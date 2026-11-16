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
import math
import os
import re
import time
from datetime import datetime, timedelta

import pytz
import requests
import yfinance as yf
from langgraph.graph import END, START, StateGraph
from typing import TypedDict

from agents.claude_cli import CodexUnavailable, ask_claude, ask_claude_json
from dashboard_delivery import dashboard_url, publish_performance
from desk_research import INVERSE_HORIZON_DAYS, SWING_HORIZON_DAYS, describe, replay, run_debate
from market_context import (collect_market_context, fetch_daily, earnings_check, entry_holds, schedule)
from desk_strategy import (PROFILES, INVERSE_TOTAL_CAP, profile, collect_tactical_snapshot,
                           tactical_candidates, bearish, SEMICONDUCTOR_TICKERS, UNSUPPORTED_GEARED)
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
ENTRY_EXPIRY_DAYS = 5      # 진입가 미도달 계획은 생성 후 5일(약 3거래일) 지나면 버림
CLOSED_STATUSES = ("손절", "목표 도달", "미체결 취소", "시간 청산")
REGIME_TOTAL_CAP = {"상승장": 80, "횡보장": 50, "하락장": 30}  # 장세별 총 투자 비중 상한

KOREAN_NAMES = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "006400.KS": "삼성SDI",
    "003670.KS": "포스코퓨처엠", "207940.KS": "삼성바이오로직스",
    "COP": "코노코필립스", "MU": "마이크론", "TSM": "TSMC",
    "ASML": "에이에스엠엘", "NVDA": "엔비디아", "AVGO": "브로드컴",
    "AAPL": "애플", "MSFT": "마이크로소프트", "AMZN": "아마존",
    "GOOGL": "알파벳", "META": "메타", "TSLA": "테슬라", "INTC": "인텔",
    "PEP": "펩시코", "XOM": "엑슨모빌", "JPM": "제이피모건", "PG": "프록터앤드갬블",
}

KOREAN_NAMES.update({t:p["name"] for t,p in PROFILES.items()})

def _has_korean(text):
    return bool(re.search(r"[가-힣]", str(text or "")))


def _display_name(order):
    ticker = order["ticker"]
    if ticker in KOREAN_NAMES:
        return KOREAN_NAMES[ticker]
    name = KOREAN_NAMES.get(ticker, order.get("name", ""))
    return name if _has_korean(name) else "국내 종목" if ticker.endswith((".KS", ".KQ")) else "미국 종목"


def _localize_candidates(candidates):
    for c in candidates:
        c["name"] = KOREAN_NAMES.get(c["ticker"], c["name"])
    pending = [c for c in candidates if (c["ticker"] not in KOREAN_NAMES and not _has_korean(c["name"])) or not _has_korean(c.get("reason"))]
    if pending:
        translated = ask_claude_json(
            "다음 종목의 name을 통용되는 한국어 기업명으로, reason을 한국어 뉴스 요약으로 번역하라. "
            "티커와 사실은 변경하지 말고 모든 설명은 한국어로 쓴다. "
            'JSON 형식: {"stocks": [{"ticker": "...", "name": "...", "reason": "..."}]}\n'
            + json.dumps(pending, ensure_ascii=False)
        )
        by_ticker = {c["ticker"]: c for c in translated.get("stocks", []) if isinstance(c, dict)}
        failed = set()
        for c in pending:
            t = by_ticker.get(c["ticker"], {})
            if not ((c["ticker"] in KOREAN_NAMES or _has_korean(t.get("name"))) and _has_korean(t.get("reason"))):
                # 한 종목 번역 실패로 전체 실행을 죽이지 않고 그 종목만 제외
                print(f"[스크리닝부] 한국어 번역 실패로 제외: {c['ticker']}")
                failed.add(c["ticker"])
                continue
            c.update(name=KOREAN_NAMES.get(c["ticker"], t["name"]), reason=t["reason"])
        candidates = [c for c in candidates if c["ticker"] not in failed]
    return candidates


class DeskState(TypedDict, total=False):
    headlines: list
    candidates: list       # [{name, ticker, market, reason}]
    technicals: dict       # ticker → indicators
    fundamentals: dict     # ticker → financial profile summary
    regime: dict           # {regime, strategy, rationale, snapshot_text}
    risk_reviews: list     # [{ticker, verdict, weight_pct, stop_loss, reason}]
    plan: dict             # 운용부 최종 계획
    journal: list
    review_text: str       # 지난 계획 복기
    tactical_snapshot: dict
    market_context: dict
    data_checks: dict
    earnings_checks: dict
    dashboard_status: str
    dashboard_error: str
    debates: dict          # ticker → 강세·약세 토론 판정 (TradingAgents)


def _num(x):
    return round(float(x), 2) if x is not None else None


def prepare_context(state: DeskState) -> dict:
    context = collect_market_context()
    print(f"[시장 근거] 확인 {sum(q['status']=='확인' for q in context['quality'].values())}/{len(context['quality'])} · {context['mode']}")
    return {'market_context': context}


