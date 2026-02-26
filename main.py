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

def get_index(ticker):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if not data.empty:
            return round(data['Close'].iloc[-1], 2)
        return "N/A"
    except Exception:
        return "Error"

kospi_current = get_index("^KS11")
kosdaq_current = get_index("^KQ11")
sp500_current = get_index("^GSPC")
dow_current = get_index("^DJI")

client = OpenAI(api_key=OPENAI_API_KEY)

prompt_context = "간밤의 미국 시장 주요 이슈와 오늘 한국 시장 관전 포인트" if is_morning else "오늘 한국 시장 주요 이슈와 마감 상황, 그리고 오늘 밤 미국 시장 관전 포인트"

text_prompt = f"""
현재 지수 - 코스피: {kospi_current}, 코스닥: {kosdaq_current}, S&P500: {sp500_current}, 다우존스: {dow_current}
이 지수와 최신 경제 뉴스, 기업 실적, 지정학적 리스크를 바탕으로 {prompt_context}를 상세히 분석해 줘.
구체적인 수치, 등락률, 금액을 반드시 포함해서 3~5개의 핵심 포인트로 정리해 줘.
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
A highly detailed, premium 3D isometric illustration for a modern financial technology blog.
Theme: {comic_headline}.
Style: Clean minimalist white background, soft studio lighting, glossy and sleek finish.
Elements: Neatly arranged, high-end 3D icons such as a glowing server, a rising green chart, a sleek rocket, and gold coins.
Layout: Very spacious, modern, and uncluttered.
Crucially: DO NOT write any text, words, or numbers. Purely visual 3D objects only.
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
    kospi_price=f"{kospi_current:,}" if isinstance(kospi_current, (int, float)) else kospi_current,
    kosdaq_price=f"{kosdaq_current:,}" if isinstance(kosdaq_current, (int, float)) else kosdaq_current,
    sp500_price=f"{sp500_current:,}" if isinstance(sp500_current, (int, float)) else sp500_current,
    dow_price=f"{dow_current:,}" if isinstance(dow_current, (int, float)) else dow_current
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
                                {"title": "KOSPI", "value": f"{kospi_current:,}" if isinstance(kospi_current, (int, float)) else kospi_current},
                                {"title": "KOSDAQ", "value": f"{kosdaq_current:,}" if isinstance(kosdaq_current, (int, float)) else kosdaq_current},
                                {"title": "S&P 500", "value": f"{sp500_current:,}" if isinstance(sp500_current, (int, float)) else sp500_current},
                                {"title": "Dow Jones", "value": f"{dow_current:,}" if isinstance(dow_current, (int, float)) else dow_current}
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
                            "title": "📊 웹페이지에서 보기",
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