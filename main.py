import os
import json
import requests
import yfinance as yf
from datetime import datetime
import pytz
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
import re
from realtime_bot import (
    align_stocks_to_news_context,
    calculate_technical_indicators,
    extract_tickers_from_news,
    get_finance_news_headlines,
    validate_target_stocks,
)
from theme_detector import detect_market_themes

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

OPENAI_API_KEY = os.environ.get("AI_API_KEY") 
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")
GITHUB_PAGES_URL = "https://saechimdaeki.github.io/daily-market-briefing/"

OUTPUT_DIR = "public"
os.makedirs(OUTPUT_DIR, exist_ok=True)

kst = pytz.timezone('Asia/Seoul')
now_kst = datetime.now(kst)
current_time_str = now_kst.strftime("%Y-%m-%d %H:%M:%S")
is_morning = now_kst.hour < 12

edition_title = "Morning Briefing: 간밤의 미장 & 국장 프리뷰" if is_morning else "Evening Briefing: 오늘 국장 실시간 & 미장 프리뷰"

def bold_filter(text):
    return re.sub(r'\*+([^*]+)\*+', r'<strong>\1</strong>', text)

def strip_code_fence(text):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()

def build_market_snapshot(kospi, kosdaq, sp500, dow, nasdaq, ewy):
    return "\n".join([
        f"- KOSPI: {kospi['price']} / {kospi['change']} / {kospi['trend']}",
        f"- KOSDAQ: {kosdaq['price']} / {kosdaq['change']} / {kosdaq['trend']}",
        f"- S&P 500: {sp500['price']} / {sp500['change']} / {sp500['trend']}",
        f"- DOW JONES: {dow['price']} / {dow['change']} / {dow['trend']}",
        f"- NASDAQ: {nasdaq['price']} / {nasdaq['change']} / {nasdaq['trend']}",
        f"- EWY: {ewy['price']} / {ewy['change']} / {ewy['trend']}",
    ])


def collect_theme_snapshot(client):
    try:
        headlines = get_finance_news_headlines()
        if not headlines:
            return {"themes": [], "market_regime_note": "오늘은 반복적으로 부각된 테마를 포착하지 못했습니다."}

        stocks = extract_tickers_from_news(headlines)
        stocks = align_stocks_to_news_context(headlines, stocks)
        stocks = validate_target_stocks(stocks)

        indicator_lookup = {}
        for stock in stocks:
            ticker = stock.get("ticker")
            if not ticker:
                continue
            indicators = calculate_technical_indicators(ticker)
            if indicators:
                indicator_lookup[ticker] = indicators

        return detect_market_themes(
            headlines=headlines,
            stocks=stocks,
            indicator_lookup=indicator_lookup,
            client=client,
            max_themes=5,
        )
    except Exception as exc:
        print(f"테마 스냅샷 생성 실패: {exc}")
        return {"themes": [], "market_regime_note": "오늘은 반복적으로 부각된 테마를 포착하지 못했습니다."}