# ── 01 스크리닝부 ──────────────────────────────────────────────────────────────
def screening(state: DeskState) -> dict:
    headlines = get_finance_news_headlines()
    if not headlines and 'market_context' not in state:
        raise RuntimeError("뉴스 수집 실패: 트레이딩 데스크 실행·저널 저장·Teams 전송 중단")
    stocks = align_stocks_to_news_context(headlines, extract_tickers_from_news(headlines)) if headlines else []
    validated = validate_target_stocks(stocks) if headlines else []
    for c in validated:  # 국내 상장은 네이버 공식 한글명으로 (Samsung Electronics → 삼성전자)
        if c["market"] == "KR":
            c["name"] = fetch_company_name_by_code(c["ticker"].split(".")[0]) or c["name"]
    snapshot = state['market_context'].get('prices', {}) if 'market_context' in state else collect_tactical_snapshot()
    tactical = tactical_candidates(snapshot)
    context = state.get('market_context',{})
    us = context.get('markets',{}).get('US',{})
    if us.get('allow_new') and us.get('regime')=='상승장':
        leaders = [sector for sector in context.get('sectors',[]) if sector['relative_5d']>0 and sector['above_ma20']]
        for sector in leaders[:2]:
            tactical.append({'ticker':sector['ticker'],'market':'US',**profile(sector['ticker']),
                             'reason':f"섹터 상대강도 SPY 대비 {sector['relative_5d']:+.2f}%p · 20일선 상회. 뉴스와 독립된 추세 후보로 심사.",
                             'source':'섹터 상대강도 기반 후보'})
    tactical_tickers = {c["ticker"] for c in tactical}
    # 역방향 상품은 뉴스/LLM 경로로 들어와도 기초시장 검증을 우회하지 못한다.
    validated = [c for c in validated if c['ticker'] not in tactical_tickers
                 and profile(c['ticker'])['instrument_type'] != '인버스 ETF'
                 and c['ticker'] not in UNSUPPORTED_GEARED]
    slots = MAX_CANDIDATES - len(tactical)
    half = slots // 2
    kr = [c for c in validated if c["market"] == "KR"]
    us = [c for c in validated if c["market"] != "KR"]
    n_kr = min(len(kr), max(half, slots - len(us)))
    selected = _localize_candidates(kr[:n_kr] + us[:slots - n_kr])
    candidates = [{**c, **profile(c['ticker'])} for c in tactical + selected]
    print(f"[스크리닝부] 후보 {len(candidates)}개: {[c['name'] for c in candidates]}")
    return {"headlines": headlines, "candidates": candidates, "tactical_snapshot": snapshot}



# ── 02 기술적 분석부 ───────────────────────────────────────────────────────────
def technical(state: DeskState) -> dict:
    out, checks = {}, {}
    for c in state['candidates']:
        ticker = c['ticker']
        try:
            if 'market_context' in state:
                frame, evidence = fetch_daily(ticker, c.get('market','US'))
                ind = calculate_technical_indicators(ticker, history=frame)
                checks[ticker] = evidence
            else:
                ind = calculate_technical_indicators(ticker)
            if ind:
                out[ticker] = {k:(_num(v) if k!='signals' else v) for k,v in ind.items()}
                if ticker in checks:
                    out[ticker].update({k:checks[ticker][k] for k in ('atr14','relative_volume','as_of','basis')})
        except Exception as exc:
            checks[ticker] = {'fresh':False,'reason':str(exc)[:180]}
    print(f"[기술적 분석부] 지표 산출 {len(out)}개")
    return {'technicals':out,'data_checks':checks}


# ── 03 펀더멘털부 ──────────────────────────────────────────────────────────────
def fundamental(state: DeskState) -> dict:
    out, earnings = {}, {}
    for c in state["candidates"]:
        spec = profile(c["ticker"])
        if 'market_context' in state:
            earnings[c['ticker']] = ({'status':'대상 아님','blocked':False}
                if spec['instrument_type'].endswith('ETF') else earnings_check(c['ticker'],c.get('market','US')))
        if spec["instrument_type"].endswith("ETF"):
            out[c["ticker"]] = spec["product_note"] + " 기업 매출·영업이익 심사 대상이 아닌 ETF. 기초시장 추세·상대강도·변동성으로 심사."
            continue
        prof = fetch_company_financial_profile(c["ticker"], c.get("market", "KR"))
        out[c["ticker"]] = prof["summary"] if prof else "재무 데이터 없음"
    print(f"[펀더멘털부] 재무 확인 {len(out)}개")
    return {"fundamentals": out, "earnings_checks": earnings}


# ── 04 마켓부 ──────────────────────────────────────────────────────────────────
def market(state: DeskState) -> dict:
    if 'market_context' in state:
        context = state['market_context']
        valid = [m['regime'] for m in context['markets'].values() if m.get('allow_new')]
        regime_name = min(valid, key=lambda r:REGIME_TOTAL_CAP[r]) if valid else '횡보장'
        labels = ' · '.join(f"{m}: {v['regime']}" for m,v in context['markets'].items())
        return {'regime':{'regime':regime_name, 'strategy':context['strategy'],
                         'rationale':f"{labels}. {context['reason']}. 완료 일봉 기준이며 뉴스가 수치 판정을 변경하지 않습니다.",
                         'markets':context['markets'], 'snapshot_text':json.dumps(context['prices'],ensure_ascii=False)}}
    snap = get_market_snapshot()
    snapshot_text = "\n".join(
        f"- {k}: {v['last']:,.2f} (1일 {v['chg_1d']:+.2f}%, 5일 {v['chg_5d']:+.2f}%, 20일선 {'위' if v['above_ma20'] else '아래'})"
        for k, v in snap.items()
    )
    prompt = f"""모든 설명과 전략명은 한국어로 쓴다. 너는 증권사 마켓부장이다. 아래 지표와 헤드라인으로 현재 장세를 판정하고 전략을 고른다.

[지표]
{snapshot_text}

[헤드라인]
{json.dumps(state["headlines"][:20], ensure_ascii=False)}

regime은 반드시 "상승장", "하락장", "횡보장" 중 하나.
strategy는 장세에 맞는 전략 조합 이름. 롱 매수만 고집하지 말고 상승 추종 / 반도체 인버스 / 지수 인버스 / 방어주 상대강도 / 현금 대기를 비교한다.
약세를 무조건 저가 매수 기회로 설명하지 않는다. 기초시장 약세가 확인될 때만 인버스를 검토하고, 근거가 약하면 현금 대기를 선택한다.
[전술 후보 지표 — SOXX는 반도체 방향 확인용 대용 지표]
{json.dumps(state.get('tactical_snapshot', {}), ensure_ascii=False)}
JSON 형식: {{"regime": "...", "strategy": "...", "rationale": "수치 근거 포함 2문장"}}"""
    try:
        regime = ask_claude_json(prompt)
    except CodexUnavailable:
        raise
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
        {**c, **profile(c["ticker"]), "technical": state["technicals"][c["ticker"]], "fundamental": state["fundamentals"].get(c["ticker"])}
        for c in state["candidates"]
        if c["ticker"] in state["technicals"]
    ]


