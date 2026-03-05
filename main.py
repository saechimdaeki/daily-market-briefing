import os
import requests
import yfinance as yf
from datetime import datetime
import pytz
from jinja2 import Environment, FileSystemLoader
from openai import OpenAI
import re

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

headline_prompt = f"다음 요약 내용을 바탕으로 아주 짧고 강렬한 한 줄 헤드라인(15자 내외)을 만들어줘. 특수기호나 마크다운 금지. \n\n내용: {llm_summary_raw}"
headline_response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": headline_prompt}]
)
comic_headline = headline_response.choices[0].message.content.strip()

image_prompt = f"""
A fun, 4-panel comic strip in a hand-drawn webtoon style, summarizing the stock market theme: '{comic_headline}'.
Style: Playful, chibi characters (adorable bulls and bears), soft pastel colors, bold outlines.
Layout: A 2x2 square grid.
Content:
- Include expressive speech bubbles and thought clouds in each panel.
- INSIDE the bubbles, use ONLY short, impactful English words, onomatopoeia, or icons to convey emotion and meaning.
- Examples of allowed text: "WOW!", "OH NO!", "BOOM!", "CRASH!", "TO THE MOON!", "HODL!", "BUY!", "SELL?", "PROFIT!", "PANIC!".
- Use icons like 📈, 📉, 💰, 🚀, 😭, 😍 alongside or instead of text.
- DO NOT write full sentences or complex grammar. Keep it punchy and comic-like.
- Ensure the text is drawn clearly within the bubbles as part of the artwork.
"""

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