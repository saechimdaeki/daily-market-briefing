import argparse
import os
import re
from typing import List, Optional, Tuple

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from realtime_bot import (
    client,
    calculate_technical_indicators,
    fetch_company_name_by_code,
    generate_deep_analysis,
    get_korean_stock_code,
    normalize_company_name,
    resolve_market_suffix,
    search_korean_stock_by_name,
    validate_and_correct_stock,
)


TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")


def clean_stock_query(raw_query: str) -> str:
    query = (raw_query or "").strip()
    query = re.sub(r"^!주가\s*", "", query, flags=re.IGNORECASE)
    return query.strip()


def resolve_stock(query: str) -> Tuple[Optional[dict], Optional[str]]:
    cleaned_query = clean_stock_query(query)
    if not cleaned_query:
        return None, "종목명이 비어 있습니다. 예: !주가 SK하이닉스"

    upper_query = cleaned_query.upper()

    if re.fullmatch(r"\d{6}\.(KS|KQ)", upper_query):
        code = get_korean_stock_code(upper_query)
        official_name = fetch_company_name_by_code(code) if code else cleaned_query
        stock = validate_and_correct_stock(official_name or cleaned_query, upper_query)
        stock["market"] = "KR"
        return stock, None

    if re.fullmatch(r"\d{6}", cleaned_query):
        suffix = resolve_market_suffix(cleaned_query)
        if not suffix:
            return None, f"{cleaned_query} 종목코드의 시장(KS/KQ)을 확인하지 못했습니다."
        ticker = f"{cleaned_query}.{suffix}"
        official_name = fetch_company_name_by_code(cleaned_query) or cleaned_query
        stock = validate_and_correct_stock(official_name, ticker)
        stock["market"] = "KR"
        return stock, None

    korean_stock = search_korean_stock_by_name(cleaned_query)
    if korean_stock:
        stock = validate_and_correct_stock(korean_stock["name"], korean_stock["ticker"])
        stock["market"] = "KR"
        return stock, None

    if re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]{0,9}", cleaned_query):
        ticker = upper_query
        try:
            hist = yf.Ticker(ticker).history(period="1mo")
            if not hist.empty:
                return {"name": ticker, "ticker": ticker, "market": "US"}, None
        except Exception:
            pass

    return None, f"'{cleaned_query}' 종목을 찾지 못했습니다. 한국 종목명, 6자리 종목코드, 또는 정확한 해외 티커를 입력해 주세요."