# ── 05 리스크관리부 ────────────────────────────────────────────────────────────
def research_debate(state: DeskState) -> dict:
    """04-1 리서치 토론부: 강세·약세 연구원 토론 → 리서치 매니저 판정."""
    return {"debates": run_debate(_candidate_dossier(state), state["regime"])}


def _timemachine(d, entry, target, stop):
    """타임머신: 종목 자신의 최근 일봉으로 목표/손절 도달 확률 재생. 데이터 실패 시 None (차단하지 않음)."""
    try:
        frame, _ = fetch_daily(d["ticker"], d.get("market", "US"))
        inverse = profile(d["ticker"])["instrument_type"] == "인버스 ETF"
        return replay(frame, entry, target, stop, INVERSE_HORIZON_DAYS if inverse else SWING_HORIZON_DAYS)
    except Exception as e:
        print(f"[타임머신] {d['ticker']} 재생 실패: {type(e).__name__}")
        return None


def risk(state: DeskState) -> dict:
    journal = _load_journal()
    _refresh_journal(journal)
    previous = _latest_plans(journal)
    dossier = _candidate_dossier(state)
    regime = state["regime"]
    total_cap = REGIME_TOTAL_CAP[regime["regime"]]
    if not dossier:
        return {"risk_reviews": [{"ticker":c['ticker'],"verdict":"보류","weight_pct":0,"stop_loss":None,
                                 "reason":state.get('data_checks',{}).get(c['ticker'],{}).get('reason','기술적 지표 확인 실패')}
                                for c in state['candidates']], "journal": journal}
    holds = {}
    if 'market_context' in state:
        for c in state['candidates']:
            ticker = c['ticker']
            holds[ticker] = entry_holds(state['market_context'],state.get('data_checks',{}).get(ticker,{}),
                                      state.get('earnings_checks',{}).get(ticker,{'status':'미확인'}),c.get('market','US'))
        if all(holds.get(c['ticker']) for c in state['candidates']):
            return {'risk_reviews':[{'ticker':c['ticker'],'verdict':'보류','weight_pct':0,'stop_loss':None,
                                     'reason':' / '.join(holds[c['ticker']])} for c in state['candidates']], 'journal':journal}


    prompt = f"""너는 리스크관리부장이다. 공격적 아이디어에 반대하고 자본을 지키는 것이 임무다.
장세: {regime['regime']} / 전략: {regime['strategy']}
총 투자 비중 상한: {total_cap}%, 기존 진행 계획 포함. 종목당 최대 {MAX_WEIGHT_PCT}%.
SOXS 최대 5%, SH 최대 10%, 인버스 합계 최대 {INVERSE_TOTAL_CAP}%. 둘 다 1개 미국 정규 세션 이내 종료.
인버스는 ETF를 매수해 기초시장 하락에 대응하는 전략이며 ETF 자체를 공매도하는 것이 아니다.
주식 상승 대응·방어주 상대강도·인버스 하락 대응·현금 대기를 비교하라. 인버스 ETF에 기업 실적 부재를 재무 부실로 적용하지 않는다.
추가 인버스는 보유 주식과의 관계, 헤지/독립 방향성 목적, 일중 무효화 조건을 reason에 명시한다. 근거 없으면 전원 보류 가능.

[경제 일정 확인 범위]
{json.dumps(state.get('market_context',{}).get('event_warnings',[]), ensure_ascii=False)}
일정 조회 실패 자체는 매매 중단 신호가 아니다. 그 사유만으로 전원 보류하지 말고 확인된 가격·추세·상대강도와 위험 기준으로 계속 심사한다.
실제로 확인된 발표 임박과 가격/장세 데이터 실패에 대한 코드 차단은 유지한다.

[후보 종목 자료]
{json.dumps(dossier, ensure_ascii=False)}

[종목별 최신 계획과 평가]
{json.dumps(previous, ensure_ascii=False)}

[리서치 토론부 판정 — 강세·약세 연구원 토론 결과. "매도 우위"는 코드에서 자동 보류된다]
{json.dumps(state.get('debates', {}), ensure_ascii=False)}
설명과 근거는 반드시 한국어로 작성한다.

각 종목에 대해:
- verdict: "통과" 또는 "보류" (RSI 과열, 밴드 상단 과이탈, 재무 취약, 뉴스 근거 빈약, 장세 불일치면 보류)
- weight_pct: 통과 시 비중(%), 보류면 0
- stop_loss: 통과 시 손절가 (볼린저 하단·기준선·피보나치 50% 참고, 현재가보다 낮아야 함), 보류면 null
- reason: 한 줄 근거
- position_purpose: 인버스는 "헤지" 또는 "방향성", 주식은 "상승 대응"
- invalidation: 인버스는 기초시장 기준 전략 무효화 조건을 반드시 한국어로 명시
JSON 형식: {{"reviews": [{{"ticker": "...", "verdict": "...", "weight_pct": 0, "stop_loss": null, "reason": "...", "position_purpose": "...", "invalidation": "..."}}]}}"""
    try:
        reviews = [r for r in ask_claude_json(prompt).get("reviews", []) if isinstance(r, dict)]
    except CodexUnavailable:
        raise
    except Exception as e:
        print(f"[리스크관리부] 심사 실패 → 전원 보류: {e}")
        reviews = [{"ticker": d["ticker"], "verdict": "보류", "weight_pct": 0, "stop_loss": None, "reason": "심사 실패"} for d in dossier]

    returned = {r.get('ticker') for r in reviews}
    for c in state['candidates']:
        if c['ticker'] not in returned:
            reviews.append({'ticker':c['ticker'],'verdict':'보류','weight_pct':0,'stop_loss':None,
                            'reason':' / '.join(holds.get(c['ticker'],[])) or '지표 부족 또는 심사 결과 누락'})

    for r in reviews:
        d = state.get("debates", {}).get(r.get("ticker"))
        if d and d["verdict"] == "매도 우위" and r.get("verdict") == "통과":
            r.update(verdict="보류", weight_pct=0, stop_loss=None,
                     reason=f"리서치 토론 매도 우위: {d.get('bear', '')}")

    # 하드 룰: LLM 출력과 무관하게 코드로 강제
    prices = {d["ticker"]: d["technical"]["price"] for d in dossier}
    # 기존 진입 대기·보유 비중도 예약 자금으로 포함한다.
    active = [p['order'] for p in previous.values() if p['order'].get('review_status') not in CLOSED_STATUSES]
    def weight(order):
        try:
            value = float(order.get('weight_pct') or 0)
            return max(value,0) if math.isfinite(value) else 0
        except (ValueError,TypeError):
            return 0
    total = sum(weight(o) for o in active)
    inverse_total = sum(weight(o) for o in active if profile(o['ticker'])['instrument_type']=='인버스 ETF')
    seen = set()
    inverse_positions = {o['ticker'] for o in active if profile(o['ticker'])['instrument_type']=='인버스 ETF'}
    reviews.sort(key=lambda r: profile(r.get('ticker'))['instrument_type']!='인버스 ETF')
    for r in reviews:
        ticker = r.get('ticker')
        spec = profile(ticker)
        if holds.get(ticker):
            r.update(verdict='보류',weight_pct=0,stop_loss=None,reason=' / '.join(holds[ticker]))
            continue
        if ticker not in prices or ticker in seen:
            r.update(verdict='보류',weight_pct=0,stop_loss=None,reason='미등록 또는 중복 심사 종목')
            continue
        seen.add(ticker)
        if spec['instrument_type']=='인버스 ETF':
            if r.get('position_purpose') not in ('헤지','방향성') or not _has_korean(r.get('invalidation')):
                r.update(verdict='보류',weight_pct=0,stop_loss=None,reason='인버스 목적 또는 무효화 조건 누락')
                continue
            relevant = [o for o in active if profile(o['ticker'])['daily_leverage']>0
                        and (ticker=='SH' and o.get('market','US')=='US' or ticker=='SOXS' and o['ticker'] in SEMICONDUCTOR_TICKERS)]
            if relevant and r['position_purpose']!='헤지' or not relevant and r['position_purpose']=='헤지':
                r.update(verdict='보류',weight_pct=0,stop_loss=None,reason='기존 포지션과 헤지 목적 불일치')
                continue
            ind = state['technicals'].get(ticker,{})
            if not bearish(state.get('tactical_snapshot',{}),spec['benchmark_proxy']) or not isinstance(ind.get('rsi'),(int,float)) or not math.isfinite(ind['rsi']) or ind['rsi'] >= 65:
                r.update(verdict='보류',weight_pct=0,stop_loss=None,reason='기초시장 약세 미확인 또는 인버스 과열/지표 부족')
                continue

        if spec['instrument_type']!='인버스 ETF' and (ticker in SEMICONDUCTOR_TICKERS and 'SOXS' in inverse_positions or 'SH' in inverse_positions and ticker not in ('PG','KO','XLP','XLV','XLU') and not str(ticker).endswith(('.KS','.KQ'))):
            r.update(verdict='보류',weight_pct=0,stop_loss=None,reason='진행 중인 인버스와 상충하는 신규 롱 확대 보류')
            continue
        price = prices.get(r.get("ticker"))
        prior = previous.get(r.get("ticker"))
        if prior:
            old = prior["order"]
            status = old.get("review_status")
            reason = None
            if status in ("진행중", "진입 대기", "보유"):
                reason = "기존 계획 진행 중: 중복 신규 추천 제외"
            elif status is None:
                reason = "기존 계획 평가 미확인: 신규 추천 보류"
            elif status == "손절" and (price is None or price <= old["stop_loss"]):
                reason = "최근 손절가 회복 전: 재진입 보류"
            if reason:
                r.update(verdict="보류", weight_pct=0, stop_loss=None, reason=reason)
                continue
            r["plan_type"] = "재진입 계획"
            r["previous_result"] = status

        stop = r.get("stop_loss")
        bad_stop = (not isinstance(stop, (int, float)) or isinstance(stop,bool) or not math.isfinite(stop)
                    or stop <= 0 or not isinstance(price,(int,float)) or not math.isfinite(price) or stop >= price)
        if r.get("verdict") != "통과" or bad_stop:
            if r.get("verdict") == "통과":
                r["reason"] = f"손절가 무효로 보류 ({r.get('reason', '')})"
            r.update(verdict="보류", weight_pct=0, stop_loss=None)
            continue
        w = min(weight(r), spec['max_weight_pct'], total_cap - total)
        if spec['instrument_type']=='인버스 ETF':
            w = min(w, INVERSE_TOTAL_CAP-inverse_total)
            # ETF 손절 시 손실 예산은 전체 계획 자산의 0.5% 이내.
            w = min(w, 0.5 / ((price-stop)/price))
            if r['position_purpose']=='헤지':
                w = min(w, sum(weight(o) for o in relevant)/abs(spec['daily_leverage']))
            inverse_total += max(w,0)
            if w > 0:
                inverse_positions.add(ticker)
        r["weight_pct"] = max(w, 0)
        if r["weight_pct"] == 0:
            r.update(verdict="보류", stop_loss=None, reason="총 비중 상한 초과")
        total += r["weight_pct"]
    print(f"[리스크관리부] 통과 {sum(r['verdict'] == '통과' for r in reviews)}/{len(reviews)}, 총 비중 {total}%")
    return {"risk_reviews": reviews, "journal": journal}


