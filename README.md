# 📈 AI Daily Market Briefing & Real-time Stock Monitor

매일 아침/저녁 글로벌 증시 시황을 요약해주는 **[데일리 브리핑]**과, 장중에 쏟아지는 뉴스와 기술적 지표를 분석해 매수/매도 타이밍을 잡아주는 **[실시간 특징주 감시 봇]**을 결합한 완벽한 서버리스(Serverless) AI 투자 비서 파이프라인입니다.

---

## ✨ Key Features

### 1. ⚡ 실시간 특징주 퀀트 & AI 모니터링 (**Update!**)
* **📰 실시간 뉴스 스캐닝**: `BeautifulSoup`을 이용해 네이버 금융 주요 뉴스를 수집하고, GPT-4o-mini가 가장 핫한 상장 기업(타겟 종목)을 동적으로 추출합니다.
* **📊 5대 핵심 보조지표 분석**: `yfinance`와 `pandas`를 활용해 단순 등락률을 넘어 **RSI, MACD, 볼린저 밴드, 일목균형표, 피보나치 되돌림**을 실시간으로 계산합니다.
* **🧠 AI 3줄 심층 브리핑**: MACD 크로스, 밴드 돌파 등 유의미한 '기술적 시그널'이 포착된 종목에 한해, AI가 **[모멘텀 - 기술적 평가 - 단기 대응 전략]**의 전문가급 리포트를 작성합니다.
* **🔔 MS Teams 통합 알림**: 수집된 데이터와 AI 분석 결과를 **Adaptive Cards** 형태로 가공하여 팀즈로 즉시 전송합니다.
* **⌨️ Teams `!주가` 온디맨드 조회**: Teams Workflow 또는 Teams Outgoing Webhook에서 `!주가 SK하이닉스` 같은 명령을 받아 GitHub Actions를 호출하고, 단일 종목 브리핑 카드를 다시 Teams 채널로 전송할 수 있습니다.

### 2. 🌅 AI 데일리 마켓 브리핑
* **팩트 폭격 AI 분석**: 주요 지수(KOSPI, S&P 500 등)의 실제 등락률 데이터를 프롬프트에 주입하여 정확한 시황 브리핑을 제공합니다.
* **🎨 DALL-E 3 네컷 만화**: 매일의 증시 테마를 바탕으로 귀여운 황소와 곰돌이가 등장하는 웹툰을 자동 생성합니다.
* **💻 프리미엄 핀테크 대시보드**: `Jinja2` 템플릿을 활용하여 깔끔한 정적 웹페이지(HTML)로 렌더링하고 **GitHub Pages**로 배포합니다.

---

## 📸 Screenshots

### 1. MS Teams 실시간 특징주 알림 (Real-time Alert)
장중 유의미한 기술적 시그널(MACD 크로스, 과매수/과매도 등) 발생 시 통합 브리핑 전송
<img width="566" height="659" alt="image" src="https://github.com/user-attachments/assets/953e2ee9-3c2f-4521-8f2e-cd68fe9e6b17" />

### 2. MS Teams 데일리 마켓 브리핑 (Daily Alert)
매일 아침/저녁 주요 지수 요약 및 만화 생성

<img width="600" height="579" alt="image" src="https://github.com/user-attachments/assets/7759ceb0-461a-4e62-a7f7-22132de6dc08" />


### 3. Premium Web Dashboard
GitHub Pages로 자동 배포되는 데일리 리포트 웹페이지

<img width="681" height="926" alt="image" src="https://github.com/user-attachments/assets/b98f78ed-ba75-4e0f-b31f-cce468eb2e5f" />


---

## 🛠 Tech Stack

| 분류 | 기술 |
|------|------|
| **Language** | Python 3.10 |
| **Agent Framework** | LangGraph (StateGraph), LangChain (LCEL) |
| **AI Models** | OpenAI GPT-4o-mini (Text/JSON), DALL-E 3 (Image) |
| **LLM Client** | langchain-openai (ChatOpenAI), openai SDK |
| **Data & Scraping** | yfinance, pandas, BeautifulSoup4 |
| **Template Engine** | Jinja2 |
| **CI/CD & Hosting** | GitHub Actions, GitHub Pages |
| **Notification** | MS Teams (Incoming Webhook & Adaptive Cards) |

---

