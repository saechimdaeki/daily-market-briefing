import os
import re
import time

from jinja2 import Environment, FileSystemLoader

from agents.state import GRAPH_STRUCTURE, MarketBriefingState

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "public")


def _bold_filter(text: str) -> str:
    return re.sub(r"\*+([^*]+)\*+", r"<strong>\1</strong>", text)


def render_html(state: MarketBriefingState) -> dict:
    """
    [Node] HTML 렌더링
    - Jinja2 template.html에 state 데이터를 주입하여 public/index.html 생성
    - execution_log_map: 노드 ID → 로그 엔트리 딕셔너리 (템플릿에서 노드별 상태 표시에 사용)
    """
    t0 = time.time()
    try:
        env = Environment(loader=FileSystemLoader("."))
        env.filters["bold"] = _bold_filter
        template = env.get_template("template.html")

        # 노드 ID → log 엔트리 매핑 (정적 그래프 다이어그램 오버레이용)
        log_by_node = {entry["node"]: entry for entry in state.get("execution_log", [])}
        total_ms = sum(e.get("duration_ms", 0) for e in state.get("execution_log", []))

        html_output = template.render(
            edition_title=state["edition_title"],
            current_time=state["current_time_str"],
            comic_headline=state.get("comic_headline", ""),
            summary_items=state.get("summary_items", []),
            daily_news_items=state.get("daily_news_items", []),
            kospi=state["kospi"],
            kosdaq=state["kosdaq"],
            sp500=state["sp500"],
            dow=state["dow"],
            nasdaq=state["nasdaq"],
            ewy=state["ewy"],
            execution_log=state.get("execution_log", []),
            execution_log_map=log_by_node,
            graph_structure=GRAPH_STRUCTURE,
            total_execution_ms=total_ms,
            errors=state.get("errors", []),
        )

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_output)

        duration_ms = int((time.time() - t0) * 1000)
        return {
            "html_output": html_output,
            "execution_log": [{"node": "render_html", "label": "HTML 렌더링",
                                "status": "success", "duration_ms": duration_ms,
                                "detail": f"index.html 저장 완료 ({len(html_output):,} chars)"}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "html_output": "",
            "execution_log": [{"node": "render_html", "label": "HTML 렌더링",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"render_html: {e}"],
        }
