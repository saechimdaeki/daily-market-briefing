"""종목별 복기, 종료 결과 고정, 중복 추천, 한국어 표시 검증."""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime

import pandas as pd
import trading_desk as desk


class FixedDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 12, 10, 0, tzinfo=tz)


def plan(date, entry=100, stop=95, target=120, **extra):
    return {'date': date, 'regime': '상승장', 'strategy': '추세추종', 'orders': [
        {'ticker': '005930.KS', 'name': 'Samsung Electronics', 'market': 'KR',
         'entry': entry, 'stop_loss': stop, 'target': target, **extra}
    ]}


class PlanReviewTests(unittest.TestCase):
    def test_us_premarket_fill_and_empty_history(self):
        journal = [plan('2026-10-12 09:32')]
        order = journal[0]['orders'][0]
        order.update(ticker='NVDA', market='US')
        hist = pd.DataFrame({'Open': [100], 'Low': [99], 'High': [102], 'Close': [101]},
                            index=pd.to_datetime(['2026-10-12 09:35']).tz_localize('Asia/Seoul'))
        with patch.object(desk, 'datetime', FixedDate), patch.object(desk.yf, 'Ticker') as ticker:
            ticker.return_value.history.return_value = pd.DataFrame()
            desk._refresh_journal(journal)
            self.assertEqual(order['review_status'], '진입 대기')
            self.assertIn('5분봉 없음', order['evaluation_error'])
            ticker.return_value.history.return_value = hist
            desk._refresh_journal(journal)
            self.assertTrue(ticker.return_value.history.call_args.kwargs['prepost'])
            self.assertEqual(order['review_status'], '보유')
            self.assertNotIn('evaluation_error', order)

    def test_stop_shown_once_then_hidden_but_history_survives_reentry(self):
        stopped = plan('2026-10-12 09:32', review_status='손절', review_price=95,
                       review_date='2026-10-12 09:50', simulation_version=2)
        state = {'journal': [stopped], 'risk_reviews': [], 'candidates': [],
                 'technicals': {}, 'fundamentals': {},
                 'regime': {'regime': '하락장', 'strategy': '관망'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desk, 'JOURNAL_PATH', os.path.join(tmp, 'journal.json')), \
             patch.object(desk, 'datetime', FixedDate):
            first = desk.operations(state)
            self.assertIn('[손절 2026-10-12 09:50]', first['review_text'])
            self.assertEqual(first['plan']['active_orders'], [])
            with open(desk.JOURNAL_PATH) as saved:
                state['journal'] = json.load(saved)
            second = desk.operations(state)
            self.assertNotIn('[손절', second['review_text'])
            # 재진입으로 최신 계획이 바뀌고 빈 실행이 60회 이상 쌓여도 손절 원장은 유지.
            state['journal'].append(plan('2026-10-12 09:55', review_status='진입 대기'))
            state['journal'] += [{'date': '2026-10-12 09:59', 'regime': '하락장',
                                  'strategy': '관망', 'orders': []} for _ in range(61)]
            desk.operations(state)
            with open(desk.JOURNAL_PATH) as saved:
                history = json.load(saved)
            old = history[0]['orders'][0]
            self.assertEqual(old['review_status'], '손절')
            self.assertEqual(old['review_price'], 95)
            self.assertTrue(old['review_reported'])

    def test_same_day_plan_survives_empty_run_and_is_rendered(self):
        journal = [plan('2026-10-12 09:32', review_status='진행중', weight_pct=15)]
        state = {'journal': journal, 'risk_reviews': [], 'candidates': [],
                 'technicals': {}, 'fundamentals': {}, 'headlines': ['뉴스'],
                 'regime': {'regime': '하락장', 'strategy': '관망', 'rationale': '시장 약세'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desk, 'JOURNAL_PATH', os.path.join(tmp, 'journal.json')), \
             patch.object(desk, 'datetime', FixedDate), patch.object(desk, 'ask_claude_json') as ai:
            state.update(desk.operations(state))
            self.assertEqual(state['plan']['orders'], [])
            self.assertEqual(state['plan']['active_orders'][0]['entry'], 100)
            self.assertEqual(journal[-1]['orders'], [])
            ai.assert_not_called()
            with patch.dict(os.environ, {'TEAMS_WEBHOOK_URL': 'https://example.invalid'}), \
                 patch.object(desk.requests, 'post') as post:
                desk.notify(state)
            body = post.call_args.kwargs['json']['attachments'][0]['content']['body']
            rendered = json.dumps(body, ensure_ascii=False)
            self.assertIn('신규 계획 0건 · 기존 진행 계획 1건', rendered)
            self.assertIn('삼성전자', rendered)
            self.assertIn('2026-10-12 09:32', rendered)
            self.assertIn('진입가 도달 대기', rendered)

    def test_latest_plan_retained_after_sixty_empty_runs(self):
        journal = [plan('2026-10-08 09:32', review_status='진행중')]
        journal += [{'date': '2026-10-12 09:00', 'regime': '하락장', 'strategy': '관망', 'orders': []} for _ in range(60)]
        state = {'journal': journal, 'risk_reviews': [], 'candidates': [], 'technicals': {},
                 'fundamentals': {}, 'regime': {'regime': '하락장', 'strategy': '관망'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desk, 'JOURNAL_PATH', os.path.join(tmp, 'journal.json')), \
             patch.object(desk, 'datetime', FixedDate):
            desk.operations(state)
            with open(desk.JOURNAL_PATH) as saved:
                latest = desk._latest_plans(json.load(saved))
            self.assertEqual(latest['005930.KS']['order']['entry'], 100)

    def test_latest_ticker_only_and_empty_runs_do_not_hide_results(self):
        journal = [plan('2026-10-06 08:18'), plan('2026-10-08 08:59', review_status='손절', review_price=94, review_date='2026-10-09')]
        journal += [{'date': f'2026-10-09 {hour}:00', 'regime': '하락장', 'strategy': '관망', 'orders': []} for hour in range(10, 18)]
        with patch.object(desk, 'datetime', FixedDate):
            text = desk._review_past_plans(journal)
        self.assertEqual(text.count('005930.KS'), 1)
        self.assertIn('삼성전자', text)
        self.assertNotIn('Samsung', text)
        self.assertNotIn('2026-10-06', text)
        self.assertIn('[손절 2026-10-09]', text)

    def test_first_stop_is_frozen_after_rebound(self):
        journal = [plan('2026-10-08 08:59')]
        hist = pd.DataFrame({'Open': [100, 94, 110], 'Low': [99, 93, 109], 'High': [101, 95, 111], 'Close': [100, 94, 110]}, index=pd.to_datetime(['2026-10-08 10:00', '2026-10-09 10:00', '2026-10-12 09:00']).tz_localize('Asia/Seoul'))
        with patch.object(desk, 'datetime', FixedDate), patch.object(desk.yf, 'Ticker') as ticker:
            ticker.return_value.history.return_value = hist
            desk._refresh_journal(journal)
            self.assertEqual(journal[0]['orders'][0]['review_status'], '손절')
            self.assertEqual(journal[0]['orders'][0]['review_price'], 94)
            ticker.reset_mock()
            desk._refresh_journal(journal)
            ticker.assert_not_called()

    def test_today_new_plan_does_not_hide_previous_stop(self):
        journal = [plan('2026-10-08 08:59'), plan('2026-10-12 09:32', stop=90)]
        hist = pd.DataFrame({'Open': [100, 94], 'Low': [99, 93], 'High': [101, 95], 'Close': [100, 94]}, index=pd.to_datetime(['2026-10-08 10:00', '2026-10-12 09:00']).tz_localize('Asia/Seoul'))
        with patch.object(desk, 'datetime', FixedDate), patch.object(desk.yf, 'Ticker') as ticker:
            ticker.return_value.history.return_value = hist
            desk._refresh_journal(journal)
            self.assertIn('[손절 2026-10-12 09:00]', desk._review_past_plans(journal))
            self.assertEqual(journal[1]['orders'][0]['review_status'], '진입 대기')

    def test_price_failure_does_not_silently_drop_plan(self):
        with patch.object(desk, 'datetime', FixedDate):
            self.assertIn('[확인 전] 가격 확인 실패', desk._review_past_plans([plan('2026-10-08 08:59')]))

    def test_active_duplicate_and_unrecovered_stop_blocked(self):
        state = {'candidates': [{'ticker': '005930.KS', 'name': '삼성전자'}],
                 'technicals': {'005930.KS': {'price': 94}}, 'fundamentals': {},
                 'regime': {'regime': '하락장', 'strategy': '관망'}}
        response = {'reviews': [{'ticker': '005930.KS', 'verdict': '통과', 'weight_pct': 10, 'stop_loss': 90, 'reason': '테스트'}]}
        for status in ['진행중', '손절']:
            with self.subTest(status=status), patch.object(desk, '_load_journal', return_value=[plan('2026-10-08 08:59', review_status=status)]), \
                 patch.object(desk, '_refresh_journal'), patch.object(desk, 'ask_claude_json', return_value=copy.deepcopy(response)):
                result = desk.risk(state)['risk_reviews'][0]
                self.assertEqual(result['verdict'], '보류')
                self.assertEqual(result['weight_pct'], 0)

    def test_virtual_entry_only_after_creation_and_exit_after_fill(self):
        journal = [plan('2026-10-12 09:32')]
        hist = pd.DataFrame({
            'Open': [100, 110, 102, 105], 'Low': [90, 108, 99, 104],
            'High': [130, 130, 121, 122], 'Close': [110, 115, 105, 120],
        }, index=pd.to_datetime(['2026-10-12 09:30', '2026-10-12 09:35',
                                '2026-10-12 09:40', '2026-10-12 09:45']).tz_localize('Asia/Seoul'))
        with patch.object(desk, 'datetime', FixedDate), patch.object(desk.yf, 'Ticker') as ticker:
            ticker.return_value.history.return_value = hist.iloc[:2]
            desk._refresh_journal(journal)
            order = journal[0]['orders'][0]
            self.assertEqual(order['review_status'], '진입 대기')
            self.assertNotIn('filled_at', order)
            ticker.return_value.history.return_value = hist.iloc[:3]
            desk._refresh_journal(journal)
            self.assertEqual(order['review_status'], '보유')
            self.assertEqual(order['fill_price'], 100)
            ticker.return_value.history.return_value = hist
            desk._refresh_journal(journal)
            self.assertEqual(order['review_status'], '목표 도달')
            self.assertEqual(order['review_price'], 120)

    def test_candidate_translation_preserves_ticker(self):
        stocks = [{'ticker': 'MU', 'name': 'Micron Technology', 'reason': 'AI demand', 'market': 'US'}]
        with patch.object(desk, 'ask_claude_json', return_value={'stocks': [{'ticker': 'MU', 'name': '마이크론', 'reason': '인공지능 메모리 수요 확대'}]}):
            result = desk._localize_candidates(stocks)
        self.assertEqual(result[0]['ticker'], 'MU')
        self.assertEqual(result[0]['reason'], '인공지능 메모리 수요 확대')

    def test_english_explanations_never_posted(self):
        state = {'headlines': ['뉴스'], 'regime': {'strategy': '관망', 'rationale': '시장 약세'},
                 'plan': {'summary': '오늘 관망', 'orders': []}, 'candidates': [{'reason': 'Record profits reported'}], 'risk_reviews': []}
        with patch.object(desk.requests, 'post') as post:
            with self.assertRaisesRegex(RuntimeError, '한국어 설명'):
                desk.notify(state)
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
