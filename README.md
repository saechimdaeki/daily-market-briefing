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
<img width="311" height="623" alt="daily_alert" src="https://github.com/user-attachments/assets/43a93c4a-0ca9-4dee-8356-20d4a2c9cec3" />

### 3. Premium Web Dashboard
GitHub Pages로 자동 배포되는 데일리 리포트 웹페이지
<img width="436" height="803" alt="web_dashboard" src="https://github.com/user-attachments/assets/79fcc5fd-976a-4b6f-8c16-da416655f46b" />

---

## 🛠 Tech Stack

- **Language:** Python 3.10
- **AI Models:** OpenAI GPT-4o-mini (Text Analysis), DALL-E 3 (Image Generation)
- **Data & Scraping:** yfinance, pandas, BeautifulSoup4
- **Template Engine:** Jinja2
- **CI/CD & Hosting:** GitHub Actions, GitHub Pages
- **Notification:** MS Teams (Incoming Webhook & Adaptive Cards)

---

## ⚙️ How it Works (Two-Track Architecture)

### Track A: Real-time Monitor (`realtime_bot.py`)
1. **[Data Ingestion]** 네이버 금융 메인 뉴스 헤드라인 실시간 크롤링
2. **[Target Extraction]** GPT가 기사를 분석해 수혜/타격 예상 핵심 상장사 동적 추출
3. **[Quant Analysis]** `pandas`로 6개월치 데이터를 분석해 RSI, MACD, 볼린저 밴드 등 시그널 감지
4. **[AI Briefing]** 강력한 시그널이 발생한 종목만 추려내어 AI 심층 브리핑 생성 후 Teams 전송

### Track C: Teams Stock Command (`teams_stock_command.py`)
1. **[Command Trigger]** Teams Workflow 또는 Teams Outgoing Webhook이 `!주가 <종목명>` 메시지를 감지
2. **[GitHub Dispatch]** `workflow_dispatch`로 GitHub Actions 실행
3. **[Stock Resolution]** 종목명과 종목코드를 실제 상장사 기준으로 검증 및 보정
4. **[Single-Stock Briefing]** 기술적 지표와 최근 이슈를 요약해 Teams Adaptive Card 전송

### Track B: Daily Dashboard (`main.py`)
1. **[Data Collection]** 글로벌 주요 4대 지수 종가 및 등락률 계산
2. **[AI Summary & Comic]** 지수 기반 시황 요약 및 DALL-E 3 네컷 만화 생성
3. **[Web Rendering]** HTML 템플릿에 주입 후 `public/index.html` 생성
4. **[Deploy & Alert]** GitHub Pages 배포 및 Teams 데일리 브리핑 발송

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
