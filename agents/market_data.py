import math
import time

import requests
import yfinance as yf

from agents.state import MarketBriefingState


def _get_korean_index_data(market_type: str) -> dict:
    url = f"https://m.stock.naver.com/api/index/{market_type}/basic"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        data = res.json()

        price = data["closePrice"]
        diff = data["compareToPreviousClosePrice"]
        ratio = data["fluctuationsRatio"]
        trend_code = data["compareToPreviousPrice"]["code"]

        if trend_code in ["1", "2"]:
            color, sign, trend = "#ef4444", "▲", "상승"
        elif trend_code in ["4", "5"]:
            color, sign, trend = "#3b82f6", "▼", "하락"
        else:
            color, sign, trend = "#6b7280", "-", "보합"

        return {
            "price": price,
            "change": f"{sign} {diff.replace('-', '')} ({float(ratio):+.2f}%)",
            "color": color,
            "trend": trend,
        }
    except Exception as e:
        print(f"네이버 금융 API 에러 ({market_type}): {e}")
        return {"price": "N/A", "change": "", "color": "#000", "trend": ""}


def _get_index_data(ticker: str) -> dict:
    try:
        data = yf.Ticker(ticker).history(period="7d", interval="1d")
        closes = data["Close"].dropna()

        if len(closes) >= 2:
            today_close = float(closes.iloc[-1])
            yesterday_close = float(closes.iloc[-2])

            if not math.isfinite(today_close) or not math.isfinite(yesterday_close) or yesterday_close == 0:
                raise ValueError("유효하지 않은 종가 데이터")

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
                "trend": trend,
            }
        print(f"yfinance 유효 종가 부족: {ticker}")
    except Exception as e:
        print(f"yfinance 데이터 조회 실패 ({ticker}): {e}")
    return {"price": "N/A", "change": "", "color": "#000", "trend": ""}


def _build_market_snapshot(kospi, kosdaq, sp500, dow, nasdaq, ewy) -> str:
    return "\n".join([
        f"- KOSPI: {kospi['price']} / {kospi['change']} / {kospi['trend']}",
        f"- KOSDAQ: {kosdaq['price']} / {kosdaq['change']} / {kosdaq['trend']}",
        f"- S&P 500: {sp500['price']} / {sp500['change']} / {sp500['trend']}",
        f"- DOW JONES: {dow['price']} / {dow['change']} / {dow['trend']}",
        f"- NASDAQ: {nasdaq['price']} / {nasdaq['change']} / {nasdaq['trend']}",
        f"- EWY: {ewy['price']} / {ewy['change']} / {ewy['trend']}",
    ])


def collect_market_data(state: MarketBriefingState) -> dict:
    """
    [Node] 시장 데이터 수집
    - 국내 지수: 네이버 금융 모바일 API (KOSPI, KOSDAQ)
    - 해외 지수 / ETF: yfinance (S&P500, Dow, NASDAQ, EWY)
    """
    t0 = time.time()
    try:
        kospi = _get_korean_index_data("KOSPI")
        kosdaq = _get_korean_index_data("KOSDAQ")
        sp500 = _get_index_data("^GSPC")
        dow = _get_index_data("^DJI")
        nasdaq = _get_index_data("^IXIC")
        ewy = _get_index_data("EWY")
        market_snapshot = _build_market_snapshot(kospi, kosdaq, sp500, dow, nasdaq, ewy)

        duration_ms = int((time.time() - t0) * 1000)
        detail = f"KOSPI {kospi['price']} | KOSDAQ {kosdaq['price']} | S&P500 {sp500['price']}"
        return {
            "kospi": kospi,
            "kosdaq": kosdaq,
            "sp500": sp500,
            "dow": dow,
            "nasdaq": nasdaq,
            "ewy": ewy,
            "market_snapshot": market_snapshot,
            "execution_log": [{"node": "collect_market_data", "label": "시장 데이터 수집",
                                "status": "success", "duration_ms": duration_ms, "detail": detail}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "execution_log": [{"node": "collect_market_data", "label": "시장 데이터 수집",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"collect_market_data: {e}"],
        }
