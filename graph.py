"""
LangGraph StateGraph 조립

실행 흐름:
  START
    ↓
  collect_market_data                  ← Naver API + yfinance
    ↓ (fan-out: 병렬 실행)
  ┌─ analyze_market ─────────────────┐  LangChain LCEL: 요약 + 헤드라인
  └─ fetch_and_curate_news ──────────┘  Naver 스크래핑 + GPT 큐레이션
    ↓ (fan-in: 두 노드 모두 완료 후)
  build_visual_brief                   LangChain LCEL: 4컷 이미지 방향 JSON
    ↓
  generate_image                       DALL-E-3 생성 + cover.png 저장
    ↓
  render_html                          Jinja2 렌더링 + index.html 저장
    ↓ (conditional edge)
  notify (TEAMS_WEBHOOK_URL 있을 때)   Adaptive Card 전송
    ↓
  END
"""

import os

from langgraph.graph import END, START, StateGraph

from agents.analysis import analyze_market, build_visual_brief
from agents.image_gen import generate_image
from agents.market_data import collect_market_data
from agents.news import fetch_and_curate_news
from agents.notifier import notify
from agents.renderer import render_html
from agents.state import MarketBriefingState


def _should_notify(state: MarketBriefingState) -> str:
    """조건부 엣지: Teams webhook URL이 설정된 경우에만 notify 노드로 분기"""
    return "notify" if os.environ.get("TEAMS_WEBHOOK_URL") else END


def build_graph():
    builder = StateGraph(MarketBriefingState)

    # ── 노드 등록 ──────────────────────────────────────────────────────────────
    builder.add_node("collect_market_data",   collect_market_data)
    builder.add_node("analyze_market",        analyze_market)
    builder.add_node("fetch_and_curate_news", fetch_and_curate_news)
    builder.add_node("build_visual_brief",    build_visual_brief)
    builder.add_node("generate_image",        generate_image)
    builder.add_node("render_html",           render_html)
    builder.add_node("notify",                notify)

    # ── 엣지 정의 ──────────────────────────────────────────────────────────────
    builder.add_edge(START, "collect_market_data")

    # fan-out: 시장 데이터 수집 완료 후 두 노드를 병렬 실행
    builder.add_edge("collect_market_data", "analyze_market")
    builder.add_edge("collect_market_data", "fetch_and_curate_news")

    # fan-in: 두 병렬 노드가 모두 완료된 후 이미지 방향 설계
    builder.add_edge("analyze_market",        "build_visual_brief")
    builder.add_edge("fetch_and_curate_news", "build_visual_brief")

    builder.add_edge("build_visual_brief", "generate_image")
    builder.add_edge("generate_image",     "render_html")

    # 조건부 엣지: Teams webhook 설정 여부에 따라 분기
    builder.add_conditional_edges(
        "render_html",
        _should_notify,
        {"notify": "notify", END: END},
    )
    builder.add_edge("notify", END)

    return builder.compile()
