"""종목별 복기, 종료 결과 고정, 중복 추천, 한국어 표시 검증."""
import copy
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
    def test_latest_ticker_only_and_empty_runs_do_not_hide_results(self):
        journal = [plan('2026-10-06 08:18'), plan('2026-10-08 08:59', review_status='손절', review_price=94, review_date='2026-10-09')]
        journal += [{'date': f'2026-10-09 {hour}:00', 'regime': '하락장', 'strategy': '관망', 'orders': []} for hour in range(10, 18)]
        with patch.object(desk, 'datetime', FixedDate):
            text = desk._review_past_plans(journal)
        self.assertEqual(text.count('005930.KS'), 1)
        self.assertIn('삼성전자', text)
        self.assertNotIn('Samsung', text)
        self.assertNotIn('2026-10-06', text)
        self.assertIn('[손절]', text)

    def test_first_stop_is_frozen_after_rebound(self):
        journal = [plan('2026-10-08 08:59')]
        hist = pd.DataFrame({'Close': [100, 94, 110]}, index=pd.to_datetime(['2026-10-08', '2026-10-09', '2026-10-12']))
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
        hist = pd.DataFrame({'Close': [94]}, index=pd.to_datetime(['2026-10-12']))
        with patch.object(desk, 'datetime', FixedDate), patch.object(desk.yf, 'Ticker') as ticker:
            ticker.return_value.history.return_value = hist
            desk._refresh_journal(journal)
            self.assertIn('[손절]', desk._review_past_plans(journal))
            self.assertEqual(journal[1]['orders'][0]['review_status'], '진행중')

    def test_price_failure_does_not_silently_drop_plan(self):
        with patch.object(desk, 'datetime', FixedDate):
            self.assertIn('[가격 확인 실패]', desk._review_past_plans([plan('2026-10-08 08:59')]))

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
