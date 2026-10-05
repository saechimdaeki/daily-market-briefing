"""
AI 트레이딩 데스크 — 6개 AI 부서 LangGraph 파이프라인

  START
    ↓
  01 스크리닝부        뉴스 → 후보 종목 발굴 (realtime_bot 추출·검증 재사용)
    ↓ (fan-out)
  ┌ 02 기술적 분석부   RSI/MACD/볼린저/일목 지표
  ├ 03 펀더멘털부      시총·매출·영업이익·순현금
  └ 04 마켓부          지수 스냅샷 → 상승장/하락장/횡보장 + 전략 선택
    ↓ (fan-in)
  05 리스크관리부      비중·손절가 결정, 기준 미달은 매매 보류
    ↓
  06 운용부            매매 계획 수립 (+ 지난 계획 성과 복기) → 저널 저장 → Teams

주문은 절대 실행하지 않는다. 계획은 Teams 카드로 전달되고, 실행은 사람이 승인 후 직접 한다.
"""

import json
import os
import time
from datetime import datetime

import pytz
import requests
import yfinance as yf
from langgraph.graph import END, START, StateGraph
from typing import TypedDict

from agents.claude_cli import ask_claude, ask_claude_json
from realtime_bot import (
    align_stocks_to_news_context,
    calculate_technical_indicators,
    extract_tickers_from_news,
    fetch_company_financial_profile,
    fetch_company_name_by_code,
    format_money,
    get_finance_news_headlines,
    get_market_snapshot,
    validate_target_stocks,
)

KST = pytz.timezone("Asia/Seoul")
JOURNAL_PATH = os.environ.get("DESK_JOURNAL_PATH", "desk_journal.json")
MAX_CANDIDATES = 8          # ponytail: 후보 상한 — yfinance/LLM 호출 수 제한
MAX_WEIGHT_PCT = 20         # 종목당 최대 비중 (리스크관리부 하드 캡)
REGIME_TOTAL_CAP = {"상승장": 80, "횡보장": 50, "하락장": 30}  # 장세별 총 투자 비중 상한


class DeskState(TypedDict, total=False):
    headlines: list
    candidates: list       # [{name, ticker, market, reason}]
    technicals: dict       # ticker → indicators
    fundamentals: dict     # ticker → financial profile summary
    regime: dict           # {regime, strategy, rationale, snapshot_text}
    risk_reviews: list     # [{ticker, verdict, weight_pct, stop_loss, reason}]
    plan: dict             # 운용부 최종 계획
    review_text: str       # 지난 계획 복기


def _num(x):
    return round(float(x), 2) if x is not None else None


# ── 01 스크리닝부 ──────────────────────────────────────────────────────────────
def screening(state: DeskState) -> dict:
    headlines = get_finance_news_headlines()
    stocks = align_stocks_to_news_context(headlines, extract_tickers_from_news(headlines))
    validated = validate_target_stocks(stocks)
    for c in validated:  # 국내 상장은 네이버 공식 한글명으로 (Samsung Electronics → 삼성전자)
        if c["market"] == "KR":
            c["name"] = fetch_company_name_by_code(c["ticker"].split(".")[0]) or c["name"]
    half = MAX_CANDIDATES // 2
    kr = [c for c in validated if c["market"] == "KR"]
    us = [c for c in validated if c["market"] != "KR"]
    # 한·미 절반씩, 한쪽이 모자라면 다른 쪽으로 채움
    n_kr = min(len(kr), max(half, MAX_CANDIDATES - len(us)))
    candidates = kr[:n_kr] + us[:MAX_CANDIDATES - n_kr]
    print(f"[스크리닝부] 후보 {len(candidates)}개: {[c['name'] for c in candidates]}")
    return {"headlines": headlines, "candidates": candidates}


# ── 02 기술적 분석부 ───────────────────────────────────────────────────────────
def technical(state: DeskState) -> dict:
    out = {}
    for c in state["candidates"]:
        ind = calculate_technical_indicators(c["ticker"])
        if ind:
            out[c["ticker"]] = {k: (_num(v) if k != "signals" else v) for k, v in ind.items()}
    print(f"[기술적 분석부] 지표 산출 {len(out)}개")
    return {"technicals": out}