def build_image_prompt(client, comic_headline, llm_summary_raw, market_snapshot, prompt_context):
    visual_brief_prompt = f"""
너는 금융 시사만평과 증권사 커버 아트에 특화된 아트 디렉터다.
목표는 '귀여운 반응짤'이 아니라, 그날 시장을 움직인 촉매와 투자 심리가 한눈에 읽히는 4컷 커버 장면 기획서를 만드는 것이다.

[시장 맥락]
{prompt_context}

[시장 데이터]
{market_snapshot}

[요약]
{llm_summary_raw}

[판단 원칙]
1. 먼저 요약에서 시장을 움직인 핵심 촉매를 하나로 특정해라.
2. 그 촉매가 실존 인물, 정책 결정자, 정치 이벤트, 기자회견, 관세, 금리, 전쟁 리스크, AI 투자, 반도체 수출 규제, 유가 급등 같은 사건이면, 그 촉매를 그림에서 즉시 인식 가능하게 만들어라.
3. 실존 인물이 핵심이면 그 인물의 recognizably editorial caricature를 전면 배치해라.
4. 촉매가 인물이 아니라면, 그 사건을 상징하는 장소와 소품을 전면 배치해라. 예: 연준 회견장, 백악관 브리핑룸, 관세 문서, 수출 통제 서류, GPU 서버랙, 유조선, 미사일 경보, 반도체 클린룸.
5. 각 컷은 서로 다른 시장 포인트를 설명해야 하며 같은 리액션을 반복하면 안 된다.
6. 투자자 심리, 포지셔닝 변화, 리스크 온오프, 섹터 회전이 장면에서 읽혀야 한다.
7. 귀여움, 마스코트, 캐릭터 상품 같은 감성은 금지한다.

[강한 금지 사항]
- 황소 캐릭터, 곰 캐릭터, 치비 캐릭터, 동물 마스코트 사용 금지
- 의미 없는 리액션샷 4연속 금지
- 파스텔 위주의 유아풍 톤 금지
- 브랜드 로고, 저작권 캐릭터, 읽기 어려운 긴 문장 금지
- 사건과 무관한 랜덤 돈주머니, 로켓, 하트 남발 금지

[장면 설계 원칙]
- 한국 투자자가 바로 이해할 수 있는 뉴스룸, 트레이딩 데스크, 중앙은행 회견장, 기자회견장, 국회/백악관 스타일 브리핑룸, 데이터센터, 항만, 반도체 공장, 차트 월, 재난경보실 같은 공간을 우선 사용
- 각 컷은 다른 카메라 거리와 구도를 써라. 와이드샷, 미디엄샷, 클로즈업, 오버헤드 중 섞어서 사용
- 화면 안의 인물, 표정, 소품, 전광판, 차트 방향만 봐도 장세가 읽혀야 한다
- 텍스트는 최소화하되 들어간다면 1~3단어 캡션만 허용
- 은유는 허용하지만 실제 데이터와 직접 연결되어야 한다
- 결과물은 시사만평처럼 날카롭되, 동시에 잡지 커버처럼 세련되고 아름다워야 한다
- 색감, 조명, 구도, 레이어 깊이가 살아 있어야 하며 조잡하거나 낙서처럼 보여서는 안 된다

아래 JSON만 출력해라. 백틱 금지.
{{
  "primary_catalyst": "시장을 움직인 핵심 인물 또는 사건",
  "catalyst_type": "person | policy | macro | geopolitical | earnings | sector",
  "must_show": ["반드시 보일 요소1", "요소2"],
  "visual_style": "전체 그림 스타일 한 줄",
  "color_palette": "색감 방향 한 줄",
  "mood_keywords": ["키워드1", "키워드2", "키워드3", "키워드4"],
  "panels": [
    {{
      "focus": "이 컷이 설명하는 시장 포인트",
      "shot": "wide | medium | close-up | overhead",
      "scene": "장면 설명",
      "characters": "등장인물/오브젝트",
      "symbol": "핵심 상징",
      "caption": "1~3단어"
    }}
  ]
}}
"""

    fallback_brief = {
        "primary_catalyst": "overnight macro shock and positioning battle",
        "catalyst_type": "macro",
        "must_show": ["US index board", "EWY monitor", "Korean trading desk"],
        "visual_style": "polished Korean editorial illustration, premium finance magazine cover, cinematic composition, expressive human faces, layered lighting",
        "color_palette": "electric red and cobalt blue market colors, emergency amber lights, refined ticker green accents, warm paper undertones, crisp black ink lines",
        "mood_keywords": ["satirical", "cinematic", "urgent", "high-contrast"],
        "panels": [
            {
                "focus": "overnight US market and EWY setting the tone",
                "shot": "wide",
                "scene": "a tense pre-market war room where traders stare at flashing US index boards and a wobbling EWY monitor while a policy headline slams onto the main screen",
                "characters": "retail investor, exhausted strategist, anchor on a breaking-news monitor",
                "symbol": "split scoreboard",
                "caption": "Night Shift"
            },
            {
                "focus": "KOSPI and KOSDAQ diverging or accelerating together",
                "shot": "medium",
                "scene": "two market elevators moving at different speeds with investors switching lanes in a panic",
                "characters": "office workers, day traders, a smug algorithm bot",
                "symbol": "double elevator",
                "caption": "Rotation"
            },
            {
                "focus": "the key risk or momentum hiding behind the session",
                "shot": "close-up",
                "scene": "a boxing ring where greed and fear trade blows while screens throw off warning lights",
                "characters": "two human traders, referee analyst, crowd of phone-holding investors",
                "symbol": "boxing bell",
                "caption": "Risk On?"
            },
            {
                "focus": "today's actionable takeaway",
                "shot": "overhead",
                "scene": "a trader at a forked road choosing between chase, hedge, and wait while price candles explode overhead",
                "characters": "solo investor, shadowy fund manager, directional arrows",
                "symbol": "three-way crossroads",
                "caption": "Your Move"
            }
        ]
    }

    try:
        visual_brief_response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.9,
            messages=[{"role": "user", "content": visual_brief_prompt}]
        )
        visual_brief = json.loads(strip_code_fence(visual_brief_response.choices[0].message.content))
        if len(visual_brief.get("panels", [])) != 4:
            raise ValueError("4컷 구성이 아님")
    except Exception as e:
        print(f"비주얼 브리프 생성 실패: {e}")
        visual_brief = fallback_brief

    mood_keywords = ", ".join(visual_brief.get("mood_keywords", fallback_brief["mood_keywords"]))
    must_show = ", ".join(visual_brief.get("must_show", fallback_brief["must_show"]))
    panels = visual_brief.get("panels", fallback_brief["panels"])
    panel_directions = "\n".join([
        (
            f"- Panel {idx}: focus={panel.get('focus', '')}; shot={panel.get('shot', '')}; scene={panel.get('scene', '')}; "
            f"characters={panel.get('characters', '')}; symbol={panel.get('symbol', '')}; "
            f"caption={panel.get('caption', '')}"
        )
        for idx, panel in enumerate(panels, start=1)
    ])

    return f"""
Create a bold 4-panel editorial comic cover about the stock market headline: "{comic_headline}".

[Story context]
{llm_summary_raw}

[Concrete market snapshot]
{market_snapshot}

[Art direction]
- Style: {visual_brief.get('visual_style', fallback_brief['visual_style'])}
- Mood: {mood_keywords}
- Palette: {visual_brief.get('color_palette', fallback_brief['color_palette'])}
- Primary catalyst: {visual_brief.get('primary_catalyst', fallback_brief['primary_catalyst'])}
- Catalyst type: {visual_brief.get('catalyst_type', fallback_brief['catalyst_type'])}
- Must-show visual anchors: {must_show}
- Tone: provocative, witty, sharp, meme-aware, financially literate, visually surprising
- Make it feel like a Korean market satire cover, political cartoon, or financial magazine illustration
- Prioritize irony, tension, positioning battle, fear vs greed, rotation, FOMO, panic, relief rallies
- Visual quality must be beautiful, premium, and polished enough to feel like a cover illustration, not a rough storyboard
- Use elegant color harmony, cinematic lighting, clean silhouette separation, rich textures, and balanced composition
- Make the image stylish and eye-catching even before reading the details
- If the market move is driven by a real public figure or policymaker, show a recognizable editorial caricature of that person prominently
- If the market move is driven by tariffs, rates, AI, semiconductors, oil, regulation, elections, or war risk, make those catalysts visually explicit through props, setting, and headlines
- Use human characters, officials, traders, anchors, analysts, or realistic symbolic objects only
- Absolutely do not use bulls, bears, animals, mascots, plushies, chibi figures, or sticker-like characters
- Avoid cute mascot energy, nursery pastel aesthetics, and repetitive faces
- Avoid muddy colors, flat lighting, cluttered composition, sloppy anatomy, or amateur doodle quality
- No copyrighted characters, no brand logos, no unreadable text walls
- If text appears, keep it very short and integrated into the artwork, max 1-3 words per panel
- Text should support the scene, but the image must still make sense without reading

[Panel blueprint]
{panel_directions}

[Composition]
- 2x2 grid, cinematic escalation from panel 1 to panel 4
- Each panel must depict a distinct market beat tied to the real data above
- Use strong visual metaphors, dynamic perspective, speed lines, alarm lights, ticker energy
- Characters can include retail investors, analysts, officials, anchors, office workers, algorithm terminals, money managers
- The final result should feel meaningful, spicy, and entertaining
"""

