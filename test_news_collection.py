"""뉴스 장애와 전송 차단 회귀 테스트: python -m unittest test_news_collection"""
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape

import requests
import realtime_bot as bot
import trading_desk as desk


def rss(*items):
    content = ''.join(
        f'<item><title>{escape(title)}</title><pubDate>{format_datetime(date)}</pubDate></item>'
        for title, date in items
    )
    return Mock(status_code=200, url='https://example.com/rss', content=f'<rss><channel>{content}</channel></rss>'.encode())


class NewsCollectionTests(unittest.TestCase):
    def test_direct_sources_filter_stale_and_deduplicate(self):
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        with patch.object(bot.requests, 'get', side_effect=[
            rss(('삼성전자', now), ('오래된 뉴스', now - timedelta(days=2))),
            rss(('삼성전자', now), ('미국 증시', now)),
        ]) as get:
            self.assertEqual(bot.get_finance_news_headlines(), ['삼성전자', '미국 증시'])
            self.assertEqual(get.call_count, 2)

    def test_one_source_failure_uses_other_source(self):
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        with patch.object(bot.requests, 'get', side_effect=[requests.Timeout(), rss(('최신 뉴스', now))]):
            self.assertEqual(bot.get_finance_news_headlines(), ['최신 뉴스'])

    def test_google_429_stops_further_requests(self):
        blocked = Mock(status_code=429, url='https://www.google.com/sorry/index')
        with patch.object(bot.requests, 'get', side_effect=[requests.Timeout(), requests.Timeout(), blocked]) as get:
            self.assertEqual(bot.get_finance_news_headlines(), [])
            self.assertEqual(get.call_count, 3)

    def test_google_fallback_after_invalid_and_empty_feeds(self):
        invalid = Mock(status_code=200, url='https://example.com/rss', content=b'<html>bad')
        now = datetime.now(timezone.utc) - timedelta(minutes=1)
        with patch.object(bot.requests, 'get', side_effect=[invalid, rss(), rss(('최신 뉴스 - 언론사', now)), rss(), rss(), rss()]):
            self.assertEqual(bot.get_finance_news_headlines(), ['최신 뉴스'])

    def test_missing_news_stops_graph_before_analysis_journal_and_teams(self):
        with patch.object(desk, 'get_finance_news_headlines', return_value=[]), \
             patch.object(desk, 'ask_claude_json') as ai, \
             patch.object(desk, '_load_journal') as journal, \
             patch.object(desk.requests, 'post') as post:
            with self.assertRaisesRegex(RuntimeError, '뉴스 수집 실패'):
                desk.build_desk_graph().invoke({})
            ai.assert_not_called()
            journal.assert_not_called()
            post.assert_not_called()
            self.assertEqual(desk.notify({'headlines': []}), {})
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