def fetch_korean_stock_headlines(ticker: str, limit: int = 3) -> List[str]:
    code = get_korean_stock_code(ticker)
    if not code:
        return []

    url = "https://finance.naver.com/item/news_news.naver"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(
            url,
            params={"code": code, "page": 1, "sm": "title_entity_id.basic", "clusterId": ""},
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        response.encoding = "euc-kr"
        soup = BeautifulSoup(response.text, "html.parser")

        headlines = []
        for anchor in soup.select("td.title a"):
            title = anchor.get_text(" ", strip=True)
            if title and title not in headlines:
                headlines.append(title)
            if len(headlines) >= limit:
                break
        return headlines
    except Exception as e:
        print(f"[{ticker}] 네이버 뉴스 조회 실패: {e}")
        return []


def fetch_us_stock_headlines(ticker: str, limit: int = 3) -> List[str]:
    try:
        news_items = yf.Ticker(ticker).news or []
        headlines = []
        for item in news_items:
            title = (item or {}).get("title")
            if title and title not in headlines:
                headlines.append(title)
            if len(headlines) >= limit:
                break
        return headlines
    except Exception as e:
        print(f"[{ticker}] 해외 뉴스 조회 실패: {e}")
        return []


def fetch_relevant_headlines(stock: dict, limit: int = 3) -> List[str]:
    if stock.get("market") == "KR":
        return fetch_korean_stock_headlines(stock["ticker"], limit=limit)
    return fetch_us_stock_headlines(stock["ticker"], limit=limit)


def build_issue_summary(name: str, ticker: str, headlines: List[str], market: str) -> str:
    if not headlines:
        if market == "KR":
            return f"{name}의 최근 기술적 흐름과 수급 기대를 중심으로 점검했습니다."
        return f"{ticker}의 최근 기술적 흐름과 시장 반응을 중심으로 점검했습니다."

    prompt = f"""
다음 헤드라인을 보고 '{name}' 종목의 핵심 이슈를 한국어 한 줄로 요약해.

[규칙]
- 35자 이내
- 투자자 관점에서 바로 이해되게
- 근거 없는 해석 금지
- 문장부호 남발 금지

헤드라인:
{chr(10).join(f"- {headline}" for headline in headlines)}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[{ticker}] 이슈 요약 실패: {e}")
        return headlines[0]


def build_price_text(price: float, market: str) -> str:
    if market == "KR":
        return f"₩ {price:,.2f}"
    return f"$ {price:,.2f}"


def build_band_text(lower: float, upper: float, market: str) -> str:
    if market == "KR":
        return f"하단 ₩ {lower:,.0f} ~ 상단 ₩ {upper:,.0f}"
    return f"하단 $ {lower:,.2f} ~ 상단 $ {upper:,.2f}"


def build_base_line_text(indicators: dict, market: str) -> str:
    if market == "KR":
        return f"RSI / 기준선: {indicators['rsi']:.2f} / ₩ {indicators['kijun_sen']:,.0f}"
    return f"RSI / 기준선: {indicators['rsi']:.2f} / $ {indicators['kijun_sen']:,.2f}"


def build_reference_url(stock: dict) -> Optional[str]:
    if stock.get("market") == "KR":
        code = get_korean_stock_code(stock["ticker"])
        if code:
            return f"https://finance.naver.com/item/main.naver?code={code}"
        return None
    return f"https://finance.yahoo.com/quote/{stock['ticker']}"


def build_stock_card(stock: dict, indicators: dict, issue_summary: str, analysis: str) -> dict:
    signals = indicators.get("signals") or ["특이 신호 없음"]
    market = stock.get("market", "KR")
    reference_url = build_reference_url(stock)

    body = [
        {
            "type": "TextBlock",
            "text": f"🎯 {stock['name']} ({stock['ticker']})",
            "weight": "Bolder",
            "size": "Large",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "현재가", "value": build_price_text(indicators["price"], market)},
                {"title": "주요 이슈", "value": issue_summary},
                {"title": "기술적 신호", "value": "\n".join(f"• {signal}" for signal in signals)},
                {"title": "볼린저 밴드", "value": build_band_text(indicators["bb_lower"], indicators["bb_upper"], market)},
                    {"title": "RSI / 기준선", "value": build_base_line_text(indicators, market)},
            ],
        },
        {
            "type": "TextBlock",
            "text": analysis,
            "wrap": True,
            "spacing": "Medium",
        },
    ]

    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }

    if reference_url:
        card["actions"] = [
            {
                "type": "Action.OpenUrl",
                "title": "종목 상세 보기",
                "url": reference_url,
            }
        ]

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


def build_error_card(message: str, query: str) -> dict:
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "⚠️ 종목 조회 실패",
                            "weight": "Bolder",
                            "size": "Large",
                        },
                        {
                            "type": "TextBlock",
                            "text": f"입력값: {query}",
                            "wrap": True,
                            "spacing": "Medium",
                        },
                        {
                            "type": "TextBlock",
                            "text": message,
                            "wrap": True,
                            "spacing": "Small",
                        },
                    ],
                    "msteams": {"width": "Full"},
                },
            }
        ],
    }


def post_to_teams(payload: dict) -> None:
    if not TEAMS_WEBHOOK_URL:
        raise RuntimeError("TEAMS_WEBHOOK_URL 환경 변수가 설정되지 않았습니다.")

    response = requests.post(TEAMS_WEBHOOK_URL, json=payload, timeout=15)
    response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="팀즈용 단일 종목 브리핑 카드 생성")
    parser.add_argument("--query", required=True, help="종목명 또는 티커. 예: SK하이닉스, 000660.KS, NVDA")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query = clean_stock_query(args.query)
    stock, error_message = resolve_stock(query)

    if not stock:
        post_to_teams(build_error_card(error_message or "종목을 찾지 못했습니다.", query))
        return 0

    indicators = calculate_technical_indicators(stock["ticker"])
    if indicators is None:
        message = f"{stock['ticker']} 가격 데이터를 불러오지 못했습니다."
        post_to_teams(build_error_card(message, query))
        return 0

    headlines = fetch_relevant_headlines(stock)
    issue_summary = build_issue_summary(stock["name"], stock["ticker"], headlines, stock.get("market", "KR"))
    analysis = generate_deep_analysis(
        stock["name"],
        issue_summary,
        indicators,
        market=stock.get("market", "KR"),
    )
    payload = build_stock_card(stock, indicators, issue_summary, analysis)
    post_to_teams(payload)

    print(f"Teams 카드 전송 완료: {stock['name']} ({stock['ticker']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