# 🟢 네이버 금융 모바일 API (국장 실시간/종가용)
def get_korean_index_data(market_type):
    url = f"https://m.stock.naver.com/api/index/{market_type}/basic"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers)
        data = res.json()
        
        price = data['closePrice']
        diff = data['compareToPreviousClosePrice']
        ratio = data['fluctuationsRatio']
        trend_code = data['compareToPreviousPrice']['code']
        
        if trend_code in ["1", "2"]:
            color, sign, trend = "#ef4444", "▲", "상승"
        elif trend_code in ["4", "5"]:
            color, sign, trend = "#3b82f6", "▼", "하락"
        else:
            color, sign, trend = "#6b7280", "-", "보합"
            
        return {
            "price": price,
            "change": f"{sign} {diff.replace('-','')} ({float(ratio):+.2f}%)",
            "color": color,
            "trend": trend
        }
    except Exception as e:
        print(f"네이버 금융 API 에러: {e}")
        return {"price": "N/A", "change": "", "color": "#000", "trend": ""}

# 🟢 yfinance API (미장 및 ETF용)
def get_index_data(ticker):
    try:
        data = yf.Ticker(ticker).history(period="5d")
        if len(data) >= 2:
            today_close = data['Close'].iloc[-1]
            yesterday_close = data['Close'].iloc[-2]
            diff = today_close - yesterday_close
            pct_change = (diff / yesterday_close) * 100
            
            if diff > 0:
                color, sign, trend = "#ef4444", "▲", "상승"
            elif diff < 0:
                color, sign, trend = "#3b82f6", "▼", "하락"
            else:
                color, sign, trend = "#6b7280", "-", "보합"
                
            return {
                "price": f"{today_close:,.2f}",
                "change": f"{sign} {abs(diff):.2f} ({pct_change:+.2f}%)",
                "color": color,
                "trend": trend
            }
    except Exception:
        pass
    return {"price": "N/A", "change": "", "color": "#000", "trend": ""}