# ── 03 펀더멘털부 ──────────────────────────────────────────────────────────────
def fundamental(state: DeskState) -> dict:
    out = {}
    for c in state["candidates"]:
        prof = fetch_company_financial_profile(c["ticker"], c.get("market", "KR"))
        out[c["ticker"]] = prof["summary"] if prof else "재무 데이터 없음"
    print(f"[펀더멘털부] 재무 확인 {len(out)}개")
    return {"fundamentals": out}


# ── 04 마켓부 ──────────────────────────────────────────────────────────────────
def market(state: DeskState) -> dict:
    snap = get_market_snapshot()
    snapshot_text = "\n".join(
        f"- {k}: {v['last']:,.2f} (1일 {v['chg_1d']:+.2f}%, 5일 {v['chg_5d']:+.2f}%, 20일선 {'위' if v['above_ma20'] else '아래'})"
        for k, v in snap.items()
    )
    prompt = f"""너는 증권사 마켓부장이다. 아래 지표와 헤드라인으로 현재 장세를 판정하고 전략을 고른다.

[지표]
{snapshot_text}

[헤드라인]
{json.dumps(state["headlines"][:20], ensure_ascii=False)}

regime은 반드시 "상승장", "하락장", "횡보장" 중 하나.
strategy는 이 장세에 맞는 전략 조합 이름 (예: 추세추종+눌림목 매수, 박스권 역추세, 현금비중 확대+방어주).
JSON 형식: {{"regime": "...", "strategy": "...", "rationale": "수치 근거 포함 2문장"}}"""
    try:
        regime = ask_claude_json(prompt)
    except Exception as e:
        print(f"[마켓부] 판정 실패: {e}")
        regime = {}
    if regime.get("regime") not in REGIME_TOTAL_CAP:
        regime = {"regime": "횡보장", "strategy": "관망", "rationale": "장세 판정 실패 — 보수적 기본값"}
    regime["snapshot_text"] = snapshot_text
    print(f"[마켓부] {regime['regime']} / {regime['strategy']}")
    return {"regime": regime}


def _candidate_dossier(state: DeskState) -> list:
    """기술·펀더멘털 데이터가 모두 있는 후보만 리스크 심사 대상."""
    return [
        {**c, "technical": state["technicals"][c["ticker"]], "fundamental": state["fundamentals"].get(c["ticker"])}
        for c in state["candidates"]
        if c["ticker"] in state["technicals"]
    ]


# ── 05 리스크관리부 ────────────────────────────────────────────────────────────
def risk(state: DeskState) -> dict:
    dossier = _candidate_dossier(state)
    regime = state["regime"]
    total_cap = REGIME_TOTAL_CAP[regime["regime"]]
    if not dossier:
        return {"risk_reviews": []}

    prompt = f"""너는 리스크관리부장이다. 공격적 아이디어에 반대하고 자본을 지키는 것이 임무다.
장세: {regime['regime']} / 전략: {regime['strategy']}
총 투자 비중 상한: {total_cap}%, 종목당 최대 {MAX_WEIGHT_PCT}%.

[후보 종목 자료]
{json.dumps(dossier, ensure_ascii=False)}

각 종목에 대해:
- verdict: "통과" 또는 "보류" (RSI 과열, 밴드 상단 과이탈, 재무 취약, 뉴스 근거 빈약, 장세 불일치면 보류)
- weight_pct: 통과 시 비중(%), 보류면 0
- stop_loss: 통과 시 손절가 (볼린저 하단·기준선·피보나치 50% 참고, 현재가보다 낮아야 함), 보류면 null
- reason: 한 줄 근거
JSON 형식: {{"reviews": [{{"ticker": "...", "verdict": "...", "weight_pct": 0, "stop_loss": null, "reason": "..."}}]}}"""
    try:
        reviews = [r for r in ask_claude_json(prompt).get("reviews", []) if isinstance(r, dict)]
    except Exception as e:
        print(f"[리스크관리부] 심사 실패 → 전원 보류: {e}")
        reviews = [{"ticker": d["ticker"], "verdict": "보류", "weight_pct": 0, "stop_loss": None, "reason": "심사 실패"} for d in dossier]

    # 하드 룰: LLM 출력과 무관하게 코드로 강제
    prices = {d["ticker"]: d["technical"]["price"] for d in dossier}
    total = 0
    for r in reviews:
        price = prices.get(r.get("ticker"))
        stop = r.get("stop_loss")
        bad_stop = not isinstance(stop, (int, float)) or price is None or stop >= price
        if r.get("verdict") != "통과" or bad_stop:
            if r.get("verdict") == "통과":
                r["reason"] = f"손절가 무효로 보류 ({r.get('reason', '')})"
            r.update(verdict="보류", weight_pct=0, stop_loss=None)
            continue
        w = min(float(r.get("weight_pct") or 0), MAX_WEIGHT_PCT, total_cap - total)
        r["weight_pct"] = max(w, 0)
        if r["weight_pct"] == 0:
            r.update(verdict="보류", stop_loss=None, reason="총 비중 상한 초과")
        total += r["weight_pct"]
    print(f"[리스크관리부] 통과 {sum(r['verdict'] == '통과' for r in reviews)}/{len(reviews)}, 총 비중 {total}%")
    return {"risk_reviews": reviews}


