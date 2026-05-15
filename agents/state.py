import operator
from typing import Annotated, TypedDict


class NodeLog(TypedDict):
    node: str        # 노드 ID (함수명)
    label: str       # 한글 표시 이름
    status: str      # "success" | "error" | "skipped"
    duration_ms: int # 실행 소요 시간(ms)
    detail: str      # 결과 한 줄 설명


class MarketBriefingState(TypedDict):
    # ── 실행 컨텍스트 ─────────────────────────────────────────────────────────
    is_morning: bool
    current_time_str: str
    edition_title: str

    # ── 시장 데이터 ───────────────────────────────────────────────────────────
    kospi: dict
    kosdaq: dict
    sp500: dict
    dow: dict
    nasdaq: dict
    ewy: dict
    market_snapshot: str

    # ── AI 분석 결과 ──────────────────────────────────────────────────────────
    llm_summary_raw: str
    summary_items: list
    comic_headline: str
    image_prompt: str

    # ── 뉴스 큐레이션 ─────────────────────────────────────────────────────────
    daily_news_items: list

    # ── 이미지 ────────────────────────────────────────────────────────────────
    image_url: str

    # ── 출력 ─────────────────────────────────────────────────────────────────
    html_output: str

    # ── 실행 추적 (Annotated reducer → 병렬 노드가 동시에 append해도 안전) ──
    execution_log: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]


# HTML 시각화용 그래프 구조 메타데이터
GRAPH_STRUCTURE = [
    {"id": "collect_market_data",   "label": "시장 데이터 수집",     "icon": "📊", "parallel": False},
    {"id": "analyze_market",        "label": "AI 시장 분석",         "icon": "🤖", "parallel": True},
    {"id": "fetch_and_curate_news", "label": "뉴스 수집 & 큐레이션", "icon": "📰", "parallel": True},
    {"id": "build_visual_brief",    "label": "이미지 방향 설계",     "icon": "🎨", "parallel": False},
    {"id": "generate_image",        "label": "GPT Image 생성",      "icon": "🖼️", "parallel": False},
    {"id": "render_html",           "label": "HTML 렌더링",          "icon": "📄", "parallel": False},
    {"id": "notify",                "label": "Teams 알림",           "icon": "🔔", "parallel": False, "conditional": True},
]
