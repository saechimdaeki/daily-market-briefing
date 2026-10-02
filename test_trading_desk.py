"""리스크관리부 하드 룰 검증: python test_trading_desk.py"""
import trading_desk as td

state = {
    "candidates": [{"name": n, "ticker": t, "market": "KR"} for n, t in [("A", "A"), ("B", "B"), ("C", "C"), ("D", "D")]],
    "technicals": {t: {"price": 100.0} for t in "ABCD"},
    "fundamentals": {},
    "regime": {"regime": "하락장", "strategy": "x"},  # 총 비중 상한 30%
}
td.ask_claude_json = lambda prompt: {"reviews": [
    {"ticker": "A", "verdict": "통과", "weight_pct": 50, "stop_loss": 90},   # 20%로 캡
    {"ticker": "B", "verdict": "통과", "weight_pct": 20, "stop_loss": 95},   # 남은 10%만
    {"ticker": "C", "verdict": "통과", "weight_pct": 10, "stop_loss": 105},  # 손절가 > 현재가 → 보류
    {"ticker": "D", "verdict": "통과", "weight_pct": 10, "stop_loss": 90},   # 총 비중 초과 → 보류
]}
r = {x["ticker"]: x for x in td.risk(state)["risk_reviews"]}
assert r["A"]["weight_pct"] == 20 and r["B"]["weight_pct"] == 10, r
assert r["C"]["verdict"] == "보류" and r["D"]["verdict"] == "보류", r

# 스크리닝 한·미 균형: KR 2개뿐이면 US로 채움
c = lambda m, i: {"name": f"{m}{i}", "ticker": f"{m}{i}", "market": m}
td.get_finance_news_headlines = lambda: []
td.extract_tickers_from_news = td.align_stocks_to_news_context = lambda *a: []
td.validate_target_stocks = lambda _: [c("US", i) for i in range(10)] + [c("KR", i) for i in range(2)]
picked = [x["market"] for x in td.screening({})["candidates"]]
assert picked.count("KR") == 2 and len(picked) == 8, picked
td.validate_target_stocks = lambda _: [c("US", i) for i in range(10)] + [c("KR", i) for i in range(10)]
picked = [x["market"] for x in td.screening({})["candidates"]]
assert picked.count("KR") == 4 and picked.count("US") == 4, picked

# 복기: 당일 계획 제외
from datetime import datetime
assert td._review_past_plans([{"date": datetime.now(td.KST).strftime("%Y-%m-%d 08:00"), "orders": [{"ticker": "X"}]}]) == "복기할 과거 계획 없음"
print("ok")
