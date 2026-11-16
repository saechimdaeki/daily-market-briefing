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
* **🎨 GPT Image 네컷 만화**: 매일의 증시 테마를 바탕으로 귀여운 황소와 곰돌이가 등장하는 웹툰을 자동 생성합니다.
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
| **AI Models** | OpenAI GPT-4o-mini (Text/JSON), GPT Image (Image) |
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
  → GPT Image 최종 프롬프트 포맷
  │
  ▼
[🖼️ generate_image]               ← GPT Image API, cover.png 저장
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
│   ├── image_gen.py      # [Node] GPT Image 이미지 생성
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

데일리 브리핑은 Codex cron automation이 이 workspace를 주기적으로 열어 직접 실행합니다.  
기존 GitHub Actions workflow는 장애 대응 또는 비교 실행을 위한 `workflow_dispatch` 수동 백업으로만 유지합니다. (KST 기준)

* **🌅 Morning Briefing**: 평일 09:20 (미장 마감 요약 및 국장 프리뷰)
* **🌇 Evening Briefing**: 평일 16:00 (국장 마감 요약 및 미장 프리뷰)
* **⚡ 실시간 감시 (장중)**: 기존 GitHub Actions `realtime.yml` 유지
* **🏢 AI 트레이딩 데스크**: 로컬 cron으로 월~금 09:30 KST에 `trading_desk.py` 실행

* **⌨️ Teams 온디맨드 조회**: 필요할 때마다 `Teams Stock Command` 워크플로우를 `workflow_dispatch`로 호출

트레이딩 데스크는 Yahoo Finance 종목별 RSS에서 한국·미국 지수 및 주요 종목 관련 뉴스를 수집합니다. 최근 24시간을 사용하되, 월요일에는 주말을 포함한 최근 72시간을 사용합니다. 요청 제한(429)이 발생하면 추가 요청을 멈추고, 최신 뉴스가 없으면 분석·저널 저장·Teams 전송을 중단합니다. 야후의 한국 종목 뉴스는 국내 전체 종목을 포괄하지 않을 수 있습니다.

복기는 종목별 최신 과거 계획을 한 번씩 표시하며, 빈 계획은 복기 대상을 밀어내지 않습니다. 일별 종가로 확인한 손절·목표 도달 결과와 평가 가격을 저장해 이후 반등에도 종료 결과를 유지합니다. 실제 주문 체결 기록은 아닙니다. 진행 중인 계획은 중복 신규 추천에서 제외하고, 손절한 계획의 손절가를 회복하기 전에는 재진입을 보류합니다. 이후 재추천에는 `재진입 계획` 표시와 한국어 사유가 필요합니다. 종목명·뉴스 요약·설명은 한국어로 표시합니다.

### Codex runbook

로컬 텍스트 분석은 실행 환경의 `PATH`에 있는 Claude Code CLI와 Codex CLI를 사용합니다. Claude 로그인 또는 `CLAUDE_CODE_OAUTH_TOKEN`으로 Claude를 먼저 실행하고, Claude를 사용할 수 없으면 Codex에 저장된 로그인으로 전환합니다. GitHub Actions는 기존 Claude CLI 구성을 사용합니다.

Codex automation은 아래 작업을 순서대로 수행합니다.

1. `.env`의 `AI_API_KEY`, `TEAMS_WEBHOOK_URL`을 로드한다.
2. `python main.py`를 실행해 시장 데이터 수집, GPT 분석, GPT Image 생성, HTML 렌더링, Teams 알림을 수행한다.
3. `public/index.html`, `public/cover.png`, `public/daily_news_digest.json` 변경 결과를 확인한다.
4. 필요하면 기존 GitHub Pages 배포 방식과 동일하게 `public/` 결과물을 `gh-pages`에 반영한다.

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


### 트레이딩 데스크 대시보드

`public/performance.html`에서 7일·30일·전체 기간, 국내·미국, 상태별로 계획을 조회합니다.
계획 생성일 기준으로 목표 도달률·손절률·종료 계획 평균 손익과 전략별 성과를 집계합니다.
가상 체결 근거가 있는 종료 계획만 성과에 포함하며, 미체결·평가 실패·이전 평가 방식은 제외합니다.
재진입 전후 기록을 모두 보존하고, 보유 중 평가 손익과 종료 손익을 구분합니다.
수익률은 체결가 대비 단순 수익률이며 계좌 수익률이 아닙니다. 수수료·슬리피지·환율은 미반영입니다.