# 데이터 수집 (국장은 네이버, 미장은 야후)
kospi = get_korean_index_data("KOSPI")
kosdaq = get_korean_index_data("KOSDAQ")
sp500 = get_index_data("^GSPC")
dow = get_index_data("^DJI")
nasdaq = get_index_data("^IXIC")
ewy = get_index_data("EWY")

client = OpenAI(api_key=OPENAI_API_KEY)
theme_result = collect_theme_snapshot(client)
top_themes = theme_result.get("themes", [])

prompt_context = "간밤의 미국 시장 주요 이슈와 오늘 아침 한국 시장의 개장 흐름 및 관전 포인트" if is_morning else "오늘 한국 시장 마감 상황 요약 및 오늘 밤 미국 시장 관전 포인트"

text_prompt = f"""
현재 팩트 데이터 (절대 지어내지 말 것):
- 현재 국장: 코스피 {kospi['price']} ({kospi['change']}), 코스닥 {kosdaq['price']} ({kosdaq['change']})
- 미장 데이터: S&P500 {sp500['price']} ({sp500['change']}), 다우존스 {dow['price']} ({dow['change']}), 나스닥 {nasdaq['price']} ({nasdaq['change']})
- 한국 야간지표(EWY): {ewy['price']} ({ewy['change']} - {ewy['trend']})

당신은 여의도의 실전 투자 수석 애널리스트입니다. 위 데이터를 완벽히 분석하여 {prompt_context}를 3~5개의 핵심 포인트로 작성해 줘.

[🔥 필수 분석 조건 - 반드시 지킬 것]
1. '한국 야간지표(EWY)'의 등락률과 간밤 미장 흐름을 종합적으로 언급할 것.
2. 현재 코스피/코스닥의 실제 등락 수치({kospi['price']}, {kosdaq['price']})를 바탕으로 오늘 국장 흐름을 정확히 진단할 것.
3. 데이터 간의 온도 차이가 있다면, 오늘 투자자들이 어떤 포지션을 취해야 하는지 대응 전략을 제시할 것.
4. 각 포인트는 글머리 기호 없이 한 줄씩 작성하고, 강조할 핵심 단어 양쪽에만 별표(**)를 붙일 것.
"""

text_response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": text_prompt}]
)
llm_summary_raw = text_response.choices[0].message.content.strip()
summary_items = [item.strip().lstrip('-').lstrip('*').strip() for item in llm_summary_raw.split('\n') if item.strip()]

