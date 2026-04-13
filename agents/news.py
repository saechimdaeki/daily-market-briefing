import os
import time

from openai import OpenAI

from daily_news_digest import build_daily_news_digest, save_daily_news_digest
from agents.state import MarketBriefingState

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "public")


def fetch_and_curate_news(state: MarketBriefingState) -> dict:
    """
    [Node] 뉴스 수집 & 큐레이션
    - 오전: 네이버 금융 스크래핑 → 본문 메타데이터 보강 → LLM 선정
    - 오후: GitHub Pages에 저장된 오늘 다이제스트 재사용
    """
    t0 = time.time()
    try:
        client = OpenAI(api_key=os.environ.get("AI_API_KEY"))
        digest = build_daily_news_digest(
            client=client,
            market_snapshot=state["market_snapshot"],
            is_morning=state["is_morning"],
            max_items=4,
        )
        save_daily_news_digest(OUTPUT_DIR, digest)
        items = digest.get("items", [])

        duration_ms = int((time.time() - t0) * 1000)
        source = "스크래핑 + LLM 큐레이션" if state["is_morning"] else "기존 다이제스트 재사용"
        detail = f"{len(items)}건 선정 ({source})"
        return {
            "daily_news_items": items,
            "execution_log": [{"node": "fetch_and_curate_news", "label": "뉴스 수집 & 큐레이션",
                                "status": "success", "duration_ms": duration_ms, "detail": detail}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "daily_news_items": [],
            "execution_log": [{"node": "fetch_and_curate_news", "label": "뉴스 수집 & 큐레이션",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"fetch_and_curate_news: {e}"],
        }