트레이딩 데스크의 저널 저장 후, 또는 데일리 브리핑 렌더링 시 자동으로 갱신합니다.
브리핑 화면의 **트레이딩 데스크** 링크로 이동할 수 있습니다.
시세 조회·AI 호출·Teams 전송 없이 저장된 저널로만 다시 생성하려면:

```sh
python performance_dashboard.py --journal desk_journal.json --output-dir public
```

`performance.html`과 `performance.json`은 기존 `public/` GitHub Pages 배포에 함께 포함됩니다.
저널 원본은 `DESK_JOURNAL_PATH`, 출력 위치는 `OUTPUT_DIR`로 변경할 수 있습니다.
생성 시각은 페이지에 표시되며, 이 페이지 자체가 실시간으로 시세를 조회하지는 않습니다.


공개 배포 승인에 따라 기본 활성화되어, 평일 09:30·15:00 KST의 기존 cron 실행마다 저널 → 성과 HTML/JSON 생성 →
`gh-pages` 반영 → Teams 전송 순서로 동작합니다. Teams 카드 하단의 **트레이딩 데스크 보러가기**로
`https://saechimdaeki.github.io/daily-market-briefing/performance.html`을 엽니다.
데일리 브리핑 Teams 카드에도 동일한 버튼을 제공합니다.
Pages 배포는 `performance.html`·`performance.json` 두 파일만 갱신하며 기존 브리핑 파일은 보존합니다.
GitHub Pages의 반영에는 시간이 걸릴 수 있고 화면에 데이터 생성 시각을 표시합니다.
배포 실패 시 분류된 오류를 로그에 남기고 Teams 전송은 계속합니다. 카드에는 웹 갱신 지연을 표시합니다. 동일 커밋의 push 오류(128)·응답 지연은 1회 재시도하며 강제 push는 하지 않습니다.
공개 배포는 기본 활성입니다. `DESK_PUBLISH_DASHBOARD=0`으로 비활성화할 수 있습니다. Teams 웹훅이 없는 로컬 실행도 배포하지 않습니다.
버튼 주소는 `TRADING_DESK_URL` 또는 `GITHUB_PAGES_URL`로 변경할 수 있습니다.
저장된 대시보드만 수동 배포하려면 `python dashboard_delivery.py`를 실행합니다.


### 장세별 전술 후보와 포지션 관리

뉴스 종목 외에 SOXX·SPY의 전일/5일 수익률과 20일선으로 하락 대응을 비교합니다.
SOXS(반도체 일일 -3배)·SH(S&P500 일일 -1배)는 해당 대용 지표의 전일·5일 하락 및 20일선 하회 시에만 후보가 됩니다.
SOXX는 SOXS 기초지수와 동일하지 않은 방향 확인용 대용 지표입니다.
시장 약세 때 PG·KO 중 5일 상승·20일선 상회·시장 대비 상대강도를 확인한 방어주도 비교합니다.
지표는 최소 20개 종가와 4일 이내 시점을 요구하며, 실패/누락 시 인버스 후보를 만들어내지 않습니다.
매수 추천을 강제하지 않고 현금 대기를 유지할 수 있습니다. 미지원 레버리지 상품은 뉴스 경로로 우회 편입하지 않습니다.

코드로 강제하는 정책값(최적화나 수익 보장을 뜻하지 않음):
- SOXS 최대 5%, SH 최대 10%, 인버스 전체 최대 10%, PG·KO 종목당 최대 15%.
- 기존 보유·진입 대기 비중을 장세별 총 비중 한도에 포함합니다.
- 인버스 손절 기준 손실 예산은 종목당 계획 자산의 0.5% 이내이며 갭 손실을 보장 제한하지 않습니다.
- 인버스 과열(RSI 65 이상), 기초시장 약세 미확인, 목적/무효화 조건 누락이면 보류합니다.
- 관련 롱 보유 시 인버스는 헤지 목적이어야 하며 명목 배수 기준 헤지 크기를 제한합니다.
- 인버스와 상충하는 신규 롱 확대를 보류하며, 인버스의 손익비 2:1과 추격 진입 금지를 검증합니다.
- 인버스는 미국 정규장만 평가하며 첫 세션 마지막 5분봉 종가로 시간 청산, 미진입이면 취소합니다.
  종료 시점 데이터가 없으면(조기 폐장/결측 포함) 다음 세션 시세로 수익을 만들어내지 않고 평가 확인 필요로 남깁니다.
  이 작업은 주문 실행이나 장중 실시간 청산 서비스가 아니며, 다음 cron에서 관측된 봉을 기준으로 기록합니다.