## ⚙️ How it Works

### Track B: Daily Dashboard — LangGraph Multi-Agent Pipeline (`main.py` + `graph.py`)

데일리 브리핑은 **LangGraph `StateGraph`** 기반의 멀티에이전트 파이프라인으로 동작합니다.  
모든 노드는 `MarketBriefingState`(TypedDict)를 공유 상태로 주고받으며, 병렬 실행과 조건부 분기를 그래프 엣지로 선언합니다.

#### 실행 흐름

```
START
  │
  ▼
[📊 collect_market_data]          ← 네이버 금융 API(국장) + yfinance(미장/ETF)
  │
  ├──────────────────────────────┐  (fan-out: 병렬 실행)
  ▼                              ▼
[🤖 analyze_market]    [📰 fetch_and_curate_news]
  LangChain LCEL                  네이버 금융 스크래핑
  요약 3~5포인트                   + 본문 메타데이터 보강
  헤드라인 생성                    + LLM 뉴스 4건 선정
  │                              │
  └──────────────────────────────┘  (fan-in: 두 노드 완료 후)
  │
  ▼
[🎨 build_visual_brief]           ← LangChain LCEL (JsonOutputParser)
  4컷 패널 blueprint JSON 생성     catalyst, mood, shot 방향 설계
  → DALL-E 최종 프롬프트 포맷
  │
  ▼
[🖼️ generate_image]               ← DALL-E-3 API, cover.png 저장
  │
  ▼
[📄 render_html]                  ← Jinja2, execution_log 오버레이 포함
  │
  └─ TEAMS_WEBHOOK_URL 있음? ──▶ [🔔 notify]  Adaptive Card 전송
                        없음? ──▶ END
```

#### 주요 설계 패턴

**1. `MarketBriefingState` — 공유 상태 TypedDict**

모든 노드의 입출력을 하나의 불변 State 객체로 관리합니다.  
병렬 노드가 동시에 같은 리스트 필드에 쓰는 충돌을 `Annotated[list, operator.add]` reducer로 해결합니다.

```python
class MarketBriefingState(TypedDict):
    kospi: dict
    llm_summary_raw: str
    daily_news_items: list
    image_prompt: str
    # 병렬 노드가 동시에 append해도 안전한 reducer
    execution_log: Annotated[list, operator.add]
    errors:        Annotated[list, operator.add]
```

**2. 병렬 fan-out / fan-in**

`analyze_market`(GPT 분석)과 `fetch_and_curate_news`(스크래핑)는 서로 의존성이 없으므로 동시에 실행됩니다.  
LangGraph는 두 노드가 모두 완료된 뒤 State를 merge하여 `build_visual_brief`로 넘깁니다.

```python
builder.add_edge("collect_market_data", "analyze_market")
builder.add_edge("collect_market_data", "fetch_and_curate_news")
# 두 노드 모두 완료되어야 build_visual_brief 실행
builder.add_edge("analyze_market",        "build_visual_brief")
builder.add_edge("fetch_and_curate_news", "build_visual_brief")
```

**3. LangChain LCEL (LangChain Expression Language)**

`analyze_market`과 `build_visual_brief` 노드에서 `prompt | llm | parser` 체인 패턴으로 LLM을 호출합니다.

```python
# 시장 요약: 자연어 출력
summary_chain = ChatPromptTemplate.from_messages([("user", "{input}")]) \
    | ChatOpenAI(model="gpt-4o-mini") \
    | StrOutputParser()

# 이미지 방향 설계: JSON 출력
brief_chain = ChatPromptTemplate.from_messages([("user", "{input}")]) \
    | ChatOpenAI(model="gpt-4o-mini", temperature=0.9) \
    | JsonOutputParser()
```

**4. 조건부 엣지**

`TEAMS_WEBHOOK_URL` 환경변수 유무에 따라 `notify` 노드를 실행할지 결정합니다.

```python
builder.add_conditional_edges(
    "render_html",
    lambda s: "notify" if os.environ.get("TEAMS_WEBHOOK_URL") else END,
    {"notify": "notify", END: END},
)
```

**5. 실행 흐름 시각화**

각 노드는 실행 후 `execution_log`에 소요 시간과 결과를 기록합니다.  
렌더링된 `public/index.html` 하단 "LangGraph Agent 실행 흐름" 섹션에서 노드별 상태를 시각적으로 확인할 수 있습니다.