# ── 학습: 지난 계획 복기 ───────────────────────────────────────────────────────
def _load_journal() -> list:
    try:
        with open(JOURNAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _latest_plans(journal, exclude_today=False):
    latest = {}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    for entry in sorted(journal, key=lambda e: e["date"]):
        if exclude_today and entry["date"].startswith(today):
            continue
        for order in entry.get("orders", []):
            latest[order["ticker"]] = {"date": entry["date"], "regime": entry["regime"],
                                       "strategy": entry["strategy"], "order": order}
    return latest


def _refresh_journal(journal):
    """계획 생성 이후 5분봉으로 지정가 가상 체결·청산을 평가한다."""
    records = list(_latest_plans(journal, exclude_today=True).values()) + list(_latest_plans(journal).values())
    seen = set()
    for record in records:
        p = record["order"]
        if id(p) in seen:
            continue
        seen.add(id(p))
        if p.get("simulation_version") == 2 and p.get("review_status") in CLOSED_STATUSES:
            continue
        # 종가만으로 계산했던 이전 평가는 체결 근거가 없어 다시 계산한다.
        if p.get("simulation_version") != 2:
            for key in ("review_status", "review_price", "review_date", "review_reported",
                        "filled_at", "fill_price"):
                p.pop(key, None)
            p["simulation_version"] = 2
        try:
            created = KST.localize(datetime.strptime(record["date"], "%Y-%m-%d %H:%M"))
            if (datetime.now(KST) - created).days >= 59:
                raise ValueError("계획 생성 시점의 5분봉 조회 범위 초과")
            history = yf.Ticker(p["ticker"]).history(
                start=record["date"][:10], interval="5m", auto_adjust=False,
                prepost=p.get("market", "US" if not p["ticker"].endswith((".KS", ".KQ")) else "KR") == "US"
                and profile(p["ticker"])["instrument_type"] != "인버스 ETF")
            if history.empty:
                if not p.get("filled_at"):
                    p.update(review_status="진입 대기", review_price=None)
                raise ValueError("계획 생성 이후 5분봉 없음: 가상 체결 확인 대기")
            if history.index.tz is None:
                raise ValueError("시세 시간대 정보 없음")
            bars = history.sort_index().dropna(subset=["Open", "High", "Low", "Close"])
            bars = bars[(bars.index >= created) & (bars.index <= datetime.now(KST))]
            p.pop("evaluation_error", None)
            intraday = profile(p['ticker'])['instrument_type'] == '인버스 ETF'
            if intraday:
                # 인버스는 미국 정규장만 평가. 일일 목표 상품을 다음 세션으로 자동 이월하지 않는다.
                ny = pytz.timezone('America/New_York')
                sessions = schedule('US',created.astimezone(ny).date(),datetime.now(KST).astimezone(ny).date())
                sessions = sessions[sessions.market_close>=created]
                if sessions.empty:
                    raise ValueError('진입 유효 세션 확인 대기')
                session_map = {row.Index.date():row for row in sessions.itertuples()}
                first_session = sessions.index[0].date()
                bars = bars.loc[[t.tz_convert(ny).date() in session_map
                                 and session_map[t.tz_convert(ny).date()].market_open <= t < session_map[t.tz_convert(ny).date()].market_close
                                 for t in bars.index]]
                if bars.empty:
                    raise ValueError('진입 유효 세션 정규장 5분봉 없음')
            for timestamp, bar in bars.iterrows():
                if intraday:
                    session = timestamp.tz_convert('America/New_York').date()
                    session_close = session_map[session].market_close
                    if p.get('filled_at'):
                        filled_date = KST.localize(datetime.strptime(p['filled_at'], '%Y-%m-%d %H:%M')).astimezone(pytz.timezone('America/New_York')).date()
                        if session > filled_date:
                            raise ValueError('일중 청산 시점 시세 없음: 다음 세션 이월 평가 보류')
                    elif session > first_session:
                        raise ValueError('첫 진입 유효 세션 시세 누락: 이후 세션 진입 보류')
                when = timestamp.tz_convert(KST).strftime("%Y-%m-%d %H:%M")
                if p.get("filled_at") and when < p["filled_at"]:
                    continue
                just_filled = False
                if not p.get("filled_at"):
                    if bar["Low"] > p["entry"]:
                        if intraday and timestamp + timedelta(minutes=5) == session_close and datetime.now(KST) >= session_close:
                            p.update(review_status='미체결 취소',review_price=None,review_date=when)
                            break
                        continue
                    p.update(filled_at=when, fill_price=min(float(bar["Open"]), p["entry"]))
                    just_filled = True
                # 갭 하락은 시가에 손절. 같은 봉 내 순서는 불명확하므로 손절 우선.
                if bar["Low"] <= p["stop_loss"]:
                    exit_price = min(float(bar["Open"]), p["stop_loss"])
                    p.update(review_status="손절", review_price=exit_price, review_date=when)
                    break
                # 장중 진입한 봉의 고가는 진입 전일 수 있어 목표 체결 근거로 쓰지 않는다.
                entered_at_open = bar["Open"] <= p["entry"]
                if bar["High"] >= p["target"] and (not just_filled and when != p["filled_at"] or entered_at_open):
                    p.update(review_status="목표 도달", review_price=max(float(bar["Open"]), p["target"]), review_date=when)
                    break
                p.update(review_status="보유", review_price=float(bar["Close"]), review_date=when)
                if intraday and timestamp + timedelta(minutes=5) == session_close and datetime.now(KST) >= session_close:
                    p.update(review_status='시간 청산',review_price=float(bar['Close']),review_date=when)
                    break
            if not p.get("filled_at") and p.get('review_status') not in CLOSED_STATUSES:
                if (datetime.now(KST) - created).days >= ENTRY_EXPIRY_DAYS:
                    p.update(review_status="미체결 취소", review_price=None,
                             review_date=datetime.now(KST).strftime("%Y-%m-%d %H:%M"))
                else:
                    p.update(review_status="진입 대기", review_price=None)
        except Exception as exc:
            p["evaluation_error"] = str(exc)
            print(f"[{p['ticker']}] 가상 체결 평가 실패: {type(exc).__name__}")


def _review_past_plans(journal: list) -> str:
    """진행중 계획은 전부, 종료(익절·손절)된 계획은 한 번만 알리고 이후 숨김. 같은 종목은 최근 계획 한 건만."""
    lines = []
    records_by_order = {
        id(record["order"]): record
        for record in list(_latest_plans(journal, exclude_today=True).values())
        + list(_latest_plans(journal).values())
    }
    records = sorted(records_by_order.values(), key=lambda e: e["date"])
    for entry in records:
        p = entry["order"]
        status, price = p.get("review_status"), p.get("review_price")
        closed = status in CLOSED_STATUSES
        if closed and p.get("review_reported"):
            continue
        if closed:
            p["review_reported"] = True  # operations()가 저널 저장 시 함께 기록
        label = "익절" if status == "목표 도달" else (status or "확인 전")
        ret = f"{(price / p.get('fill_price', p['entry']) - 1) * 100:+.2f}%" if price is not None else ("미체결" if status in ("진입 대기", "미체결 취소") else "가격 확인 실패")
        when = f" {p['review_date']}" if closed else ""
        lines.append(f"- {entry['date']} 계획 {_display_name(p)}({p['ticker']}): "
                     f"[{label}{when}] {ret} · {entry['regime']}/{entry['strategy']}")
    return "\n".join(lines) or "복기할 과거 계획 없음"


# ── 06 운용부 ──────────────────────────────────────────────────────────────────
def operations(state: DeskState) -> dict:
    journal = state.get("journal")
    if journal is None:
        journal = _load_journal()
        _refresh_journal(journal)
    review_text = _review_past_plans(journal)
    passed = [r for r in state["risk_reviews"] if r["verdict"] == "통과"]
    dossier = {d["ticker"]: d for d in _candidate_dossier(state)}
    regime = state["regime"]

    plan = {"summary": "리스크 기준을 통과한 종목이 없어 오늘은 관망합니다.", "orders": []}
    active_orders = [
        {**record["order"], "created_at": record["date"]}
        for record in _latest_plans(journal).values()
        if record["order"].get("review_status") not in CLOSED_STATUSES
    ]
    if active_orders:
        plan["summary"] = "이번 실행의 신규 계획은 없습니다. 기존 계획은 아래에서 계속 확인합니다."
    if passed:
        prompt = f"""너는 운용부장이다. 각 부서 분석을 하나의 매매 계획으로 정리한다.
장세: {regime['regime']} / 전략: {regime['strategy']} — {regime['rationale']}

[리스크관리부 통과 종목 (비중·손절가 확정, 변경 금지)]
{json.dumps([{**r, **dossier[r['ticker']]} for r in passed if r['ticker'] in dossier], ensure_ascii=False)}

[지난 계획 복기 — 실패 패턴은 피하고 성공 패턴은 반영]
{review_text}

모든 요약·논리·재진입 사유는 반드시 한국어로 작성한다.
재진입 계획은 이전 종료 결과와 달라진 근거를 reentry_reason에 반드시 명시한다.
각 종목에 대해 entry(ETF/주식 자체의 매수 진입가), target(동일 상품의 목표가), thesis(한 줄 포지션 논리)를 정한다.
반도체·지수 인버스는 해당 ETF의 가격 상승으로 수익을 내는 하락 대응 계획이다. 손절 < 진입 < 목표 규칙을 동일하게 적용한다.
인버스는 추격 진입 금지, 손익비 2:1 이상 필수, 1개 미국 정규 세션 안에 시간 청산한다. 신호 부재 시 현금 대기를 유지한다.
JSON 형식: {{"summary": "오늘 계획 2문장 (복기에서 얻은 교훈 포함)", "orders": [{{"ticker": "...", "entry": 0, "target": 0, "thesis": "...", "reentry_reason": "재진입일 때 달라진 근거, 신규면 빈 문자열"}}]}}"""
        try:
            raw = ask_claude_json(prompt)
            risk_by_ticker = {r["ticker"]: r for r in passed}
            orders, rejected = [], []
            for o in raw.get("orders", []):
                if any(existing['ticker'] == o.get('ticker') for existing in orders):
                    continue
                r, d = risk_by_ticker.get(o.get("ticker")), dossier.get(o.get("ticker"))
                if not (r and d and isinstance(o.get("entry"), (int, float)) and isinstance(o.get("target"), (int, float))):
                    continue
                if not (r["stop_loss"] < o["entry"] < o["target"]):
                    continue  # 손절 < 진입 < 목표 아니면 버림
                tm = _timemachine(d, o["entry"], o["target"], r["stop_loss"])
                if tm and tm["ev_r"] <= 0:
                    rejected.append({"ticker": d["ticker"], "name": d["name"], "timemachine": tm})
                    print(f"[타임머신] {d['ticker']} 기각: {describe(tm)}")
                    continue
                spec = profile(d['ticker'])
                if spec['instrument_type']=='인버스 ETF':
                    if not all(math.isfinite(v) for v in (o['entry'],o['target'])) or (o['target']-o['entry'])/(o['entry']-r['stop_loss']) < 2:
                        continue
                    current = d['technical']['price']
                    if o['entry'] > current or r['weight_pct'] * (o['entry']-r['stop_loss']) / o['entry'] > 0.5:
                        continue
                reentry_reason = o.get("reentry_reason", "")
                if r.get("plan_type") == "재진입 계획" and not _has_korean(reentry_reason):
                    continue
                orders.append({
                    "name": d["name"], "ticker": d["ticker"], "market": d.get("market", "KR"),
                    "entry": o["entry"], "target": o["target"], "stop_loss": r["stop_loss"],
                    "weight_pct": r["weight_pct"], "thesis": o.get("thesis", ""),
                    "position_purpose": r.get('position_purpose','상승 대응'),
                    "invalidation": r.get('invalidation',''),
                    "plan_type": r.get("plan_type", "신규 계획"), "reentry_reason": reentry_reason,
                    "timemachine": tm,
                    "simulation_version": 2, "review_status": "진입 대기",
                    **{k:v for k,v in spec.items() if k != "name"},
                })
            plan = {"summary": raw.get("summary", "") if orders else "계획 기준을 통과한 종목이 없어 오늘은 관망합니다.", "orders": orders,
                    "timemachine_rejected": rejected}
        except CodexUnavailable:
            raise
        except Exception as e:
            print(f"[운용부] 계획 수립 실패: {e}")

    plan["active_orders"] = active_orders
    journal.append({
        "date": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "regime": regime["regime"], "strategy": regime["strategy"],
        "rationale": regime.get("rationale", ""), "summary": plan['summary'],
        "market_context": state.get('market_context',{}),
        "data_checks":state.get('data_checks',{}), "earnings_checks":state.get('earnings_checks',{}),
        "decisions": [{"ticker": r['ticker'], "verdict": r['verdict'], "reason": r.get('reason',''),
                       "exposure": profile(r['ticker'])['exposure']} for r in state['risk_reviews']],
        "orders": plan["orders"],
    })
    # 주문이 있는 이력은 종료·재진입 후에도 보존하고 빈 실행만 정리한다.
    retained = [entry for entry in journal[:-60]
                if entry.get("orders")]
    with open(JOURNAL_PATH, "w", encoding="utf-8") as f:
        json.dump(retained + journal[-60:], f, ensure_ascii=False, indent=1)
    from performance_dashboard import write_dashboard
    write_dashboard(retained + journal[-60:])
    print(f"[운용부] 주문안 {len(plan['orders'])}건")
    from pathlib import Path
    replay_path=Path(JOURNAL_PATH).with_suffix('.latest_state.json')
    replay_tmp=replay_path.with_suffix('.tmp')
    replay_tmp.write_text(json.dumps({**state,'plan':plan,'review_text':review_text},ensure_ascii=False,indent=2),encoding='utf-8')
    replay_tmp.replace(replay_path)
    return {"plan": plan, "review_text": review_text}


def publish_dashboard(state: DeskState) -> dict:
    """Daily cron: publish the saved dashboard before sending its Teams link."""
    if not os.environ.get("TEAMS_WEBHOOK_URL") or os.environ.get("DESK_PUBLISH_DASHBOARD", "1") == "0":
        return {}
    try:
        publish_performance()
    except Exception as exc:
        # Deployment is an independent output: an error must not suppress the daily card.
        reason=str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        print(f"[대시보드] 배포 실패: {reason} · Teams 전송 계속",flush=True)
        return {'dashboard_status':'failed','dashboard_error':reason}
    print("[대시보드] GitHub Pages 반영 완료",flush=True)
    return {'dashboard_status':'published','dashboard_error':''}


# ── Teams 전송 ─────────────────────────────────────────────────────────────────
def build_teams_payload(state: DeskState):
    if not state.get("headlines") and not state.get("market_context"):
        print("뉴스·시장 근거 없음: Teams 전송 생략")
        return {}
    explanations = [state["regime"]["strategy"], state["regime"]["rationale"], state["plan"]["summary"]]
    explanations += [c.get("reason") for c in state["candidates"]]
    explanations += [r.get("reason") for r in state["risk_reviews"]]
    explanations += [o.get("thesis") for o in state["plan"]["orders"]]
    if any(not _has_korean(text) for text in explanations):
        raise RuntimeError("한국어 설명 검증 실패: Teams 전송 중단")
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
        *([head("04-1 리서치 토론부 · 강세 vs 약세")] if state.get("debates") else []),
        *[line(f"{ {'매수 우위': '🐂', '매도 우위': '🐻'}.get(d['verdict'], '⚖️') } {label(t)}: {d['verdict']} ({d.get('confidence', 0)}) "
               f"· 강세: {d.get('bull', '')} · 약세: {d.get('bear', '')}") for t, d in state.get("debates", {}).items()],
        head("05 리스크관리부 · 비중·손절 심사"),
        *[line(f"{'✅' if r['verdict'] == '통과' else '🛑'} {label(r['ticker'])}: "
               + (f"비중 {r['weight_pct']:g}% · " if r["verdict"] == "통과" else "")
               + r.get("reason", "")) for r in state["risk_reviews"]],
        head(f"06 운용부 · 신규 계획 {len(plan['orders'])}건 · 기존 진행 계획 {len(plan.get('active_orders', []))}건"),
        line(plan["summary"]),
        *[line(f"⏳ 타임머신 기각 · {_display_name(x)} ({x['ticker']}): {describe(x['timemachine'])}")
          for x in plan.get("timemachine_rejected", [])],
        line("전략 비교: 주식 상승 대응 · 반도체/지수 인버스 · 방어주 상대강도 · 현금 대기"),
    ]
    for o in plan["orders"] + plan.get("active_orders", []):
        m = o["market"]
        existing = "created_at" in o
        body += [
            {"type": "TextBlock", "text": f"🎯 {_display_name(o)} ({o['ticker']}) · {'기존 진행 계획' if existing else o.get('plan_type', '신규 계획')} · 비중 {o.get('weight_pct', 0):g}%", "weight": "Bolder", "color": "Good", "spacing": "Small"},
            {"type": "FactSet", "facts": [
                *([{"title": "계획 생성", "value": o["created_at"]},
                   {"title": "평가 상태", "value": o.get("review_status") or "확인 전"},
                   {"title": "진입 평가", "value": (f"{o['filled_at']} · {format_money(o['fill_price'], m)}" if o.get("filled_at") else ("시세 확인 필요" if o.get("evaluation_error") else "진입가 도달 대기"))},
                   *([{"title": "평가 수익률", "value": f"{(o['review_price'] / o['fill_price'] - 1) * 100:+.2f}%"}]
                     if o.get("fill_price") and o.get("review_price") is not None else []),
                   *([{"title": "평가", "value": "가격 확인 중"}] if o.get("evaluation_error") else [])] if existing else []),
                {"title": "포지션", "value": o.get('exposure',profile(o['ticker'])['exposure'])},
                *([{"title": "전략 무효화", "value": o['invalidation']}] if o.get('invalidation') else []),
                *([{"title": "보유 기준", "value": "미국 정규장 1세션 이내 · 종료 시점 청산 평가"}]
                  if profile(o['ticker'])['instrument_type']=='인버스 ETF' else []),
                {"title": "진입", "value": format_money(o["entry"], m)},
                {"title": "목표", "value": format_money(o["target"], m)},
                {"title": "손절", "value": format_money(o["stop_loss"], m)},
                {"title": "논리", "value": o.get("thesis", "")},
                *([{"title": "타임머신", "value": describe(o["timemachine"])}] if o.get("timemachine") else []),
                *([{"title": "재진입 사유", "value": o["reentry_reason"]}] if o.get("reentry_reason") else []),
            ]},
        ]
    body += [
        head("📚 지난 계획 복기"),
        line(state["review_text"].replace("\n", "\n\n")),
        {"type": "TextBlock", "text": "계획 평가: 생성 이후 5분봉 기준(미국은 프리·애프터마켓 포함) 지정가 매수·목표 매도, 손절 갭은 시가 반영. 같은 봉에서 순서가 불명확하면 손절 우선, 진입 전 고가는 목표 체결에서 제외. 수수료·슬리피지 미반영.", "wrap": True, "size": "Small", "isSubtle": True, "separator": True},
    ]
    payload = {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive",
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.2", "body": body,
                    "actions": [{"type": "Action.OpenUrl", "title": "트레이딩 데스크 보러가기",
                                 "url": dashboard_url()}]},
    }]}
    # Product copy only; the original evidence remains in the local journal.
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) if k!='url' else v for k,v in value.items()}
        if isinstance(value,list):return [clean(v) for v in value]
        if isinstance(value,str):
            return value.replace('가상 체결','진입 평가').replace('가상매매','계획 평가').replace('모의 투자','투자 계획').replace('가상','평가').replace('모의','계획')
        return value
    if state.get('dashboard_status')=='failed':
        payload['attachments'][0]['content']['body'].append({
            'type':'TextBlock','text':'대시보드 갱신이 지연되고 있어요. 이 카드의 계획은 이번 실행 결과예요.',
            'wrap':True,'size':'Small','isSubtle':True,'separator':True})
    return clean(payload)


