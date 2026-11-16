"""
외부 프레임워크에서 가져온 두 단계 (코드 의존 없이 방법만 이식)

1) 리서치 토론부 — TauricResearch/TradingAgents 의 Bull/Bear Researcher + Research Manager
   분석 자료를 두고 강세 연구원과 약세 연구원이 맞서고, 리서치 매니저가 판정한다.

2) 타임머신 — Jakeschincariol/day-trader-skill 의 /trader-timemachine
   주문(진입·목표·손절)을 종목 자신의 최근 일봉으로 수천 번 재생해
   목표 먼저 / 손절 먼저 / 미결 확률과 기대값(R)을 낸다. 기대값이 0 이하면 버린다.
"""

import json
import random

from agents.claude_cli import ask_claude_json

DEBATE_VERDICTS = ("매수 우위", "중립", "매도 우위")
SIM_PATHS = 2000
SIM_SEED = 19            # 같은 입력이면 같은 결과 (재현 가능)
SWING_HORIZON_DAYS = 10  # 일반 주식: 10거래일 안에 목표/손절 판정
INVERSE_HORIZON_DAYS = 1 # 인버스 ETF: 1세션 이내 청산 규칙과 맞춤
LOOKBACK_DAYS = 250


# ── 리서치 토론부 (TradingAgents) ──────────────────────────────────────────────
def run_debate(dossier: list, regime: dict) -> dict:
    """ticker → {bull, bear, verdict, confidence, key_risk}. 실패하면 빈 dict (리스크관리부가 그대로 심사)."""
    if not dossier:
        return {}
    prompt = f"""너는 증권사 리서치팀이다. 세 역할을 순서대로 수행한다.
1. 강세 연구원: 종목마다 지금 매수해야 하는 가장 강한 근거를 자료의 수치로 1~2문장.
2. 약세 연구원: 강세 근거를 정면으로 반박하고 가장 큰 하락 위험을 자료의 수치로 1~2문장.
3. 리서치 매니저: 두 주장 중 더 설득력 있는 쪽을 고른다. 근거가 비슷하면 "중립".
   verdict는 반드시 "매수 우위", "중립", "매도 우위" 중 하나. confidence는 0~100.
   인버스 ETF는 ETF 자체를 매수하는 하락 대응이므로, 기초시장 하락 근거가 강세 근거가 된다.

장세: {regime.get('regime')} / 전략: {regime.get('strategy')}

[분석 자료]
{json.dumps(dossier, ensure_ascii=False)}

모든 문장은 한국어로 쓴다.
JSON 형식: {{"debates": [{{"ticker": "...", "bull": "...", "bear": "...", "verdict": "...", "confidence": 0, "key_risk": "한 줄"}}]}}"""
    try:
        rows = ask_claude_json(prompt).get("debates", [])
    except Exception as e:
        print(f"[리서치 토론부] 토론 실패 → 생략: {e}")
        return {}
    out = {}
    for r in rows:
        if isinstance(r, dict) and r.get("ticker") and r.get("verdict") in DEBATE_VERDICTS:
            out[r["ticker"]] = r
    print(f"[리서치 토론부] {', '.join(f'{t}:{d['verdict']}' for t, d in out.items()) or '판정 없음'}")
    return out


# ── 타임머신 (day-trader-skill) ────────────────────────────────────────────────
def _day_moves(frame) -> list:
    """일봉을 전일 종가 대비 (시가, 고가, 저가, 종가) 비율로 바꾼다."""
    bars = frame[["Open", "High", "Low", "Close"]].dropna().tail(LOOKBACK_DAYS + 1)
    rows = bars.values.tolist()
    return [(o / pc, h / pc, l / pc, c / pc)
            for (_, _, _, pc), (o, h, l, c) in zip(rows, rows[1:]) if pc > 0]


def _walk(moves, entry, target, stop) -> str:
    """하루씩 진행. 갭은 시가 체결, 같은 날 둘 다 닿으면 손절 우선 (trading_desk 평가 규칙과 동일)."""
    price = entry
    for o, h, l, c in moves:
        if price * o <= stop or price * l <= stop:
            return "stop"
        if price * o >= target or price * h >= target:
            return "target"
        price *= c
    return "open"


def replay(frame, entry: float, target: float, stop: float, horizon: int) -> dict | None:
    """몬테카를로 SIM_PATHS회 + 과거 매일을 진입일로 본 실제 경로 재생."""
    moves = _day_moves(frame)
    if len(moves) < horizon + 20 or not (stop < entry < target):
        return None
    rng = random.Random(SIM_SEED)
    sim = {"target": 0, "stop": 0, "open": 0}
    for _ in range(SIM_PATHS):
        sim[_walk([rng.choice(moves) for _ in range(horizon)], entry, target, stop)] += 1
    hist = {"target": 0, "stop": 0, "open": 0}
    for i in range(len(moves) - horizon):
        hist[_walk(moves[i:i + horizon], entry, target, stop)] += 1
    p_t, p_s = sim["target"] / SIM_PATHS, sim["stop"] / SIM_PATHS
    reward_r = (target - entry) / (entry - stop)
    n_hist = sum(hist.values())
    return {
        "p_target": round(p_t, 3), "p_stop": round(p_s, 3), "p_open": round(1 - p_t - p_s, 3),
        "ev_r": round(p_t * reward_r - p_s, 2),  # 미결은 0R로 계산 (보수적)
        "hist_target": round(hist["target"] / n_hist, 3), "hist_stop": round(hist["stop"] / n_hist, 3),
        "hist_n": n_hist, "horizon_days": horizon,
    }


def describe(tm: dict) -> str:
    return (f"{tm['horizon_days']}일 내 목표 먼저 {tm['p_target']:.0%} · 손절 먼저 {tm['p_stop']:.0%} · "
            f"미결 {tm['p_open']:.0%} · 기대값 {tm['ev_r']:+.2f}R "
            f"(과거 {tm['hist_n']}일 재현: 목표 {tm['hist_target']:.0%} / 손절 {tm['hist_stop']:.0%})")


if __name__ == "__main__":
    import pandas as pd
    up = pd.DataFrame({"Open": [100 * 1.01 ** i for i in range(60)], "High": [100 * 1.01 ** i * 1.02 for i in range(60)],
                       "Low": [100 * 1.01 ** i * 0.995 for i in range(60)], "Close": [100 * 1.01 ** i for i in range(60)]})
    down = up.iloc[::-1].reset_index(drop=True)
    a = replay(up, 100, 104, 97, 10)
    b = replay(down, 100, 104, 97, 10)
    assert a["p_target"] == 1 and a["ev_r"] > 0, a
    assert b["p_stop"] == 1 and b["ev_r"] < 0, b
    assert replay(up, 100, 99, 97, 10) is None  # 손절<진입<목표 위반
    print("ok", describe(a))