Teams와 웹에 포지션 유형·목적·보유 기준·무효화 조건을 표시하고,
다음 데스크 실행부터 장세 근거와 후보별 통과/보류 이유를 함께 저장합니다.
상품 구조 출처: [Direxion SOXS](https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs),
[ProShares SH](https://www.proshares.com/our-etfs/leveraged-and-inverse/sh).


### 데이터·일정 검증과 시장 판단 (1·2단계)

`prepare_context`가 뉴스보다 먼저 독립적으로 시장 근거를 수집합니다. 뉴스 수집 실패 시에도
검증된 시장/섹터 후보와 현금 대기 판단을 계속하며, 뉴스를 이용한 후보 추출만 생략합니다.
미국 상승장에서 상대강도가 강한 섹터 ETF도 뉴스와 독립적으로 최대 2개 심사합니다.

- NYSE·KRX 거래소 캘린더로 휴장·서머타임·조기 폐장과 마지막 완료 거래일을 계산합니다.
- Yahoo 1년 조정 일봉에서 미완료 봉을 제외하고 최소 60개 완료 봉, 시간대·중복·가격·거래량을 검증합니다.
- 20/60일선과 5일 추세로 국내/미국 장세를 **코드로** 분리 판정합니다. 200일선·ATR·상대 거래량도 기록합니다.
- SOXX/XLK/XLF/XLP/XLV/XLU/XLE의 SPY 대비 5일 상대강도, RSP·IWM 대비를 기록합니다.
  이는 ETF 기반 확산 대용 지표이며 전체 종목의 상승/하락 수나 이동평균 상회 비율이 아닙니다.
- BLS 공식 iCalendar에서 CPI·PPI·고용, 연준 공식 페이지에서 FOMC 종료일을 확인합니다.
  FOMC는 발표 시각을 추정하지 않고 종료일 전체를 보수적으로 반영합니다.
- 주요 발표 접근(24시간) 및 발표 직후(30분), 개별주 실적 전후 24시간은 신규 계획을 보류합니다.
  Yahoo 실적은 예상 일정으로 표시하고 누락 시 확인된 일정이 없다고 단정하지 않습니다.
- 필수 가격/장세가 미확인이거나 확인된 주요 발표가 임박하면 LLM이 신규 진입을 통과시킬 수 없습니다. ETF는 개별 기업 실적 심사 대상에서 제외합니다.
- 기존 계획은 데이터 실패로 삭제하지 않으며 복기를 계속합니다. 인버스 시간 청산은 실제 거래소 폐장 시각을 사용합니다.

데이터 근거·확인 시각·시장 상태·섹터 비교·일정 수집 상태·종목별 보류 사유를 저널/Teams/웹에 남깁니다.
BLS 등 일정 소스가 HTTP 403 등으로 접근 불가하면 확인 범위 제한을 기록하고 시장 데이터 기반 심사를 계속합니다. 조회 장애만으로 신규 계획을 일괄 보류하지 않으며, 오류를 이벤트 없음으로 대체하지 않습니다.
현재 범위는 미국 주요 거시 발표와 Yahoo 기업 실적 예상치입니다. 국내 정책/기업행사 전체 일정, 실시간 호가·스프레드,
전체 종목 시장 폭, 장중 상시 감시, 단계 3~5의 전체 상태관리·전략 성과 검증은 아직 구현 범위가 아닙니다.
기존 09:30·15:00 KST cron은 유지하고 완료 일봉 기반 계획·관측 시세 평가로 명시합니다.

실행 환경 의존성은 `requirements.txt`에 고정했습니다. 기존 cron의 Python 환경에서 설치합니다.
수집 근거만 별도로 확인해 HTML을 생성할 때는 `performance_dashboard.py --context <수집 JSON 경로>`를 사용할 수 있습니다.
이 옵션은 저널이나 추천을 생성하지 않습니다.

운용 결과는 저널 옆 `desk_journal.latest_state.json`에도 로컬 저장하여 AI 재호출 없이 전송을 복구할 수 있습니다.
cron 로그에는 실행 시작/완료 시각이 기록됩니다. Git 오류는 인증/접근 권한·연결/DNS·동시 배포 충돌로 분류하며 비밀값은 출력하지 않습니다.
