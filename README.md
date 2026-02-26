# 📈 AI Daily Market Briefing (AI 증시 브리핑 자동화 시스템)

매일 아침과 저녁, 글로벌 증시 데이터(KOSPI, KOSDAQ, S&P 500, Dow Jones)를 수집하여 **AI가 팩트 기반으로 시황을 분석**하고, **귀여운 4컷 만화**와 함께 MS Teams 및 웹 대시보드로 자동 발행하는 서버리스 파이프라인입니다.

## ✨ Key Features

* **📊 팩트 폭격 AI 분석:** `yfinance`로 스크래핑한 정확한 등락률 데이터를 프롬프트에 주입하여, LLM(GPT-4o-mini)의 할루시네이션(거짓 정보 생성)을 원천 차단했습니다.
* **🎨 DALL-E 3 네컷 만화:** 매일의 증시 테마를 바탕으로 귀여운 황소와 곰돌이가 등장하는 2x2 네컷 웹툰을 자동 생성합니다. (만화적 재미를 더하는 영어 말풍선 포함!)
* **💻 프리미엄 핀테크 대시보드:** Jinja2 템플릿 엔진을 활용하여, 요즘 IT 스타트업 스타일의 깔끔하고 세련된 정적 웹페이지(HTML)를 렌더링합니다.
* **🚀 100% 자동화 (Serverless):** GitHub Actions의 Cron 스케줄러를 활용해 평일 아침/저녁 지정된 시간에 자동으로 스크립트가 실행되고 웹페이지가 배포됩니다.
* **🔔 MS Teams 실시간 연동:** 생성된 요약본과 이미지를 MS Teams Webhook을 통해 지정된 채널로 즉시 발송합니다.

<br>

## 📸 Screenshots

### 1. MS Teams Alert
*(여기에 팀즈로 알람 온 캡처 이미지를 넣어주세요. 예: `![Teams Alert](./docs/teams-alert.png)`)*

### 2. Premium Web Dashboard
*(여기에 웹페이지 전체 화면 캡처 이미지를 넣어주세요. 예: `![Web Dashboard](./docs/web-dashboard.png)`)*

<br>

## 🛠 Tech Stack

* **Language:** Python 3.10
* **AI Models:** OpenAI GPT-4o-mini (Text), DALL-E 3 (Image)
* **Data Source:** `yfinance` (Yahoo Finance API)
* **Template Engine:** `Jinja2`
* **CI/CD & Hosting:** GitHub Actions, GitHub Pages
* **Notification:** MS Teams Incoming Webhook

<br>

## ⚙️ How it Works (Architecture)

1.  **[Data Collection]** Python 스크립트가 `yfinance`를 통해 KOSPI, KOSDAQ, S&P 500, Dow 지수의 어제/오늘 종가를 가져와 등락률을 계산합니다.
2.  **[AI Analysis]** 수집된 팩트 데이터를 GPT-4o-mini에 전달하여 3~5줄의 상세 마켓 브리핑과 핵심 헤드라인을 추출합니다.
3.  **[Image Generation]** 추출된 헤드라인을 바탕으로 DALL-E 3가 2x2 그리드 형태의 귀여운 4컷 만화를 생성합니다.
4.  **[Web Rendering]** 수집된 데이터와 AI 결과물들을 `Jinja2` 템플릿에 주입하여 정적 HTML(`public/index.html`)을 생성합니다.
5.  **[Notification & Deploy]** 완성된 브리핑을 MS Teams로 발송하고, GitHub Pages를 통해 전 세계 어디서든 볼 수 있도록 자동 배포합니다.

<br>

## ⏰ Automation Schedule

GitHub Actions를 통해 주말을 제외한 **평일(월~금)**에만 작동하도록 설계되었습니다. (KST 기준)

* **🌅 Morning Briefing:** 오전 07:30 (미장 마감 및 국장 프리뷰)
* **🌇 Evening Briefing:** 오후 18:30 (국장 마감 및 미장 프리뷰)

<br>

## 🚀 Quick Start (설치 및 실행 방법)

이 프로젝트를 포크(Fork)하여 본인만의 브리핑 봇을 만들 수 있습니다.

**1. 준비물**
* OpenAI API Key (`sk-proj-...`)
* MS Teams Webhook URL

**2. GitHub Secrets 설정**
레포지토리의 `Settings` > `Secrets and variables` > `Actions`에 다음 환경변수를 등록합니다.
* `AI_API_KEY` : OpenAI API 키
* `TEAMS_WEBHOOK_URL` : (선택) MS Teams 웹훅 URL

**3. GitHub Pages 활성화**
* 레포지토리 `Settings` > `Pages` 이동
* Source를 `Deploy from a branch`로 설정하고, Branch를 `gh-pages` / `(root)`로 지정 후 Save.

**4. 수동 실행 테스트**
* `Actions` 탭으로 이동하여 `Daily Market Briefing Automation` 워크플로우를 수동으로 실행(Run workflow)해 보세요!

<br>

---
*Powered by GitHub Actions & OpenAI. Designed for automated daily insights.*