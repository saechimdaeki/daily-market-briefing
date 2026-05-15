import os
import re
import time

import requests

from agents.state import MarketBriefingState

GITHUB_PAGES_URL = "https://saechimdaeki.github.io/daily-market-briefing/"


def notify(state: MarketBriefingState) -> dict:
    """
    [Node] MS Teams 알림 (조건부 노드 — TEAMS_WEBHOOK_URL이 설정된 경우에만 실행)
    Adaptive Card로 이미지 + 시장 지표 + 요약 + 뉴스 링크 전송
    """
    t0 = time.time()
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "")

    teams_summary_text = re.sub(r"\*+", "", state.get("llm_summary_raw", ""))
    daily_news_items = state.get("daily_news_items", [])

    news_blocks: list = []
    if daily_news_items:
        news_blocks.append({
            "type": "TextBlock", "text": "📰 오늘의 주요뉴스",
            "weight": "Bolder", "size": "Medium", "separator": True,
        })
        for article in daily_news_items[:3]:
            parts = [article.get("why_it_matters", ""), article.get("summary", "")]
            news_text = "\n".join(p for p in parts if p)
            news_blocks.extend([
                {"type": "TextBlock", "text": f"• {article.get('title', '')}",
                 "weight": "Bolder", "wrap": True, "spacing": "Small"},
                {"type": "TextBlock", "text": news_text or article.get("description", ""),
                 "wrap": True, "spacing": "None"},
            ])

    kospi = state["kospi"]
    kosdaq = state["kosdaq"]
    ewy = state["ewy"]
    sp500 = state["sp500"]
    dow = state["dow"]
    nasdaq = state["nasdaq"]
    card_image_url = state.get("image_url") or f"{GITHUB_PAGES_URL.rstrip('/')}/cover.png"

    teams_payload = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.2",
                "body": [
                    {"type": "TextBlock", "text": f"🚨 {state['edition_title']}",
                     "weight": "Bolder", "size": "Medium", "color": "Accent"},
                    {"type": "Image", "url": card_image_url, "size": "Stretch"},
                    {"type": "TextBlock", "text": f"🔥 {state.get('comic_headline', '')} 🔥",
                     "weight": "Bolder", "size": "Large", "wrap": True, "horizontalAlignment": "Center"},
                    {"type": "FactSet", "facts": [
                        {"title": "KOSPI",        "value": f"{kospi['price']} ({kospi['change']})"},
                        {"title": "KOSDAQ",       "value": f"{kosdaq['price']} ({kosdaq['change']})"},
                        {"title": "EWY (한국ETF)", "value": f"{ewy['price']} ({ewy['change']})"},
                        {"title": "S&P 500",      "value": f"{sp500['price']} ({sp500['change']})"},
                        {"title": "Dow Jones",    "value": f"{dow['price']} ({dow['change']})"},
                        {"title": "NASDAQ",       "value": f"{nasdaq['price']} ({nasdaq['change']})"},
                    ]},
                    {"type": "TextBlock", "text": teams_summary_text, "wrap": True, "separator": True},
                    *news_blocks,
                ],
                "actions": [
                    *[
                        {"type": "Action.OpenUrl",
                         "title": f"📰 {a.get('publisher') or '원문'} 보기",
                         "url": a.get("url")}
                        for a in daily_news_items[:3] if a.get("url")
                    ],
                    {"type": "Action.OpenUrl", "title": "📊 프리미엄 웹페이지에서 보기",
                     "url": GITHUB_PAGES_URL},
                ],
            },
        }],
    }

    try:
        requests.post(webhook_url, json=teams_payload, timeout=10)
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "execution_log": [{"node": "notify", "label": "Teams 알림",
                                "status": "success", "duration_ms": duration_ms,
                                "detail": "Adaptive Card 전송 완료"}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "execution_log": [{"node": "notify", "label": "Teams 알림",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"notify: {e}"],
        }