def notify(state: DeskState) -> dict:
    payload = build_teams_payload(state)
    if not payload:
        return {}
    url = os.environ.get('TEAMS_WEBHOOK_URL')
    if not url:
        for block in payload['attachments'][0]['content']['body']:
            if block['type']=='TextBlock':print(block['text'])
            elif block['type']=='FactSet':print('\n'.join(f"   {fact['title']}: {fact['value']}" for fact in block['facts']))
        return {}
    try:
        r = requests.post(url, json=payload, timeout=30)
        r.raise_for_status()
        print(f"Teams 전송 완료 (HTTP {r.status_code})")
    except Exception as e:
        raise RuntimeError("Teams 전송 실패: 응답 상태를 확인하세요") from None
    return {}


def build_desk_graph():
    g = StateGraph(DeskState)
    for name, fn in [("prepare_context", prepare_context), ("screening", screening), ("technical", technical), ("fundamental", fundamental),
                     ("market", market), ("research_debate", research_debate), ("risk", risk), ("operations", operations), ("publish_dashboard", publish_dashboard), ("notify", notify)]:
        g.add_node(name, fn)
    g.add_edge(START, "prepare_context")
    g.add_edge("prepare_context", "screening")
    for dept in ("technical", "fundamental", "market"):
        g.add_edge("screening", dept)
    g.add_edge(["technical", "fundamental", "market"], "research_debate")  # fan-in: 세 부서 모두 완료 후
    g.add_edge("research_debate", "risk")
    g.add_edge("risk", "operations")
    g.add_edge("operations", "publish_dashboard")
    g.add_edge("publish_dashboard", "notify")
    g.add_edge("notify", END)
    return g.compile()


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    t0 = time.time()
    print(f"[실행 시작] {datetime.now(KST).isoformat()}",flush=True)
    build_desk_graph().invoke({})
    print(f"[실행 완료] {datetime.now(KST).isoformat()} · 총 {time.time() - t0:.1f}s",flush=True)
