import json
import os
import time

from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from agents.state import MarketBriefingState


def _make_llm(temperature: float = 0.7) -> ChatOpenAI:
    return ChatOpenAI(
        model="gpt-4o-mini",
        temperature=temperature,
        api_key=os.environ.get("AI_API_KEY"),
    )


def analyze_market(state: MarketBriefingState) -> dict:
    """
    [Node] AI 시장 분석 (LangChain LCEL 패턴)
    Chain 1: 시장 요약 3~5 포인트  (prompt | llm | StrOutputParser)
    Chain 2: 헤드라인 생성         (prompt | llm | StrOutputParser)
    """
    t0 = time.time()
    try:
        llm = _make_llm(temperature=0.7)
        str_parser = StrOutputParser()

        # ── Chain 1: 시장 요약 ────────────────────────────────────────────────
        kospi = state["kospi"]
        kosdaq = state["kosdaq"]
        sp500 = state["sp500"]
        dow = state["dow"]
        nasdaq = state["nasdaq"]
        ewy = state["ewy"]
        prompt_context = (
            "간밤의 미국 시장 주요 이슈와 오늘 아침 한국 시장의 개장 흐름 및 관전 포인트"
            if state["is_morning"]
            else "오늘 한국 시장 마감 상황 요약 및 오늘 밤 미국 시장 관전 포인트"
        )

        text_prompt_str = f"""
현재 팩트 데이터 (절대 지어내지 말 것):
- 현재 국장: 코스피 {kospi['price']} ({kospi['change']}), 코스닥 {kosdaq['price']} ({kosdaq['change']})
- 미장 데이터: S&P500 {sp500['price']} ({sp500['change']}), 다우존스 {dow['price']} ({dow['change']}), 나스닥 {nasdaq['price']} ({nasdaq['change']})
- 한국 야간지표(EWY): {ewy['price']} ({ewy['change']} - {ewy['trend']})

당신은 여의도의 실전 투자 수석 애널리스트입니다. 위 데이터를 완벽히 분석하여 {prompt_context}를 3~5개의 핵심 포인트로 작성해 줘.

[필수 분석 조건]
1. '한국 야간지표(EWY)'의 등락률과 간밤 미장 흐름을 종합적으로 언급할 것.
2. 현재 코스피/코스닥의 실제 등락 수치를 바탕으로 오늘 국장 흐름을 정확히 진단할 것.
3. 데이터 간의 온도 차이가 있다면, 오늘 투자자들이 어떤 포지션을 취해야 하는지 대응 전략을 제시할 것.
4. 각 포인트는 글머리 기호 없이 한 줄씩 작성하고, 강조할 핵심 단어 양쪽에만 별표(**)를 붙일 것.
"""
        summary_prompt = ChatPromptTemplate.from_messages([("user", "{input}")])
        summary_chain = summary_prompt | llm | str_parser
        llm_summary_raw = summary_chain.invoke({"input": text_prompt_str})
        summary_items = [
            item.strip().lstrip("-").lstrip("*").strip()
            for item in llm_summary_raw.split("\n")
            if item.strip()
        ]

        # ── Chain 2: 헤드라인 ─────────────────────────────────────────────────
        headline_prompt_str = f"""
다음 요약 내용을 바탕으로, 시장의 충돌감과 아이러니가 느껴지는 아주 짧고 강렬한 한 줄 헤드라인을 만들어줘.

[규칙]
- 12자~18자 내외
- 단순 설명문 말고, 장세의 긴장감이나 온도 차가 느껴지게
- 과장 광고 문구 말고 실제 시장 요약과 맞아야 함
- 특수기호, 이모지, 마크다운 금지

내용:
{llm_summary_raw}
"""
        headline_prompt = ChatPromptTemplate.from_messages([("user", "{input}")])
        headline_chain = headline_prompt | llm | str_parser
        comic_headline = headline_chain.invoke({"input": headline_prompt_str}).strip()

        duration_ms = int((time.time() - t0) * 1000)
        return {
            "llm_summary_raw": llm_summary_raw,
            "summary_items": summary_items,
            "comic_headline": comic_headline,
            "execution_log": [{"node": "analyze_market", "label": "AI 시장 분석",
                                "status": "success", "duration_ms": duration_ms,
                                "detail": f"요약 {len(summary_items)}포인트 | 헤드라인: {comic_headline[:20]}"}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "llm_summary_raw": "",
            "summary_items": [],
            "comic_headline": "시장 브리핑",
            "execution_log": [{"node": "analyze_market", "label": "AI 시장 분석",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"analyze_market: {e}"],
        }


def build_visual_brief(state: MarketBriefingState) -> dict:
    """
    [Node] 이미지 방향 설계 (LangChain LCEL 패턴)
    Chain: prompt | llm(temperature=0.9) | JsonOutputParser  →  4컷 패널 blueprint
    이후 blueprint를 DALL-E 프롬프트 문자열로 포맷
    """
    t0 = time.time()

    fallback_brief = {
        "primary_catalyst": "overnight macro shock and positioning battle",
        "catalyst_type": "macro",
        "must_show": ["US index board", "EWY monitor", "Korean trading desk"],
        "visual_style": "polished Korean editorial illustration, premium finance magazine cover",
        "color_palette": "electric red and cobalt blue market colors, emergency amber lights",
        "mood_keywords": ["satirical", "cinematic", "urgent", "high-contrast"],
        "panels": [
            {"focus": "overnight US market setting the tone", "shot": "wide",
             "scene": "pre-market war room, flashing US index boards, EWY wobbling",
             "characters": "retail investor, exhausted strategist", "symbol": "split scoreboard", "caption": "Night Shift"},
            {"focus": "KOSPI and KOSDAQ diverging", "shot": "medium",
             "scene": "two market elevators at different speeds, investors switching lanes",
             "characters": "office workers, day traders", "symbol": "double elevator", "caption": "Rotation"},
            {"focus": "key risk behind the session", "shot": "close-up",
             "scene": "boxing ring, greed vs fear, warning lights",
             "characters": "two traders, referee analyst", "symbol": "boxing bell", "caption": "Risk On?"},
            {"focus": "today's actionable takeaway", "shot": "overhead",
             "scene": "trader at forked road, candles exploding overhead",
             "characters": "solo investor, shadowy fund manager", "symbol": "three-way crossroads", "caption": "Your Move"},
        ],
    }

    try:
        llm = _make_llm(temperature=0.9)
        prompt_context = (
            "간밤의 미국 시장 주요 이슈와 오늘 아침 한국 시장의 개장 흐름 및 관전 포인트"
            if state["is_morning"]
            else "오늘 한국 시장 마감 상황 요약 및 오늘 밤 미국 시장 관전 포인트"
        )

        visual_brief_prompt_str = f"""
너는 금융 시사만평과 증권사 커버 아트에 특화된 아트 디렉터다.
[시장 맥락] {prompt_context}
[시장 데이터] {state['market_snapshot']}
[요약] {state['llm_summary_raw']}

[판단 원칙]
1. 요약에서 시장을 움직인 핵심 촉매를 하나로 특정해라.
2. 실존 인물이 핵심이면 recognizably editorial caricature를 전면 배치해라.
3. 각 컷은 서로 다른 시장 포인트를 설명해야 한다.
4. 투자자 심리, 포지셔닝 변화, 리스크 온오프가 장면에서 읽혀야 한다.

[강한 금지 사항]
- 황소/곰 캐릭터, 치비 캐릭터, 동물 마스코트 사용 금지
- 의미 없는 리액션샷 4연속 금지, 파스텔 유아풍 금지

아래 JSON만 출력해라.
{{
  "primary_catalyst": "핵심 인물 또는 사건",
  "catalyst_type": "person | policy | macro | geopolitical | earnings | sector",
  "must_show": ["요소1", "요소2"],
  "visual_style": "전체 그림 스타일 한 줄",
  "color_palette": "색감 방향 한 줄",
  "mood_keywords": ["키워드1", "키워드2", "키워드3", "키워드4"],
  "panels": [
    {{"focus": "시장 포인트", "shot": "wide | medium | close-up | overhead",
      "scene": "장면 설명", "characters": "등장인물/오브젝트", "symbol": "핵심 상징", "caption": "1~3단어"}}
  ]
}}
"""
        brief_prompt = ChatPromptTemplate.from_messages([("user", "{input}")])
        brief_chain = brief_prompt | llm | JsonOutputParser()
        visual_brief = brief_chain.invoke({"input": visual_brief_prompt_str})

        if len(visual_brief.get("panels", [])) != 4:
            raise ValueError(f"패널 수 오류: {len(visual_brief.get('panels', []))}")

    except Exception as e:
        print(f"비주얼 브리프 생성 실패: {e}")
        visual_brief = fallback_brief

    # ── DALL-E 프롬프트 포맷 ──────────────────────────────────────────────────
    mood_keywords = ", ".join(visual_brief.get("mood_keywords", fallback_brief["mood_keywords"]))
    must_show = ", ".join(visual_brief.get("must_show", fallback_brief["must_show"]))
    panels = visual_brief.get("panels", fallback_brief["panels"])
    panel_directions = "\n".join([
        f"- Panel {i}: focus={p.get('focus','')}; shot={p.get('shot','')}; scene={p.get('scene','')}; "
        f"characters={p.get('characters','')}; symbol={p.get('symbol','')}; caption={p.get('caption','')}"
        for i, p in enumerate(panels, 1)
    ])

    image_prompt = f"""
Create a bold 4-panel editorial comic cover about the stock market headline: "{state['comic_headline']}".

[Story context]
{state['llm_summary_raw']}

[Concrete market snapshot]
{state['market_snapshot']}

[Art direction]
- Style: {visual_brief.get('visual_style', fallback_brief['visual_style'])}
- Mood: {mood_keywords}
- Palette: {visual_brief.get('color_palette', fallback_brief['color_palette'])}
- Primary catalyst: {visual_brief.get('primary_catalyst', fallback_brief['primary_catalyst'])}
- Catalyst type: {visual_brief.get('catalyst_type', fallback_brief['catalyst_type'])}
- Must-show visual anchors: {must_show}
- Tone: provocative, witty, sharp, financially literate, visually surprising
- Make it feel like a Korean market satire cover or financial magazine illustration
- Visual quality must be beautiful, premium, and polished — not a rough storyboard
- Use human characters, officials, traders, anchors, analysts, or realistic symbolic objects only
- Absolutely do not use bulls, bears, animals, mascots, plushies, chibi figures
- Avoid cute mascot energy, nursery pastel aesthetics, and repetitive faces
- No copyrighted characters, no brand logos; if text appears keep it 1-3 words per panel

[Panel blueprint]
{panel_directions}

[Composition]
- 2x2 grid, cinematic escalation from panel 1 to panel 4
- Each panel must depict a distinct market beat tied to the real data above
"""

    duration_ms = int((time.time() - t0) * 1000)
    return {
        "image_prompt": image_prompt,
        "execution_log": [{"node": "build_visual_brief", "label": "이미지 방향 설계",
                            "status": "success", "duration_ms": duration_ms,
                            "detail": f"catalyst: {visual_brief.get('primary_catalyst', '?')[:40]}"}],
        "errors": [],
    }
