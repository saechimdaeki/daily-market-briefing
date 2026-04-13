import os
from datetime import datetime

import pytz

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

os.makedirs("public", exist_ok=True)

from graph import build_graph  # noqa: E402 (imports after env setup)

KST = pytz.timezone("Asia/Seoul")
now_kst = datetime.now(KST)
is_morning = now_kst.hour < 12

initial_state = {
    "is_morning": is_morning,
    "current_time_str": now_kst.strftime("%Y-%m-%d %H:%M:%S"),
    "edition_title": (
        "Morning Briefing: 간밤의 미장 & 국장 프리뷰"
        if is_morning
        else "Evening Briefing: 오늘 국장 실시간 & 미장 프리뷰"
    ),
    # 나머지 필드는 각 노드가 채움
    "kospi": {}, "kosdaq": {}, "sp500": {}, "dow": {}, "nasdaq": {}, "ewy": {},
    "market_snapshot": "",
    "llm_summary_raw": "", "summary_items": [], "comic_headline": "", "image_prompt": "",
    "daily_news_items": [],
    "image_url": "",
    "html_output": "",
    "execution_log": [],
    "errors": [],
}

graph = build_graph()
final_state = graph.invoke(initial_state)

# ── 실행 결과 요약 출력 ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("LangGraph 실행 완료")
print("=" * 60)
for log in final_state.get("execution_log", []):
    status_icon = "✅" if log["status"] == "success" else "❌"
    print(f"  {status_icon} {log['label']:<22} {log['duration_ms']:>6}ms  {log['detail']}")

total_ms = sum(e.get("duration_ms", 0) for e in final_state.get("execution_log", []))
print(f"\n  총 실행 시간: {total_ms:,}ms")

errors = final_state.get("errors", [])
if errors:
    print("\n[에러 목록]")
    for err in errors:
        print(f"  • {err}")
print("=" * 60)
