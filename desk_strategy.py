"""Deterministic instrument metadata and tactical screening, independent of LLM labels."""
import math
from datetime import datetime, timezone

import yfinance as yf

PROFILES = {
    'SOXS': {'name':'디렉시온 반도체 인버스 3배', 'instrument_type':'인버스 ETF',
             'exposure':'반도체 하락 대응', 'daily_leverage':-3, 'benchmark_proxy':'SOXX',
             'max_weight_pct':5, 'max_holding_sessions':1,
             'product_note':'NYSE Semiconductor Index 일일 수익률 -3배 목표. SOXX는 방향 확인용 대용 지표이며 동일 지수가 아님. 일일 재설정·복리 효과로 누적 수익률은 -3배와 다를 수 있음.'},
    'SH': {'name':'프로셰어즈 S&P500 인버스', 'instrument_type':'인버스 ETF',
           'exposure':'미국 지수 하락 대응', 'daily_leverage':-1, 'benchmark_proxy':'SPY',
           'max_weight_pct':10, 'max_holding_sessions':1,
           'product_note':'S&P500 일일 수익률 -1배 목표. 장기 누적 수익률의 역수를 보장하지 않음.'},
    'PG': {'name':'프록터앤드갬블', 'instrument_type':'주식', 'exposure':'필수소비재 방어주',
           'daily_leverage':1, 'max_weight_pct':15},
    'KO': {'name':'코카콜라', 'instrument_type':'주식', 'exposure':'필수소비재 방어주',
           'daily_leverage':1, 'max_weight_pct':15},
}
for _ticker, _sector in {'SOXX':'반도체','XLK':'기술','XLF':'금융','XLP':'필수소비재 방어','XLV':'헬스케어 방어','XLU':'유틸리티 방어','XLE':'에너지'}.items():
    PROFILES[_ticker] = {'name':_sector+' ETF','instrument_type':'ETF','exposure':_sector+' 상승 대응',
                        'daily_leverage':1,'max_weight_pct':15,
                        'product_note':_sector+' 섹터 ETF. 기업 단독 실적이 아닌 섹터 추세·상대강도·거래량으로 심사.'}

INVERSE_TOTAL_CAP = 10
SEMICONDUCTOR_TICKERS = {'NVDA','AMD','AVGO','MU','TSM','ASML','INTC','SOXX','SMH','005930.KS','000660.KS'}
UNSUPPORTED_GEARED = {'SOXL','SQQQ','TQQQ','PSQ','SDS','QID','SSG','SPXS','SPXL','SPXU'}


def profile(ticker):
    return dict(PROFILES.get(ticker, {'instrument_type':'주식', 'exposure':'주식 상승 대응',
                                     'daily_leverage':1, 'max_weight_pct':20}))


def collect_tactical_snapshot():
    out = {}
    for ticker in ('SOXX', 'SPY', 'PG', 'KO'):
        try:
            closes = yf.Ticker(ticker).history(period='3mo')['Close'].dropna()
            if len(closes) < 20 or closes.index.tz is None:
                continue
            age = (datetime.now(timezone.utc) - closes.index[-1].to_pydatetime()).total_seconds()/86400
            values = [float(closes.iloc[-1]), float(closes.iloc[-2]), float(closes.iloc[-6]), float(closes.tail(20).mean())]
            if age < 0 or age > 4 or not all(math.isfinite(x) and x > 0 for x in values):
                continue
            last, prev, week, ma20 = values
            out[ticker] = {'chg_1d':(last/prev-1)*100, 'chg_5d':(last/week-1)*100,
                           'above_ma20':last>ma20, 'as_of':str(closes.index[-1])}
        except Exception as exc:
            print(f'[{ticker}] 전술 지표 수집 실패: {type(exc).__name__}')
    return out


def bearish(snapshot, ticker):
    item = snapshot.get(ticker, {})
    one, five = item.get('chg_1d'), item.get('chg_5d')
    return (isinstance(one, (int,float)) and isinstance(five, (int,float))
            and math.isfinite(one) and math.isfinite(five)
            and one < 0 and five < 0 and item.get('above_ma20') is False)


def tactical_candidates(snapshot):
    out = []
    for ticker in ('SOXS', 'SH'):
        p = profile(ticker)
        if bearish(snapshot, p['benchmark_proxy']):
            b = snapshot[p['benchmark_proxy']]
            out.append({'ticker':ticker, 'market':'US', **p,
                        'reason':f"{p['benchmark_proxy']} 전일 {b['chg_1d']:+.2f}%, 5일 {b['chg_5d']:+.2f}%, 20일선 하회. 하락 대응 후보로 심사하며 매수 확정 아님.",
                        'source':'시장 지표 기반 전술 후보'})
    base = snapshot.get('SPY', {})
    if bearish(snapshot, 'SPY'):
        defensive = [(t,snapshot[t]) for t in ('PG','KO') if t in snapshot
                     and snapshot[t].get('above_ma20') is True
                     and snapshot[t].get('chg_5d', -100) > max(base['chg_5d'], 0)]
        for ticker, b in sorted(defensive, key=lambda item:item[1]['chg_5d'], reverse=True)[:1]:
            out.append({'ticker':ticker,'market':'US',**profile(ticker),
                        'reason':f"시장 약세 속 5일 {b['chg_5d']:+.2f}%, 20일선 상회. 필수소비재 상대강도 방어 후보, 하락 면역 아님.",
                        'source':'상대강도 기반 방어 후보'})
    return out
