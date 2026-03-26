import json
import os
import re

from openai import OpenAI


def _normalize_text(text):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(text or "").lower())


def _strip_code_fence(text):
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_json_loose(text):
    raw = _strip_code_fence(text)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return json.loads(raw[start : end + 1])
    raise ValueError("theme detector JSON parse failed")


def _build_openai_client(client=None):
    if client is not None:
        return client
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def _ai_detect_theme_candidates(client, headlines, stocks, max_themes):
    if not client:
        return []

    prompt = f"""
오늘 한국/미국 증시 뉴스와 종목 메모를 보고, 시장에서 반복적으로 부각되는 핵심 테마만 3~{max_themes}개 추출해라.

[중요]
- 반드시 뉴스와 종목 reason에 실제로 드러나는 테마만 추출
- 너무 넓은 단어 말고 투자자가 바로 이해할 수 있는 테마명으로 압축
- 비슷한 테마는 합쳐라. 예: AI 메모리/HBM 관련주는 HBM으로 통일 가능
- 테마명은 2~8자 정도의 짧은 한국어 또는 널리 쓰이는 영문 약어
- 각 테마마다 근거 키워드, 한 줄 요약, 연결 종목을 넣어라
- 연결 종목은 아래 stock list에 있는 종목만 사용

[뉴스 헤드라인]
{json.dumps(headlines, ensure_ascii=False)}

[종목 리스트]
{json.dumps(
    [{"name": stock.get("name"), "ticker": stock.get("ticker"), "reason": stock.get("reason")} for stock in stocks],
    ensure_ascii=False,
)}

아래 JSON 객체만 출력해라. 백틱 금지.
{{
  "themes": [
    {{
      "theme": "전력기기",
      "keywords": ["전력망", "변압기", "송전"],
      "summary": "미국 전력망 투자 확대로 관련 장비주가 반복 언급됨",
      "members": [
        {{"name": "효성중공업", "ticker": "298040.KS"}},
        {{"name": "HD현대일렉트릭", "ticker": "267260.KS"}}
      ]
    }}
  ]
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    data = _parse_json_loose(response.choices[0].message.content or "")
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(themes, list):
        return []

    cleaned = []
    for theme in themes[:max_themes]:
        if not isinstance(theme, dict):
            continue
        theme_name = str(theme.get("theme") or "").strip()
        if not theme_name:
            continue
        keywords = [str(keyword).strip() for keyword in theme.get("keywords", []) if str(keyword).strip()]
        members = []
        for member in theme.get("members", []):
            if not isinstance(member, dict):
                continue
            name = str(member.get("name") or "").strip()
            ticker = str(member.get("ticker") or "").strip()
            if name or ticker:
                members.append({"name": name, "ticker": ticker})
        cleaned.append(
            {
                "theme": theme_name,
                "keywords": keywords[:5],
                "summary": str(theme.get("summary") or "").strip(),
                "members": members,
            }
        )
    return cleaned

def _count_headline_hits(headlines, candidate):
    search_terms = [candidate["theme"]] + candidate.get("keywords", [])
    matched = []
    for headline in headlines:
        normalized = _normalize_text(headline)
        if any(_normalize_text(term) in normalized for term in search_terms if term):
            matched.append(headline)
    unique = []
    for headline in matched:
        if headline not in unique:
            unique.append(headline)
    return unique


def _resolve_candidate_members(candidate, stocks):
    resolved = []
    seen = set()
    candidate_names = {
        _normalize_text(member.get("name"))
        for member in candidate.get("members", [])
        if member.get("name")
    }
    candidate_tickers = {
        str(member.get("ticker") or "").upper()
        for member in candidate.get("members", [])
        if member.get("ticker")
    }
    keywords = [_normalize_text(candidate["theme"])] + [
        _normalize_text(keyword) for keyword in candidate.get("keywords", [])
    ]

    for stock in stocks:
        ticker = str(stock.get("ticker") or "").upper()
        normalized_name = _normalize_text(stock.get("name"))
        search_text = _normalize_text(
            " ".join(
                [
                    stock.get("name", ""),
                    stock.get("ticker", ""),
                    stock.get("reason", ""),
                ]
            )
        )
        matched = (
            ticker in candidate_tickers
            or normalized_name in candidate_names
            or any(keyword and keyword in search_text for keyword in keywords)
        )
        if matched and ticker not in seen:
            seen.add(ticker)
            resolved.append(stock)
    return resolved


def _normalize_metric(values, value):
    cleaned = [float(v) for v in values if v is not None]
    if not cleaned or value is None:
        return 0.0
    min_value = min(cleaned)
    max_value = max(cleaned)
    if max_value == min_value:
        return 1.0 if value > 0 else 0.0
    return (float(value) - min_value) / (max_value - min_value)


def _build_stance(avg_change_pct, positive_ratio, headline_count):
    avg_change_pct = avg_change_pct or 0.0
    positive_ratio = positive_ratio or 0.0
    if avg_change_pct >= 1.5 and positive_ratio >= 0.6:
        return "강세"
    if avg_change_pct <= -1.0 and positive_ratio <= 0.4:
        return "약세"
    if headline_count >= 4 and abs(avg_change_pct) < 0.6:
        return "뉴스과열"
    return "혼조"


def detect_market_themes(headlines, stocks, indicator_lookup=None, client=None, max_themes=5):
    indicator_lookup = indicator_lookup or {}
    if not headlines and not stocks:
        return {"themes": [], "market_regime_note": "반복적으로 부각된 테마가 아직 뚜렷하지 않습니다."}

    openai_client = _build_openai_client(client)
    try:
        candidates = _ai_detect_theme_candidates(openai_client, headlines, stocks, max_themes=max_themes)
    except Exception as exc:
        print(f"AI 테마 추출 실패: {exc}")
        candidates = []

    if not candidates:
        return {"themes": [], "market_regime_note": "오늘은 AI가 뚜렷한 반복 테마를 포착하지 못했습니다."}

    enriched = []
    for candidate in candidates:
        matched_headlines = _count_headline_hits(headlines, candidate)
        matched_stocks = _resolve_candidate_members(candidate, stocks)
        if not matched_headlines and not matched_stocks:
            continue

        members = []
        pct_changes = []
        signal_total = 0
        positive_count = 0

        for stock in matched_stocks:
            ticker = stock.get("ticker")
            indicators = indicator_lookup.get(ticker) or {}
            pct_change = indicators.get("pct_change")
            signals = indicators.get("signals") or []
            if pct_change is not None:
                pct_changes.append(pct_change)
                if pct_change > 0:
                    positive_count += 1
            signal_total += len(signals)
            members.append(
                {
                    "name": stock.get("name"),
                    "ticker": ticker,
                    "reason": stock.get("reason"),
                    "price_change_pct": round(pct_change, 2) if pct_change is not None else None,
                    "signal_count": len(signals),
                    "signals": signals,
                }
            )

        member_count = len(members)
        avg_change_pct = round(sum(pct_changes) / len(pct_changes), 2) if pct_changes else None
        avg_abs_change = round(sum(abs(change) for change in pct_changes) / len(pct_changes), 2) if pct_changes else 0.0
        positive_ratio = round(positive_count / member_count, 2) if member_count else 0.0
        signal_density = round(signal_total / member_count, 2) if member_count else 0.0
        enriched.append(
            {
                "theme": candidate["theme"],
                "keywords": candidate.get("keywords", []),
                "summary_hint": candidate.get("summary", ""),
                "headline_examples": matched_headlines[:3],
                "headline_count": len(matched_headlines),
                "members": members,
                "member_count": member_count,
                "avg_change_pct": avg_change_pct,
                "avg_abs_change": avg_abs_change,
                "positive_ratio": positive_ratio,
                "signal_density": signal_density,
            }
        )

    if not enriched:
        return {"themes": [], "market_regime_note": "반복적으로 부각된 테마가 아직 뚜렷하지 않습니다."}

    headline_counts = [item["headline_count"] for item in enriched]
    member_counts = [item["member_count"] for item in enriched]
    abs_changes = [item["avg_abs_change"] for item in enriched]
    signal_densities = [item["signal_density"] for item in enriched]
    positive_ratios = [item["positive_ratio"] for item in enriched]

    summaries = []
    for item in enriched:
        headline_score = _normalize_metric(headline_counts, item["headline_count"])
        member_score = _normalize_metric(member_counts, item["member_count"])
        move_score = _normalize_metric(abs_changes, item["avg_abs_change"])
        signal_score = _normalize_metric(signal_densities, item["signal_density"])
        positive_score = _normalize_metric(positive_ratios, item["positive_ratio"])
        score = round(
            100
            * (
                0.35 * headline_score
                + 0.25 * member_score
                + 0.20 * move_score
                + 0.15 * signal_score
                + 0.05 * positive_score
            )
        )
        leaders = sorted(
            item["members"],
            key=lambda member: (
                member["price_change_pct"] is None,
                -(member["price_change_pct"] or 0),
                -member["signal_count"],
            ),
        )[:3]
        stance = _build_stance(item["avg_change_pct"], item["positive_ratio"], item["headline_count"])
        summary = item["summary_hint"] or (
            f"{item['theme']} 테마는 뉴스 {item['headline_count']}건과 관련 종목 {item['member_count']}개로 포착됐고 "
            f"평균 등락률은 {item['avg_change_pct']:+.2f}%입니다."
            if item["avg_change_pct"] is not None
            else f"{item['theme']} 테마는 뉴스 {item['headline_count']}건을 중심으로 포착됐습니다."
        )
        summaries.append(
            {
                "theme": item["theme"],
                "score": score,
                "headline_count": item["headline_count"],
                "member_count": item["member_count"],
                "avg_change_pct": item["avg_change_pct"],
                "positive_member_ratio": item["positive_ratio"],
                "signal_density": item["signal_density"],
                "keywords": item["keywords"],
                "headline_examples": item["headline_examples"],
                "leaders": leaders,
                "stance": stance,
                "summary": summary,
            }
        )

    summaries.sort(
        key=lambda item: (
            -item["score"],
            -item["headline_count"],
            -item["member_count"],
            item["theme"],
        )
    )
    top_themes = summaries[:max_themes]
    theme_names = ", ".join([theme["theme"] for theme in top_themes[:3]])
    note = (
        f"오늘 뉴스 흐름은 {theme_names} 중심으로 반복되고 있습니다."
        if theme_names
        else "반복적으로 부각된 테마가 아직 뚜렷하지 않습니다."
    )
    return {"themes": top_themes, "market_regime_note": note}


def format_theme_brief_lines(themes, max_stocks=3):
    lines = []
    for theme in themes:
        stock_names = ", ".join(
            leader["name"] for leader in theme.get("leaders", [])[:max_stocks] if leader.get("name")
        )
        stock_label = stock_names or "대표 종목 미확인"
        avg_text = f"{theme['avg_change_pct']:+.2f}%" if theme.get("avg_change_pct") is not None else "N/A"
        lines.append(
            f"{theme['theme']} | 점수 {theme['score']} | {theme['stance']} | "
            f"뉴스 {theme['headline_count']}건 | 평균 {avg_text} | 대표 {stock_label}"
        )
    return lines
