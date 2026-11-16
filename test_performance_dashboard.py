import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from performance_dashboard import KST, build_performance, write_dashboard


class PerformanceTests(unittest.TestCase):
    def test_closed_only_and_reentry_history(self):
        def order(status, **extra):
            return dict(ticker='ABC', simulation_version=2, review_status=status,
                        filled_at='2026-11-01 10:00', fill_price=100, review_price=110, **extra)
        journal = [{'date': '2026-11-01 09:30', 'orders': [order('목표 도달'), order('손절')]},
                   {'date': '2026-11-02 09:30', 'orders': [order('보유'),
                    order('목표 도달', evaluation_error='가격 실패'),
                    {'ticker': 'ABC', 'review_status': '목표 도달', 'entry': 100, 'review_price': 120},
                    {'ticker': 'ABC', 'review_status': '미체결 취소'}]}]
        data = build_performance(journal, datetime(2026, 11, 3, tzinfo=KST))
        summary = data['summaries']['7']
        self.assertEqual(summary['plans'], 6)
        self.assertEqual(summary['closed'], 2)
        self.assertEqual(summary['target_rate'], 50)
        self.assertEqual(summary['average_return_pct'], 10)
        self.assertEqual(len([r for r in data['rows'] if r['return_pct'] is not None]), 3)

    def test_calendar_boundary_and_empty_denominator(self):
        journal = [{'date': d, 'orders': [{'ticker': 'A'}]} for d in
                   ['2026-10-27 23:59', '2026-10-28 00:00', '2026-11-03 12:00', '2026-11-04 00:00']]
        data = build_performance(journal, datetime(2026, 11, 3, tzinfo=KST))
        self.assertEqual(data['summaries']['7']['plans'], 2)
        self.assertIsNone(data['summaries']['7']['target_rate'])

    def test_safe_standalone_output(self):
        journal = [{'date': '2026-11-03 09:30', 'orders': [{'ticker': 'A', 'thesis': '</script><script>alert(1)</script>'}]}]
        with tempfile.TemporaryDirectory() as temp:
            write_dashboard(journal, temp)
            html = Path(temp, 'performance.html').read_text()
            self.assertNotIn('</script><script>alert(1)</script>', html)
            self.assertEqual(len(json.loads(Path(temp, 'performance.json').read_text())['rows']), 1)
            self.assertIn('performance-data', html)

    def test_public_output_excludes_collection_diagnostics(self):
        context={'quality':{'SECRET_DIAGNOSTIC':{'reason':'가상 체결 내부 오류'}},'prices':{},
                 'macro':{'sources':{'BLS':{'status':'미확인','reason':'HTTPError'}}}}
        journal=[{'date':'2026-11-03 09:30','data_checks':{'internal':'private'},'orders':[
            {'ticker':'MSFT','evaluation_error':'가상 체결 모의 내부 오류'}]}]
        data=build_performance(journal,context=context)
        text=json.dumps(data,ensure_ascii=False)
        self.assertNotIn('SECRET_DIAGNOSTIC',text)
        self.assertNotIn('HTTPError',text)
        self.assertNotIn('가상',text)
        self.assertNotIn('모의',text)
        self.assertIn('평가 확인 중',text)
        self.assertIn('quality',context)


if __name__ == '__main__':
    unittest.main()
