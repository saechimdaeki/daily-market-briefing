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

edition_title = "Morning Briefing: 간밤의 미장 & 국장 프리뷰" if is_morning else "Evening Briefing: 오늘 국장 마감 & 미장 프리뷰"

def bold_filter(text):
    return re.sub(r'\*+([^*]+)\*+', r'<strong>\1</strong>', text)

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

kospi = get_index_data("^KS11")
kosdaq = get_index_data("^KQ11")
sp500 = get_index_data("^GSPC")
dow = get_index_data("^DJI")

client = OpenAI(api_key=OPENAI_API_KEY)

prompt_context = "간밤의 미국 시장 주요 이슈와 오늘 한국 시장 관전 포인트" if is_morning else "오늘 한국 시장 주요 이슈와 마감 상황, 그리고 오늘 밤 미국 시장 관전 포인트"

text_prompt = f"""
현재 팩트 데이터 (절대 지어내지 말 것):
- 코스피: {kospi['price']} ({kospi['change']} - {kospi['trend']})
- 코스닥: {kosdaq['price']} ({kosdaq['change']} - {kosdaq['trend']})
- S&P500: {sp500['price']} ({sp500['change']} - {sp500['trend']})
- 다우존스: {dow['price']} ({dow['change']} - {dow['trend']})

위 실제 데이터를 무조건 반영해서 {prompt_context}를 3~5개의 핵심 포인트로 상세히 분석해 줘.
각 포인트는 글머리 기호 없이 한 줄씩 작성하고, 강조할 핵심 단어 양쪽에만 별표(**)를 붙여.
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
    dow=dow
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
                                {"title": "S&P 500", "value": f"{sp500['price']} ({sp500['change']})"},
                                {"title": "Dow Jones", "value": f"{dow['price']} ({dow['change']})"}
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