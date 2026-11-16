import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dashboard_delivery import dashboard_url, publish_performance


class DeliveryTests(unittest.TestCase):
    def test_publish_preserves_other_pages_and_is_idempotent(self):
        def git(*args):
            return subprocess.run(['git', *map(str, args)], check=True, capture_output=True, text=True).stdout
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote, seed, output = root/'remote.git', root/'seed', root/'output'
            git('init', '--bare', remote)
            git('init', seed)
            git('-C', seed, 'checkout', '-b', 'gh-pages')
            (seed/'index.html').write_text('existing briefing')
            git('-C', seed, 'add', '.')
            git('-C', seed, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'initial')
            git('-C', seed, 'remote', 'add', 'origin', remote)
            git('-C', seed, 'push', 'origin', 'gh-pages')
            output.mkdir()
            for name in ('performance.html', 'performance.json'):
                (output/name).write_text('dashboard')
            self.assertTrue(publish_performance(output, str(remote)))
            self.assertFalse(publish_performance(output, str(remote)))
            self.assertEqual(git('--git-dir', remote, 'show', 'gh-pages:index.html').strip(), 'existing briefing')
            self.assertEqual(git('--git-dir', remote, 'show', 'gh-pages:performance.html').strip(), 'dashboard')

    def test_url_override(self):
        with patch.dict(os.environ, {'TRADING_DESK_URL':'https://example.com/desk'}):
            self.assertEqual(dashboard_url(), 'https://example.com/desk')

    def test_teams_button_and_graph_order(self):
        import trading_desk as desk
        state = {'headlines':['뉴스'], 'regime':{'regime':'횡보장','strategy':'관망 전략','rationale':'변동성 확인'},
                 'plan':{'summary':'진행 상황을 확인합니다.','orders':[]}, 'candidates':[], 'risk_reviews':[],
                 'technicals':{}, 'fundamentals':{}, 'review_text':'복기 기록 없음'}
        with patch.dict(os.environ, {'TEAMS_WEBHOOK_URL':'https://example.invalid/hook'}), patch.object(desk.requests, 'post') as post:
            desk.notify(state)
        card = post.call_args.kwargs['json']['attachments'][0]['content']
        self.assertEqual(card['actions'][0]['title'], '트레이딩 데스크 보러가기')
        self.assertTrue(card['actions'][0]['url'].endswith('/performance.html'))
        graph = desk.build_desk_graph().get_graph()
        edges = {(e.source,e.target) for e in graph.edges}
        self.assertIn(('operations','publish_dashboard'), edges)
        self.assertIn(('publish_dashboard','notify'), edges)
        with patch.dict(os.environ, {'TEAMS_WEBHOOK_URL':'','DESK_PUBLISH_DASHBOARD':'1'}), patch.object(desk,'publish_performance') as publish:
            desk.publish_dashboard({})
            publish.assert_not_called()

    def test_public_card_does_not_expose_diagnostics_or_old_labels(self):
        import trading_desk as desk
        state={'headlines':['뉴스'],'regime':{'regime':'횡보장','strategy':'관망 전략','rationale':'추세 확인'},
               'plan':{'summary':'계획을 확인합니다.','orders':[], 'active_orders':[
                   {'ticker':'MSFT','market':'US','name':'마이크로소프트','created_at':'2026-11-03 09:30',
                    'entry':100,'target':120,'stop_loss':95,'evaluation_error':'가상 체결 모의 오류 내부 로그'}]},
               'candidates':[], 'risk_reviews':[], 'technicals':{}, 'fundamentals':{},
               'review_text':'가상 체결 모의 결과는 계획 평가로 표시',
               'market_context':{'mode':'내부 수집 상태','sessions':{},'breadth':{},'macro':{}}}
        payload=desk.build_teams_payload(state)
        import json
        text=json.dumps(payload,ensure_ascii=False)
        for word in ('가상','모의','내부 로그','내부 수집 상태','시장 근거 · 데이터와 일정'):
            self.assertNotIn(word,text)
        self.assertIn('트레이딩 데스크 보러가기',text)

    def test_deploy_failure_does_not_suppress_teams(self):
        import trading_desk as desk
        base={'headlines':['뉴스'],'candidates':[],'technicals':{},'fundamentals':{},
              'regime':{'regime':'횡보장','strategy':'관망 전략','rationale':'추세 확인'},
              'risk_reviews':[],'plan':{'summary':'기존 계획 확인','orders':[]},'review_text':'복기 기록 없음'}
        with patch.multiple(desk,prepare_context=lambda state:{},screening=lambda state:base,
                            technical=lambda state:{},fundamental=lambda state:{},market=lambda state:{},
                            risk=lambda state:{},operations=lambda state:{}), \
             patch.dict(os.environ,{'TEAMS_WEBHOOK_URL':'https://example.invalid/hook','DESK_PUBLISH_DASHBOARD':'1'}), \
             patch.object(desk,'publish_performance',side_effect=RuntimeError('연결 오류')), \
             patch.object(desk.requests,'post') as post:
            result=desk.build_desk_graph().invoke({})
        self.assertEqual(result['dashboard_status'],'failed')
        post.assert_called_once()
        import json
        body=json.dumps(post.call_args.kwargs['json'],ensure_ascii=False)
        self.assertIn('대시보드 갱신이 지연',body)
        self.assertNotIn('연결 오류',body)


if __name__ == '__main__':
    unittest.main()