# ── 학습: 지난 계획 복기 ───────────────────────────────────────────────────────
def _load_journal() -> list:
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _review_past_plans(journal: list) -> str:
    """최근 5회 계획의 진입가 대비 현재 수익률 — 운용부가 다음 계획에 반영."""
    lines = []
    today = datetime.now(KST).strftime("%Y-%m-%d")
    past = [e for e in journal if not e["date"].startswith(today)]  # 당일 계획은 성과가 없으니 제외
    for entry in past[-5:]:
        for p in entry.get("orders", []):
            try:
                now = float(yf.Ticker(p["ticker"]).history(period="5d")["Close"].dropna().iloc[-1])
                ret = (now / p["entry"] - 1) * 100
                hit = "손절선 이탈" if now <= p["stop_loss"] else ("목표 도달" if now >= p["target"] else "진행중")
                lines.append(f"- {entry['date']} {p['name']}({p['ticker']}) {entry['regime']}/{entry['strategy']}: {ret:+.2f}% [{hit}]")
            except Exception:
                continue
    return "\n".join(lines) or "복기할 과거 계획 없음"


# ── 06 운용부 ──────────────────────────────────────────────────────────────────
def operations(state: DeskState) -> dict:
    journal = _load_journal()
    review_text = _review_past_plans(journal)
    passed = [r for r in state["risk_reviews"] if r["verdict"] == "통과"]
    dossier = {d["ticker"]: d for d in _candidate_dossier(state)}
    regime = state["regime"]

    plan = {"summary": "리스크 기준을 통과한 종목이 없어 오늘은 관망합니다.", "orders": []}
    if passed:
        prompt = f"""너는 운용부장이다. 각 부서 분석을 하나의 매매 계획으로 정리한다.
장세: {regime['regime']} / 전략: {regime['strategy']} — {regime['rationale']}

[리스크관리부 통과 종목 (비중·손절가 확정, 변경 금지)]
{json.dumps([{**r, **dossier[r['ticker']]} for r in passed if r['ticker'] in dossier], ensure_ascii=False)}

[지난 계획 복기 — 실패 패턴은 피하고 성공 패턴은 반영]
{review_text}

각 종목에 대해 entry(진입가, 현재가 근처), target(목표가, 손익비 2:1 이상 지향), thesis(한 줄 매수 논리)를 정한다.
JSON 형식: {{"summary": "오늘 계획 2문장 (복기에서 얻은 교훈 포함)", "orders": [{{"ticker": "...", "entry": 0, "target": 0, "thesis": "..."}}]}}"""
        try:
            raw = ask_claude_json(prompt)
            risk_by_ticker = {r["ticker"]: r for r in passed}
            orders = []
            for o in raw.get("orders", []):
                r, d = risk_by_ticker.get(o.get("ticker")), dossier.get(o.get("ticker"))
                if not (r and d and isinstance(o.get("entry"), (int, float)) and isinstance(o.get("target"), (int, float))):
                    continue
                if not (r["stop_loss"] < o["entry"] < o["target"]):
                    continue  # 손절 < 진입 < 목표 아니면 버림
                orders.append({
                    "name": d["name"], "ticker": d["ticker"], "market": d.get("market", "KR"),
                    "entry": o["entry"], "target": o["target"], "stop_loss": r["stop_loss"],
                    "weight_pct": r["weight_pct"], "thesis": o.get("thesis", ""),
                })
            plan = {"summary": raw.get("summary", ""), "orders": orders}
        except Exception as e:
            print(f"[운용부] 계획 수립 실패: {e}")

    journal.append({
        "date": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "regime": regime["regime"], "strategy": regime["strategy"],
        "orders": plan["orders"],
    })
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(journal[-60:], f, ensure_ascii=False, indent=1)  # ponytail: 최근 60회만 보관
    print(f"[운용부] 주문안 {len(plan['orders'])}건")
    return {"plan": plan, "review_text": review_text}


