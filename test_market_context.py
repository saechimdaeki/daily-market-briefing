import copy
from datetime import datetime,timezone
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import market_context as mc
import trading_desk as desk

NOW=datetime(2026,11,3,15,0,tzinfo=timezone.utc)


def price(up=True):
    return {'above_ma20':up,'above_ma60':up,'chg_1d':1 if up else -1,
            'chg_5d':3 if up else -3,'as_of':'2026-11-02T00:00:00-05:00'}


class MarketContextTests(unittest.TestCase):
    def history(self):
        days=mc.schedule('US','2025-09-01','2026-11-03').index[-240:]
        index=pd.DatetimeIndex(days).tz_localize('America/New_York')
        close=np.arange(len(index),dtype=float)+100
        return pd.DataFrame({'Open':close,'High':close+2,'Low':close-2,'Close':close,'Volume':1000},index=index)

    def context(self):
        return {'markets':{'US':{'allow_new':True}},'macro':{'sources':{'BLS':{'status':'확인'},'FOMC':{'status':'확인'}},'events':[]}}

    def test_dst_holidays_early_close_and_kr_calendar(self):
        winter=mc.schedule('US','2026-11-03','2026-11-03')
        summer=mc.schedule('US','2026-07-06','2026-07-06')
        self.assertEqual(winter.iloc[0].market_open.hour,14)
        self.assertEqual(summer.iloc[0].market_open.hour,13)
        self.assertTrue(mc.schedule('US','2026-11-26','2026-11-26').empty)
        self.assertEqual(mc.schedule('US','2026-11-27','2026-11-27').iloc[0].market_close.hour,18)
        self.assertTrue(mc.schedule('KR','2026-02-17','2026-02-17').empty)

    def test_partial_daily_bar_removed_and_metrics(self):
        clean=mc.completed_history(self.history(),'US',NOW)
        self.assertEqual(str(clean.index[-1].date()),'2026-11-02')
        metrics=mc.daily_metrics(clean,'US',NOW)
        self.assertTrue(metrics['fresh'])
        self.assertTrue(metrics['above_ma200'])
        self.assertEqual(metrics['relative_volume'],1)
        self.assertGreater(metrics['atr14'],0)

    def test_stale_missing_timezone_nan_duplicate_rejected(self):
        frame=self.history()
        with self.assertRaisesRegex(ValueError,'시세 지연'):
            mc.completed_history(frame.iloc[:-2],'US',NOW)
        naive=frame.copy();naive.index=naive.index.tz_localize(None)
        with self.assertRaisesRegex(ValueError,'시간대'):mc.completed_history(naive,'US',NOW)
        bad=frame.copy();bad.iloc[-2,bad.columns.get_loc('Close')]=float('inf')
        with self.assertRaisesRegex(ValueError,'유한'):mc.completed_history(bad,'US',NOW)
        with self.assertRaisesRegex(ValueError,'중복'):mc.completed_history(pd.concat([frame,frame.tail(1)]),'US',NOW)

    def test_source_failure_is_not_no_events(self):
        with patch.object(mc,'_get',side_effect=RuntimeError('unavailable')):
            macro=mc.macro_events(NOW)
        self.assertTrue(all(s['status']=='미확인' for s in macro['sources'].values()))
        context=self.context();context['macro']=macro
        self.assertEqual(mc.entry_holds(context,{'fresh':True},{'status':'확인','blocked':False},'US',NOW),[])

    def test_bls_timezone_parsing_and_coverage(self):
        ics='''BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261103T083000
SUMMARY:Consumer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261201T100000
SUMMARY:Other Release
END:VEVENT
END:VCALENDAR'''
        events=mc.parse_bls(ics,NOW)
        self.assertEqual(len(events),1)
        self.assertEqual(pd.Timestamp(events[0]['start']).hour,13)
        with self.assertRaisesRegex(ValueError,'範囲|범위'):
            mc.parse_bls(ics,datetime(2027,1,1,tzinfo=timezone.utc))

    def test_fomc_final_date_and_unknown_markup(self):
        html='<h4>2026 FOMC Meetings</h4><div class="fomc-meeting"><div class="fomc-meeting__month">December</div><div class="fomc-meeting__date">8-9*</div></div>'
        result=mc.parse_fomc(html,NOW)
        self.assertEqual(result[0]['precision'],'date')
        self.assertEqual(result[0]['start'],'2026-12-09T05:00:00+00:00')
        with self.assertRaises(ValueError):mc.parse_fomc('<html>maintenance</html>',NOW)

    def test_event_and_earnings_gates(self):
        context=self.context()
        context['macro']['events']=[{'title':'CPI','start':'2026-11-04T13:30:00+00:00','end':'2026-11-04T14:00:00+00:00'}]
        holds=mc.entry_holds(context,{'fresh':True},{'status':'미확인'},'US',NOW)
        self.assertTrue(any('CPI' in reason for reason in holds))
        self.assertIn('기업 실적 일정 미확인',holds)
        self.assertIn('완료 거래일 시세 미확인 또는 지연',mc.entry_holds(context,{}, {'status':'대상 아님'},'US',NOW))

    def test_breadth_is_proxy_and_coverage_controls_new_plans(self):
        prices={t:price() for t in mc.SYMBOLS}
        result=mc.summarize_market(prices,{})
        self.assertEqual(result['markets']['US']['regime'],'상승장')
        self.assertEqual(result['breadth']['sector_above_ma20_pct'],100)
        self.assertIn('대용',result['breadth']['label'])
        prices.pop('RSP')
        self.assertFalse(mc.summarize_market(prices,{})['markets']['US']['allow_new'])
        prices={t:price(False) for t in mc.SYMBOLS}
        self.assertIn('인버스',mc.summarize_market(prices,{})['strategy'])

    def test_risk_cannot_override_failed_checks(self):
        state={'candidates':[{'ticker':'MSFT','market':'US'}],'technicals':{'MSFT':{'price':100}},
               'fundamentals':{},'regime':{'regime':'상승장','strategy':'상승 추종'},
               'market_context':self.context(),'data_checks':{'MSFT':{'fresh':False}},
               'earnings_checks':{'MSFT':{'status':'확인','blocked':False}}}
        with patch.object(desk,'_load_journal',return_value=[]),patch.object(desk,'_refresh_journal'),patch.object(desk,'ask_claude_json') as ai:
            reviews=desk.risk(state)['risk_reviews']
        self.assertEqual(reviews[0]['verdict'],'보류')
        self.assertIn('시세',reviews[0]['reason'])
        ai.assert_not_called()

    def test_unknown_earnings_and_etf_no_corporate_earnings(self):
        with patch.object(mc.yf,'Ticker') as ticker:
            ticker.return_value.get_earnings_dates.return_value=None
            self.assertTrue(mc.earnings_check('MSFT','US',NOW)['blocked'])
        graph=desk.build_desk_graph().get_graph()
        self.assertIn(('prepare_context','screening'),{(e.source,e.target) for e in graph.edges})

    def test_market_candidates_continue_without_news(self):
        context=self.context()
        context.update(prices={'SPY':price()},sectors=[{'ticker':'XLK','relative_5d':2,'above_ma20':True}])
        context['markets']['US']['regime']='상승장'
        with patch.object(desk,'get_finance_news_headlines',return_value=[]),patch.object(desk,'extract_tickers_from_news') as extract:
            result=desk.screening({'market_context':context})
        extract.assert_not_called()
        self.assertEqual(result['candidates'][0]['ticker'],'XLK')
        self.assertEqual(result['candidates'][0]['instrument_type'],'ETF')

    def test_early_close_time_exit(self):
        class Now(datetime):
            @classmethod
            def now(cls,tz=None):return desk.KST.localize(datetime(2026,11,28,10,0))
        index=pd.to_datetime(['2026-11-27 09:30','2026-11-27 12:55']).tz_localize('America/New_York')
        history=pd.DataFrame({'Open':[100,101],'High':[102,103],'Low':[99,100],'Close':[101,102]},index=index)
        journal=[{'date':'2026-11-27 09:30','regime':'하락장','strategy':'인버스','orders':[
            {'ticker':'SOXS','market':'US','entry':100,'target':120,'stop_loss':90,'simulation_version':2}]}]
        with patch.object(desk,'datetime',Now),patch.object(desk.yf,'Ticker') as ticker:
            ticker.return_value.history.return_value=history
            desk._refresh_journal(journal)
        self.assertEqual(journal[0]['orders'][0]['review_status'],'시간 청산')
        self.assertEqual(journal[0]['orders'][0]['review_price'],102)
        self.assertTrue(journal[0]['orders'][0]['review_date'].endswith('02:55'))

    def test_schedule_outage_preserves_strategy_and_records_warning(self):
        with patch.object(mc,'fetch_daily',return_value=(None,price())),patch.object(mc,'session_context',return_value={'state':'정규장 외'}),patch.object(mc,'macro_events',return_value={'sources':{'BLS':{'status':'미확인'},'FOMC':{'status':'확인'}},'events':[]}):
            context=mc.collect_market_context(NOW)
        self.assertNotIn('신규 진입 보류',context['strategy'])
        self.assertTrue(any('BLS' in warning for warning in context['event_warnings']))

    def test_bls_outage_does_not_block_otherwise_valid_plan(self):
        context=self.context();context['macro']['sources']['BLS']={'status':'미확인'}
        context['event_warnings']=['BLS 일정 미확인: 이벤트 확인 범위 제한']
        bear={'chg_1d':-1,'chg_5d':-3,'above_ma20':False}
        state={'candidates':[{'ticker':'SOXS','market':'US'}], 'technicals':{'SOXS':{'price':100,'rsi':50}},
               'fundamentals':{},'regime':{'regime':'하락장','strategy':'하락 대응'},
               'market_context':context,'data_checks':{'SOXS':{'fresh':True}},
               'earnings_checks':{'SOXS':{'status':'대상 아님','blocked':False}},'tactical_snapshot':{'SOXX':bear}}
        response={'reviews':[{'ticker':'SOXS','verdict':'통과','weight_pct':5,'stop_loss':95,
                             'position_purpose':'방향성','invalidation':'기초시장 추세 회복 시 무효','reason':'가격 추세 확인'}]}
        with patch.object(desk,'_load_journal',return_value=[]),patch.object(desk,'_refresh_journal'),patch.object(desk,'ask_claude_json',return_value=response) as ai:
            result=desk.risk(state)['risk_reviews'][0]
        ai.assert_called_once()
        self.assertEqual(result['verdict'],'통과')
        self.assertEqual(result['weight_pct'],5)
        context['macro']['events']=[{'title':'CPI','start':'2026-11-04T13:30:00+00:00','end':'2026-11-04T14:00:00+00:00'}]
        self.assertTrue(any('CPI' in reason for reason in mc.entry_holds(context,{'fresh':True},{'status':'대상 아님'},'US',NOW)))


if __name__=='__main__':unittest.main()
