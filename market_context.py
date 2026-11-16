"""Timestamped daily evidence, exchange sessions and independently sourced event checks."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import calendar
import numpy as np
import re
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import requests
import yfinance as yf
from bs4 import BeautifulSoup
from icalendar import Calendar

UTC = timezone.utc
KST = ZoneInfo('Asia/Seoul')
SECTORS = {'SOXX':'반도체','XLK':'기술','XLF':'금융','XLP':'필수소비재','XLV':'헬스케어','XLU':'유틸리티','XLE':'에너지'}
SYMBOLS = ['SPY','QQQ','RSP','IWM',*SECTORS,'PG','KO','^KS11','^KQ11']
BLS_URL = 'https://www.bls.gov/schedule/news_release/bls.ics'
FED_URL = 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm'


def utc_now(now=None):
    stamp = pd.Timestamp(now if now is not None else datetime.now(UTC))
    if stamp.tzinfo is None:
        raise ValueError('시간대 없는 기준 시각')
    return stamp.tz_convert('UTC')


@lru_cache(maxsize=96)
def _schedule(market, start, end):
    return mcal.get_calendar('NYSE' if market == 'US' else 'XKRX').schedule(start_date=start, end_date=end)


def schedule(market, start, end):
    if market not in ('US','KR'):
        raise ValueError('미지원 시장')
    return _schedule(market,str(start)[:10],str(end)[:10])


def session_context(market, now=None):
    stamp=utc_now(now)
    table=schedule(market,(stamp-timedelta(days=20)).date(),(stamp+timedelta(days=20)).date())
    completed=table[table.market_close<=stamp]
    future=table[table.market_close>stamp]
    active=table[(table.market_open<=stamp)&(table.market_close>stamp)]
    if completed.empty or future.empty:
        raise ValueError('거래소 일정 범위 부족')
    following=future.iloc[0]
    return {'market':market,'state':'정규장 진행 중' if not active.empty else '정규장 외',
            'last_completed_session':str(completed.index[-1].date()),
            'next_open':following.market_open.isoformat(), 'next_close':following.market_close.isoformat(),
            'checked_at':stamp.isoformat()}


def completed_history(history, market, now=None):
    stamp=utc_now(now)
    if history.empty or history.index.tz is None:
        raise ValueError('가격 없음 또는 시간대 누락')
    zone='America/New_York' if market=='US' else 'Asia/Seoul'
    labels=history.index.tz_convert(zone).date
    if history.index.has_duplicates:
        raise ValueError('중복 가격 시각')
    table=schedule(market,min(labels),max(labels))
    completed={row.Index.date() for row in table.itertuples() if row.market_close<=stamp}
    clean=history.loc[[day in completed for day in labels]].sort_index().dropna(subset=['Open','High','Low','Close','Volume'])
    if len(clean)<60:
        raise ValueError('완료 일봉 60개 미만')
    if not np.isfinite(clean[['Open','High','Low','Close','Volume']].to_numpy()).all():
        raise ValueError('유한하지 않은 가격/거래량')
    if (clean[['Open','High','Low','Close']]<=0).any().any() or (clean.High<clean[['Open','Close','Low']].max(axis=1)).any() or (clean.Low>clean[['Open','Close','High']].min(axis=1)).any() or (clean.Volume<0).any():
        raise ValueError('비정상 가격')
    context=session_context(market,stamp)
    actual=str(clean.index[-1].tz_convert(zone).date())
    if actual!=context['last_completed_session']:
        raise ValueError(f"시세 지연: {actual}, 필요한 완료 거래일 {context['last_completed_session']}")
    return clean


def daily_metrics(frame, market, now=None):
    close=frame.Close
    last=float(close.iloc[-1]); previous=float(close.iloc[-2])
    tr=pd.concat([frame.High-frame.Low,(frame.High-close.shift()).abs(),(frame.Low-close.shift()).abs()],axis=1).max(axis=1)
    baseline=float(frame.Volume.iloc[-21:-1].mean())
    return {'last':last, 'price':last, 'chg_1d':(last/previous-1)*100,
            'chg_5d':(last/float(close.iloc[-6])-1)*100,
            'chg_20d':(last/float(close.iloc[-21])-1)*100,
            'above_ma20':bool(last>close.tail(20).mean()),
            'above_ma60':bool(last>close.tail(60).mean()),
            'above_ma200':bool(last>close.tail(200).mean()) if len(close)>=200 else None,
            'atr14':float(tr.tail(14).mean()),
            'relative_volume':float(frame.Volume.iloc[-1])/baseline if baseline>0 else None,
            'as_of':frame.index[-1].isoformat(), 'market':market, 'fresh':True,
            'basis':'완료 일봉 · Yahoo 조정 가격 · 실시간 호가 아님',
            'checked_at':utc_now(now).isoformat()}


def fetch_daily(ticker, market='US', now=None):
    frame=yf.Ticker(ticker).history(period='1y',auto_adjust=True)
    clean=completed_history(frame,market,now)
    return clean,daily_metrics(clean,market,now)


def classify_market(prices, symbols):
    valid=[prices[s] for s in symbols if s in prices]
    if len(valid)!=len(symbols):
        return {'regime':'확인 불가','reason':'필수 시장 지표 누락','allow_new':False}
    if all(p['above_ma20'] and p['above_ma60'] and p['chg_5d']>0 for p in valid):
        regime='상승장'
    elif all(not p['above_ma20'] and not p['above_ma60'] and p['chg_5d']<0 for p in valid):
        regime='하락장'
    else:
        regime='횡보장'
    return {'regime':regime,'reason':'완료 일봉 20·60일선과 5일 추세의 일치 여부','allow_new':True}


def summarize_market(prices, quality):
    sectors=[]
    for ticker,name in SECTORS.items():
        if ticker in prices and 'SPY' in prices:
            p=prices[ticker]
            sectors.append({'ticker':ticker,'name':name,'chg_5d':round(p['chg_5d'],2),
                            'relative_5d':round(p['chg_5d']-prices['SPY']['chg_5d'],2),
                            'above_ma20':p['above_ma20'],'as_of':p['as_of']})
    sectors.sort(key=lambda p:p['relative_5d'],reverse=True)
    breadth={'label':'미국 ETF 기반 시장 확산 대용 지표 · 전체 종목 상승/하락 비율 아님',
             'coverage':len(sectors),'universe':len(SECTORS),
             'sector_above_ma20_pct':round(sum(s['above_ma20'] for s in sectors)/len(sectors)*100,1) if sectors else None,
             'equal_weight_relative_5d':round(prices['RSP']['chg_5d']-prices['SPY']['chg_5d'],2) if all(t in prices for t in ('RSP','SPY')) else None,
             'small_cap_relative_5d':round(prices['IWM']['chg_5d']-prices['SPY']['chg_5d'],2) if all(t in prices for t in ('IWM','SPY')) else None}
    markets={'US':classify_market(prices,['SPY','QQQ']),'KR':classify_market(prices,['^KS11','^KQ11'])}
    if len(sectors)<5 or breadth['equal_weight_relative_5d'] is None:
        markets['US'].update(allow_new=False,reason='섹터/동일가중 대용 지표 확인 부족')
    us=markets['US']; broad=breadth['sector_above_ma20_pct']
    if not us['allow_new']:
        strategy='현금 대기'; reason=us['reason']
    elif us['regime']=='하락장':
        strategy='인버스 하락 대응·방어주 상대강도·현금 비교';reason='미국 주요 지수 추세 하락'
    elif us['regime']=='상승장' and broad is not None and broad>=50 and breadth['equal_weight_relative_5d']>=-1:
        strategy='상대강도 상위 섹터 상승 추종';reason='미국 지수 상승과 섹터 확산 확인'
    else:
        strategy='선별 대응·현금 비중 유지';reason='추세 혼재 또는 상승 확산 미확인'
    return {'markets':markets,'sectors':sectors,'breadth':breadth,'quality':quality,
            'strategy':strategy,'reason':reason}


def _get(url):
    response=requests.get(url,timeout=15,headers={'User-Agent':'DailyMarketBriefing/1.0'})
    response.raise_for_status()
    return response.text


def parse_bls(text, now=None):
    stamp=utc_now(now); events=[]; dates=[]
    for component in Calendar.from_ical(text).walk('VEVENT'):
        if str(component.get('STATUS',''))=='CANCELLED':continue
        start=component.decoded('DTSTART'); title=str(component.get('SUMMARY',''))
        if not isinstance(start,datetime) or start.tzinfo is None:
            raise ValueError('경제 일정 시간대 누락')
        start=utc_now(start); dates.append(start)
        if any(word in title.lower() for word in ('consumer price index','employment situation','producer price index')):
            events.append({'title':title,'start':start.isoformat(),'end':(start+timedelta(minutes=30)).isoformat(),'source':'BLS','url':BLS_URL})
    if not dates or max(dates)<stamp+timedelta(days=7):raise ValueError('BLS 미래 일정 범위 부족')
    return events


def parse_fomc(text, now=None):
    stamp=utc_now(now);soup=BeautifulSoup(text,'html.parser');events=[]
    for meeting in soup.select('.fomc-meeting'):
        heading=meeting.find_previous('h4')
        year=re.search(r'(20\d{2})',heading.get_text() if heading else '')
        month=meeting.select_one('.fomc-meeting__month');day=meeting.select_one('.fomc-meeting__date')
        if not (year and month and day):continue
        month_name=month.get_text(strip=True).split('/')[-1].strip()
        months={name:i for i,name in enumerate(calendar.month_name) if name}
        if month_name not in months:continue
        numbers=re.findall(r'\d+',day.get_text())
        if not numbers:continue
        # The page specifies a meeting date, not a guaranteed release timestamp: block the full final day.
        start=datetime(int(year[1]),months[month_name],int(numbers[-1]),tzinfo=ZoneInfo('America/New_York'))
        events.append({'title':'FOMC 회의 종료일','start':utc_now(start).isoformat(),
                       'end':utc_now(start+timedelta(days=1)).isoformat(),'source':'Federal Reserve','url':FED_URL,'precision':'date'})
    if not events or max(utc_now(e['start']) for e in events)<stamp+timedelta(days=7):raise ValueError('FOMC 미래 일정 범위 부족')
    return events


def macro_events(now=None):
    stamp=utc_now(now); events=[];sources={}
    for name,url,parser in [('BLS',BLS_URL,parse_bls),('FOMC',FED_URL,parse_fomc)]:
        try:
            events.extend(parser(_get(url),stamp));sources[name]={'status':'확인','checked_at':stamp.isoformat()}
        except Exception as exc:
            sources[name]={'status':'미확인','reason':type(exc).__name__,'checked_at':stamp.isoformat()}
    events=[e for e in events if utc_now(e['end'])>=stamp-timedelta(minutes=30) and utc_now(e['start'])<=stamp+timedelta(days=7)]
    return {'sources':sources,'events':sorted(events,key=lambda e:e['start']),
            'coverage':'미국 BLS 물가·고용 및 FOMC · 국내 정책 일정/기업행사 전체를 포괄하지 않음',
            'checked_at':stamp.isoformat()}


def earnings_check(ticker, market, now=None):
    stamp=utc_now(now)
    try:
        frame=yf.Ticker(ticker).get_earnings_dates(limit=12)
        if frame is None or frame.empty or frame.index.tz is None:raise ValueError('실적 일정 없음')
        future=[utc_now(t) for t in frame.index if utc_now(t)>=stamp-timedelta(hours=24)]
        if not future:raise ValueError('미래 실적 일정 미확인')
        next_date=min(future)
        return {'status':'확인','next_earnings':next_date.isoformat(),'source':'Yahoo earnings estimate',
                'blocked':stamp-timedelta(hours=24)<=next_date<=stamp+timedelta(hours=24),
                'note':'예상 일정 · 회사 IR 확정 시각과 다를 수 있음','checked_at':stamp.isoformat()}
    except Exception as exc:
        return {'status':'미확인','blocked':True,'reason':type(exc).__name__,'checked_at':stamp.isoformat()}


def entry_holds(context, evidence, earnings, market, now=None):
    stamp=utc_now(now); reasons=[]
    if not evidence.get('fresh'):reasons.append('완료 거래일 시세 미확인 또는 지연')
    status=context.get('markets',{}).get(market,{})
    if not status.get('allow_new'):reasons.append('해당 시장 장세/필수 지표 미확인')
    macro=context.get('macro',{})
    for event in macro.get('events',[]):
        if utc_now(event['end'])>=stamp-timedelta(minutes=30) and utc_now(event['start'])<=stamp+timedelta(hours=24):
            reasons.append('주요 발표 접근: '+event['title'])
    if earnings.get('status')=='미확인':reasons.append('기업 실적 일정 미확인')
    elif earnings.get('blocked'):reasons.append('실적 발표 전후 24시간 신규 진입 보류')
    return reasons


def collect_market_context(now=None):
    stamp=utc_now(now);prices={};quality={};sessions={}
    for market in ('US','KR'):
        try:sessions[market]=session_context(market,stamp)
        except Exception as exc:sessions[market]={'state':'확인 불가','reason':str(exc)}
    for ticker in SYMBOLS:
        try:
            _,prices[ticker]=fetch_daily(ticker,'KR' if ticker.startswith('^K') else 'US',stamp)
            quality[ticker]={'status':'확인','as_of':prices[ticker]['as_of']}
        except Exception as exc:quality[ticker]={'status':'미확인','reason':str(exc)[:140]}
    result=summarize_market(prices,quality)
    result.update(prices=prices,sessions=sessions,macro=macro_events(stamp),checked_at=stamp.isoformat(),
                  mode='완료 일봉 기반 계획 · 장중 실시간 신호 아님')
    result['event_warnings'] = [name+' 일정 미확인: 이벤트 확인 범위 제한'
                                for name,status in result['macro']['sources'].items() if status['status']!='확인']
    return result