# ── Teams 전송 ─────────────────────────────────────────────────────────────────
def notify(state: DeskState) -> dict:
    regime, plan = state["regime"], state["plan"]
    techs, funds = state["technicals"], state["fundamentals"]
    head = lambda text: {"type": "TextBlock", "text": text, "weight": "Bolder", "size": "Medium", "separator": True, "spacing": "Medium"}
    names = {c["ticker"]: f"{c['name']} ({c['ticker']})" for c in state["candidates"]}
    label = lambda t: names.get(t, t)
    line = lambda text: {"type": "TextBlock", "text": text, "wrap": True, "spacing": "None"}

    body = [
        {"type": "TextBlock", "text": "🏢 AI 트레이딩 데스크 — 오늘의 매매 계획", "weight": "Bolder", "size": "Large", "color": "Accent"},
        head(f"01 스크리닝부 · 후보 {len(state['candidates'])}개 발굴"),
        *[line(f"• {c['name']} ({c['ticker']}): {c.get('reason', '')}") for c in state["candidates"]],
        head("02 기술적 분석부 · 추세·모멘텀"),
        *[line(f"• {label(t)}: RSI {v['rsi']:.1f} | {', '.join(v['signals']) or '특이 시그널 없음'}") for t, v in techs.items()],
        head("03 펀더멘털부 · 실적·재무"),
        *[line(f"• {label(t)}: {v}") for t, v in funds.items()],
        head(f"04 마켓부 · {regime['regime']} → {regime['strategy']}"),
        line(regime["rationale"]),
        head("05 리스크관리부 · 비중·손절 심사"),
        *[line(f"{'✅' if r['verdict'] == '통과' else '🛑'} {label(r['ticker'])}: "
               + (f"비중 {r['weight_pct']:g}% · " if r["verdict"] == "통과" else "")
               + r.get("reason", "")) for r in state["risk_reviews"]],
        head(f"06 운용부 · 매매 계획 {len(plan['orders'])}건"),
        line(plan["summary"]),
    ]
    for o in plan["orders"]:
        m = o["market"]
        body += [
            {"type": "TextBlock", "text": f"🎯 {o['name']} ({o['ticker']}) · 비중 {o['weight_pct']:g}%", "weight": "Bolder", "color": "Good", "spacing": "Small"},
            {"type": "FactSet", "facts": [
                {"title": "진입", "value": format_money(o["entry"], m)},
                {"title": "목표", "value": format_money(o["target"], m)},
                {"title": "손절", "value": format_money(o["stop_loss"], m)},
                {"title": "논리", "value": o["thesis"]},
            ]},
        ]
    body += [
        head("📚 지난 계획 복기"),
        line(state["review_text"].replace("\n", "\n\n")),
        {"type": "TextBlock", "text": "과거 성과는 미래 수익을 보장하지 않습니다.", "wrap": True, "size": "Small", "isSubtle": True, "separator": True},
    ]
    url = os.environ.get("TEAMS_WEBHOOK_URL")
    if not url:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return {}
    payload = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.2", "body": body},
    }]}
    try:
        r = requests.post(url, json=payload, timeout=30)
        print(f"Teams 전송 완료 (HTTP {r.status_code})")
    except Exception as e:
        print(f"Teams 전송 실패: {e}")
    return {}


def build_desk_graph():
    g = StateGraph(DeskState)
    for name, fn in [("screening", screening), ("technical", technical), ("fundamental", fundamental),
                     ("market", market), ("risk", risk), ("operations", operations), ("notify", notify)]:
        g.add_node(name, fn)
    g.add_edge(START, "screening")
    for dept in ("technical", "fundamental", "market"):
        g.add_edge("screening", dept)
    g.add_edge(["technical", "fundamental", "market"], "risk")  # fan-in: 세 부서 모두 완료 후
    g.add_edge("risk", "operations")
    g.add_edge("operations", "notify")
    g.add_edge("notify", END)
    return g.compile()


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    t0 = time.time()
    build_desk_graph().invoke({})
    print(f"총 {time.time() - t0:.1f}s")
