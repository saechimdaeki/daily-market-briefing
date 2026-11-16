import copy
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd
import trading_desk as desk
from desk_strategy import tactical_candidates
from performance_dashboard import build_performance, KST

BEAR = {'chg_1d':-1.2,'chg_5d':-4.0,'above_ma20':False}
BULL = {'chg_1d':1.0,'chg_5d':3.0,'above_ma20':True}


class TacticalTests(unittest.TestCase):
    def test_regime_gates_and_defensive_relative_strength(self):
        self.assertEqual(tactical_candidates({}), [])
        self.assertEqual(tactical_candidates({'SPY':BULL,'SOXX':BULL}), [])
        selected=tactical_candidates({'SPY':BEAR,'SOXX':BEAR,'PG':BULL,'KO':{**BULL,'chg_5d':1}})
        self.assertEqual([c['ticker'] for c in selected], ['SOXS','SH','PG'])
        self.assertEqual(selected[0]['daily_leverage'], -3)
        self.assertEqual(selected[0]['max_holding_sessions'], 1)

    def test_screening_reserves_tactical_slots_and_prevents_news_bypass(self):
        news=[{'ticker':f'K{i}.KS','market':'KR','name':'한국주식','reason':'뉴스 근거'} for i in range(6)]
        news += [{'ticker':f'U{i}','market':'US','name':'미국주식','reason':'뉴스 근거'} for i in range(6)]
        news += [{'ticker':'SOXS','market':'US','name':'소스','reason':'뉴스'}]
        with patch.object(desk,'get_finance_news_headlines',return_value=['뉴스']), patch.object(desk,'extract_tickers_from_news',return_value=[]), patch.object(desk,'align_stocks_to_news_context',return_value=[]), patch.object(desk,'validate_target_stocks',return_value=news), patch.object(desk,'fetch_company_name_by_code',return_value='한국주식'), patch.object(desk,'collect_tactical_snapshot',return_value={'SPY':BEAR,'SOXX':BEAR,'PG':BULL}):
            state=desk.screening({})
            self.assertEqual(len(state['candidates']),8)
            self.assertEqual([c['ticker'] for c in state['candidates'][:3]],['SOXS','SH','PG'])
        with patch.object(desk,'get_finance_news_headlines',return_value=['뉴스']), patch.object(desk,'extract_tickers_from_news',return_value=[]), patch.object(desk,'align_stocks_to_news_context',return_value=[]), patch.object(desk,'validate_target_stocks',return_value=[news[-1]]), patch.object(desk,'collect_tactical_snapshot',return_value={}):
            self.assertEqual(desk.screening({})['candidates'],[])

    def test_etf_uses_product_not_company_fundamentals(self):
        with patch.object(desk,'fetch_company_financial_profile') as fetch:
            result=desk.fundamental({'candidates':[{'ticker':'SOXS'}]})
            fetch.assert_not_called()
            self.assertIn('일일',result['fundamentals']['SOXS'])

    def state(self):
        return {'candidates':[{'ticker':t,'name':t,'market':'US'} for t in ('SOXS','SH')],
                'technicals':{t:{'price':100,'rsi':55} for t in ('SOXS','SH')},
                'fundamentals':{}, 'regime':{'regime':'하락장','strategy':'하락 대응'},
                'tactical_snapshot':{'SPY':BEAR,'SOXX':BEAR}}

    def reviews(self):
        return {'reviews':[{'ticker':t,'verdict':'통과','weight_pct':20,'stop_loss':95,'reason':'하락 추세 대응',
                            'position_purpose':'방향성','invalidation':'기초지수 20일선 회복 시 무효'} for t in ('SOXS','SH')]}

    def assess(self,state,journal=None):
        with patch.object(desk,'_load_journal',return_value=journal or []), patch.object(desk,'_refresh_journal'), patch.object(desk,'ask_claude_json',return_value=self.reviews()):
            return desk.risk(state)['risk_reviews']

    def test_inverse_weight_caps_existing_budget_and_missing_data(self):
        results=self.assess(self.state())
        self.assertEqual([r['weight_pct'] for r in results],[5,5])
        held=[{'date':'2026-11-02 09:30','regime':'하락장','strategy':'방어','orders':[{'ticker':'MSFT','review_status':'보유','weight_pct':28}]}]
        self.assertEqual(sum(r['weight_pct'] for r in self.assess(self.state(),held)),2)
        state=self.state();state['tactical_snapshot']={}
        self.assertTrue(all(r['verdict']=='보류' for r in self.assess(state)))
        state=self.state();state['technicals']['SOXS']['rsi']=70
        self.assertEqual(self.assess(state)[0]['verdict'],'보류')

    def test_session_exit_and_no_carry_for_missing_close(self):
        class Now(datetime):
            @classmethod
            def now(cls,tz=None):
                return desk.KST.localize(datetime(2026,11,4,10,0))
        def journal():
            return [{'date':'2026-11-03 09:30','regime':'하락장','strategy':'인버스','orders':[
                {'ticker':'SOXS','market':'US','entry':100,'stop_loss':90,'target':120,'simulation_version':2}]}]
        index=pd.to_datetime(['2026-11-03 09:30','2026-11-03 15:55']).tz_localize('America/New_York')
        history=pd.DataFrame({'Open':[100,103],'Low':[99,102],'High':[102,104],'Close':[101,103]},index=index)
        with patch.object(desk,'datetime',Now),patch.object(desk.yf,'Ticker') as ticker:
            ticker.return_value.history.return_value=history
            j=journal();desk._refresh_journal(j)
            self.assertFalse(ticker.return_value.history.call_args.kwargs['prepost'])
            self.assertEqual(j[0]['orders'][0]['review_status'],'시간 청산')
            self.assertEqual(j[0]['orders'][0]['review_price'],103)
            data=build_performance(j,datetime(2026,11,4,tzinfo=KST))
            self.assertEqual(data['summaries']['7']['closed'],1)
            self.assertEqual(data['summaries']['7']['average_return_pct'],3)

    def test_pending_inverse_cancelled_at_session_end(self):
        class Now(datetime):
            @classmethod
            def now(cls,tz=None):
                return desk.KST.localize(datetime(2026,11,4,10,0))
        index=pd.to_datetime(['2026-11-03 09:30','2026-11-03 15:55']).tz_localize('America/New_York')
        history=pd.DataFrame({'Open':[110,110],'Low':[109,109],'High':[111,111],'Close':[110,110]},index=index)
        j=[{'date':'2026-11-03 09:30','regime':'하락장','strategy':'인버스','orders':[
            {'ticker':'SOXS','market':'US','entry':100,'stop_loss':90,'target':120,'simulation_version':2}]}]
        with patch.object(desk,'datetime',Now),patch.object(desk.yf,'Ticker') as ticker:
            ticker.return_value.history.return_value=history
            desk._refresh_journal(j)
        self.assertEqual(j[0]['orders'][0]['review_status'],'미체결 취소')
        self.assertNotIn('filled_at',j[0]['orders'][0])

    def test_missing_invalidation_and_conflicting_direction_rejected(self):
        response=self.reviews();response['reviews'][0].pop('invalidation')
        with patch.object(desk,'_load_journal',return_value=[]),patch.object(desk,'_refresh_journal'),patch.object(desk,'ask_claude_json',return_value=response):
            result=desk.risk(self.state())['risk_reviews']
            self.assertEqual(result[0]['verdict'],'보류')
        held=[{'date':'2026-11-02 09:30','regime':'하락장','strategy':'기존 롱','orders':[
            {'ticker':'NVDA','market':'US','review_status':'보유','weight_pct':10}]}]
        self.assertTrue(all(r['verdict']=='보류' for r in self.assess(self.state(),held)))
        response=self.reviews()
        for r in response['reviews']:r['position_purpose']='헤지'
        with patch.object(desk,'_load_journal',return_value=held),patch.object(desk,'_refresh_journal'),patch.object(desk,'ask_claude_json',return_value=response):
            result=desk.risk(self.state())['risk_reviews']
            self.assertLessEqual(result[0]['weight_pct']*3,10)

    def test_missing_session_close_does_not_use_next_day_price(self):
        class Now(datetime):
            @classmethod
            def now(cls,tz=None):
                return desk.KST.localize(datetime(2026,11,5,10,0))
        history=pd.DataFrame({'Open':[100,110],'Low':[99,109],'High':[101,111],'Close':[100,110]},
            index=pd.to_datetime(['2026-11-03 09:30','2026-11-04 09:30']).tz_localize('America/New_York'))
        j=[{'date':'2026-11-03 09:30','regime':'하락장','strategy':'인버스','orders':[
            {'ticker':'SOXS','market':'US','entry':100,'stop_loss':90,'target':120,'simulation_version':2}]}]
        with patch.object(desk,'datetime',Now),patch.object(desk.yf,'Ticker') as ticker:
            ticker.return_value.history.return_value=history
            desk._refresh_journal(j)
        order=j[0]['orders'][0]
        self.assertIn('이월 평가 보류',order['evaluation_error'])
        self.assertEqual(order['review_price'],100)
        self.assertNotIn(order['review_status'],desk.CLOSED_STATUSES)

    def test_inverse_plan_metadata_and_duplicate_plan_guard(self):
        state=self.state();state['journal']=[]
        state['regime']['rationale']='기초시장 하락 추세'
        state['risk_reviews']=[{**self.reviews()['reviews'][0],'weight_pct':5}]
        order={'ticker':'SOXS','entry':100,'target':110,'thesis':'반도체 약세에 대응하는 일중 계획'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desk,'JOURNAL_PATH',os.path.join(tmp,'journal.json')),patch.dict(os.environ,{'OUTPUT_DIR':tmp}),patch.object(desk,'ask_claude_json',return_value={'summary':'단기 하락 대응','orders':[order,order]}),patch.object(desk,'_timemachine',return_value=None):
            result=desk.operations(state)
        self.assertEqual(len(result['plan']['orders']),1)
        saved=result['plan']['orders'][0]
        self.assertEqual(saved['daily_leverage'],-3)
        self.assertEqual(saved['max_holding_sessions'],1)
        self.assertEqual(saved['position_purpose'],'방향성')
        self.assertIn('20일선',saved['invalidation'])

    def test_timemachine_rejects_negative_expected_value(self):
        state=self.state();state['journal']=[]
        state['regime']['rationale']='기초시장 하락 추세'
        state['risk_reviews']=[{**self.reviews()['reviews'][0],'weight_pct':5}]
        order={'ticker':'SOXS','entry':100,'target':110,'thesis':'반도체 약세에 대응하는 일중 계획'}
        bad={'p_target':0.1,'p_stop':0.6,'p_open':0.3,'ev_r':-0.4,'hist_target':0.1,'hist_stop':0.5,'hist_n':200,'horizon_days':1}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desk,'JOURNAL_PATH',os.path.join(tmp,'journal.json')),patch.dict(os.environ,{'OUTPUT_DIR':tmp}),patch.object(desk,'ask_claude_json',return_value={'summary':'단기 하락 대응','orders':[order]}),patch.object(desk,'_timemachine',return_value=bad):
            result=desk.operations(state)
        self.assertEqual(result['plan']['orders'],[])
        self.assertEqual(result['plan']['timemachine_rejected'][0]['ticker'],'SOXS')


if __name__=='__main__':
    unittest.main()