headline_prompt = f"""
다음 요약 내용을 바탕으로, 시장의 충돌감과 아이러니가 느껴지는 아주 짧고 강렬한 한 줄 헤드라인을 만들어줘.

[규칙]
- 12자~18자 내외
- 단순 설명문 말고, 장세의 긴장감이나 온도 차가 느껴지게
- 과장 광고 문구 말고 실제 시장 요약과 맞아야 함
- 특수기호, 이모지, 마크다운 금지

내용:
{llm_summary_raw}
"""
headline_response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": headline_prompt}]
)
comic_headline = headline_response.choices[0].message.content.strip()

market_snapshot = build_market_snapshot(kospi, kosdaq, sp500, dow, nasdaq, ewy)
image_prompt = build_image_prompt(
    client=client,
    comic_headline=comic_headline,
    llm_summary_raw=llm_summary_raw,
    market_snapshot=market_snapshot,
    prompt_context=prompt_context,
)

image_response = client.images.generate(
    model="dall-e-3",
    prompt=image_prompt,
    size="1024x1024",
    quality="standard",
    n=1,
)
image_url = image_response.data[0].url

img_data = requests.get(image_url).content
with open(os.path.join(OUTPUT_DIR, 'cover.png'), 'wb') as handler:
    handler.write(img_data)

env = Environment(loader=FileSystemLoader('.'))
env.filters['bold'] = bold_filter
template = env.get_template('template.html')

html_output = template.render(
    edition_title=edition_title,
    current_time=current_time_str,
    comic_headline=comic_headline,
    summary_items=summary_items,
    themes=top_themes,
    theme_note=theme_result.get("market_regime_note", ""),
    kospi=kospi,
    kosdaq=kosdaq,
    sp500=sp500,
    dow=dow,
    nasdaq=nasdaq,
    ewy=ewy
)

with open(os.path.join(OUTPUT_DIR, 'index.html'), 'w', encoding='utf-8') as f:
    f.write(html_output)

if TEAMS_WEBHOOK_URL:
    teams_summary_text = re.sub(r'\*+', '', llm_summary_raw)
    
    teams_payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"🚨 {edition_title}",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Accent"
                        },
                        {
                            "type": "Image",
                            "url": image_url,
                            "size": "Stretch"
                        },
                        {
                            "type": "TextBlock",
                            "text": f"🔥 {comic_headline} 🔥",
                            "weight": "Bolder",
                            "size": "Large",
                            "wrap": True,
                            "horizontalAlignment": "Center"
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "KOSPI", "value": f"{kospi['price']} ({kospi['change']})"},
                                {"title": "KOSDAQ", "value": f"{kosdaq['price']} ({kosdaq['change']})"},
                                {"title": "EWY (한국ETF)", "value": f"{ewy['price']} ({ewy['change']})"},
                                {"title": "S&P 500", "value": f"{sp500['price']} ({sp500['change']})"},
                                {"title": "Dow Jones", "value": f"{dow['price']} ({dow['change']})"},
                                {"title": "NASDAQ", "value": f"{nasdaq['price']} ({nasdaq['change']})"}
                            ]
                        },
                        {
                            "type": "TextBlock",
                            "text": "📡 오늘의 테마 랭킹",
                            "weight": "Bolder",
                            "size": "Medium",
                            "separator": True,
                            "isVisible": bool(top_themes),
                        },
                        {
                            "type": "TextBlock",
                            "text": (
                                theme_result.get("market_regime_note", "") + "\n\n" + "\n".join(
                                    [
                                        f"• {theme['theme']} | 점수 {theme['score']} | {theme['stance']} | 대표 "
                                        + ", ".join([leader['name'] for leader in theme['leaders'][:3]])
                                        for theme in top_themes
                                    ]
                                )
                            ).strip(),
                            "wrap": True,
                            "isVisible": bool(top_themes),
                        },
                        {
                            "type": "TextBlock",
                            "text": teams_summary_text,
                            "wrap": True,
                            "separator": True
                        }
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "📊 프리미엄 웹페이지에서 보기",
                            "url": GITHUB_PAGES_URL
                        }
                    ]
                }
            }
        ]
    }
    try:
        requests.post(TEAMS_WEBHOOK_URL, json=teams_payload)
    except Exception:
        pass