```python
return {
    "execution_log": [{
        "node": "collect_market_data",
        "label": "시장 데이터 수집",
        "status": "success",
        "duration_ms": 1823,
        "detail": "KOSPI 2,580 | KOSDAQ 742 | S&P500 5,123"
    }],
    ...
}
```

#### 파일 구조

```
daily-market-briefing/
├── agents/
│   ├── state.py          # MarketBriefingState TypedDict + GRAPH_STRUCTURE
│   ├── market_data.py    # [Node] 시장 데이터 수집
│   ├── news.py           # [Node] 뉴스 수집 & 큐레이션
│   ├── analysis.py       # [Node] AI 시장 분석 + 이미지 방향 설계 (LangChain LCEL)
│   ├── image_gen.py      # [Node] DALL-E-3 이미지 생성
│   ├── renderer.py       # [Node] Jinja2 HTML 렌더링
│   └── notifier.py       # [Node] Teams Adaptive Card 전송
├── graph.py              # StateGraph 조립 (엣지 + 조건부 분기)
├── main.py               # 진입점: 초기 State 설정 → graph.invoke()
└── daily_news_digest.py  # 뉴스 스크래핑 + GPT 큐레이션 유틸리티
```

---

### Track A: Real-time Monitor (`realtime_bot.py`)
1. **[Data Ingestion]** 네이버 금융 메인 뉴스 헤드라인 실시간 크롤링
2. **[Target Extraction]** GPT가 기사를 분석해 수혜/타격 예상 핵심 상장사 동적 추출
3. **[Quant Analysis]** `pandas`로 6개월치 데이터를 분석해 RSI, MACD, 볼린저 밴드 등 시그널 감지
4. **[AI Briefing]** 강력한 시그널이 발생한 종목만 추려내어 AI 심층 브리핑 생성 후 Teams 전송

### Track C: Teams Stock Command
1. **[Command Trigger]** Teams Workflow 또는 Teams Outgoing Webhook이 `!주가 <종목명>` 메시지를 감지
2. **[GitHub Dispatch]** `workflow_dispatch`로 GitHub Actions 실행
3. **[Stock Resolution]** 종목명과 종목코드를 실제 상장사 기준으로 검증 및 보정
4. **[Single-Stock Briefing]** 기술적 지표와 최근 이슈를 요약해 Teams Adaptive Card 전송

---

## ⏰ Automation Schedule

GitHub Actions의 Cron 스케줄러를 활용해 서버 없이 **평일(월~금)**에만 100% 자동으로 작동합니다. (KST 기준)

* **⚡ 실시간 감시 (장중)**: 09:00 ~ 15:00 (매 1시간 간격 실행)
* **🌅 Morning Briefing**: 07:30 (미장 마감 요약 및 국장 프리뷰)
* **🌇 Evening Briefing**: 18:30 (국장 마감 요약 및 미장 프리뷰)
* **⌨️ Teams 온디맨드 조회**: 필요할 때마다 `Teams Stock Command` 워크플로우를 `workflow_dispatch`로 호출

---

## 🚀 Quick Start

1. **GitHub Secrets 설정**
   - `AI_API_KEY`: OpenAI API 키
   - `TEAMS_WEBHOOK_URL`: MS Teams 웹훅 URL

2. **GitHub Pages 활성화**
   - Settings > Pages > Source를 `Deploy from a branch`로 설정
   - Branch를 `gh-pages`로 지정 후 Save

3. **작동 확인**
   - Actions 탭에서 `Realtime Trading Bot` 워크플로우를 **Run workflow**로 수동 실행해 보세요!
   - Actions 탭에서 `Teams Stock Command` 워크플로우에 `stock_query`를 넣고 수동 실행해 보세요!

4. **Teams 명령 연동**
   - Teams Workflow 경로는 [teams-stock-command.md](/Users/junseongkim/Desktop/daily-market-briefing/docs/teams-stock-command.md)를 참고하세요.
   - Power Automate 프리미엄 없이 붙이려면 [teams-outgoing-webhook.md](/Users/junseongkim/Desktop/daily-market-briefing/docs/teams-outgoing-webhook.md)를 참고하세요.

---
Powered by **GitHub Actions & OpenAI**.
