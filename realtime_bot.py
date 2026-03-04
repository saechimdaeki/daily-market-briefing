import os
import json
import requests
from bs4 import BeautifulSoup
import yfinance as yf
from openai import OpenAI
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 환경 변수 세팅
OPENAI_API_KEY = os.environ.get("AI_API_KEY") 
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

def get_finance_news_headlines():
    """네이버 금융 '주요 뉴스'를 크롤링하여 핵심 기사 추출"""
    url = "https://finance.naver.com/news/mainnews.naver"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    headlines = []
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        response.encoding = 'euc-kr' 
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for a_tag in soup.select('.articleSubject a'):
            title = a_tag.text.strip()
            if title and title not in headlines:
                headlines.append(title)
                
            if len(headlines) >= 20: # 더 많은 뉴스를 확보
                break
                
        return headlines
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")
        return []

def extract_tickers_from_news(headlines):
    """뉴스 헤드라인에서 타겟 종목 추출 (정밀도 향상)"""
    if not headlines:
        return []
        
    prompt = f"""
    다음 오늘 증시 관련 뉴스 헤드라인들을 바탕으로, 주가 변동이 클 것으로 예상되는 핵심 기업을 **최대 7개** 추출해.
    
    [매우 중요한 규칙]
    1. '한화운용', 'KB자산운용' 같은 펀드/ETF 운용사 이름은 절대 추출하지 마. 실제 이슈가 있는 개별 상장 기업명(예: SK하이닉스, 테슬라 등)을 정확히 찾아내야 해.
    2. 미국 주식은 티커(예: AAPL), 한국 주식은 종목코드 뒤에 .KS(코스피)나 .KQ(코스닥)를 정확히 매칭해(예: 000660.KS).
    
    뉴스: {headlines}
    
    응답은 반드시 아래 JSON 배열 포맷만 출력 (마크다운 백틱 금지):
    [{{"name": "정확한 상장기업명", "ticker": "티커", "reason": "관련 뉴스 핵심 1줄 요약"}}]
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1 # 정확도를 위해 온도 낮춤
        )
        res_text = response.choices[0].message.content.strip()
        
        if res_text.startswith("```json"): 
            res_text = res_text[7:-3]
        elif res_text.startswith("```"): 
            res_text = res_text[3:-3]
            
        return json.loads(res_text.strip())
    except Exception as e:
        print(f"AI 추출 실패: {e}")
        return []

def calculate_technical_indicators(ticker):
    """RSI, 볼린저 밴드, 일목균형표, 피보나치 등 종합 지표 계산"""
    try:
        df = yf.Ticker(ticker).history(period="6mo")
        if df.empty or len(df) < 52: 
            return None
            
        current_price = df['Close'].iloc[-1]
        
        # 1. RSI (14일)
        delta = df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        
        # 2. 볼린저 밴드 (20일 이평, 2 표준편차)
        sma_20 = df['Close'].rolling(window=20).mean()
        std_20 = df['Close'].rolling(window=20).std()
        bb_upper = sma_20 + (std_20 * 2)
        bb_lower = sma_20 - (std_20 * 2)
        
        # 3. 일목균형표 (전환선 9일, 기준선 26일)
        high_9 = df['High'].rolling(window=9).max()
        low_9 = df['Low'].rolling(window=9).min()
        tenkan_sen = (high_9 + low_9) / 2
        
        high_26 = df['High'].rolling(window=26).max()
        low_26 = df['Low'].rolling(window=26).min()
        kijun_sen = (high_26 + low_26) / 2
        
        # 4. 피보나치 되돌림
        recent_high = df['High'].max()
        recent_low = df['Low'].min()
        diff = recent_high - recent_low
        fib_382 = recent_high - diff * 0.382
        fib_500 = recent_high - diff * 0.500
        fib_618 = recent_high - diff * 0.618
        
        signals = []
        
        if current_rsi >= 70: signals.append("🔴 RSI 과매수 (조정 주의)")
        elif current_rsi <= 30: signals.append("🟢 RSI 과매도 (반등 기회)")
        
        if current_price >= bb_upper.iloc[-1]: signals.append("🔴 볼린저밴드 상단 돌파 (차익 실현 고려)")
        elif current_price <= bb_lower.iloc[-1]: signals.append("🟢 볼린저밴드 하단 이탈 (단기 지지선)")
        
        if current_price > kijun_sen.iloc[-1] and df['Close'].iloc[-2] <= kijun_sen.iloc[-2]:
            signals.append("🟢 일목균형표 기준선 상향 돌파 (추세 강세)")
        elif current_price < kijun_sen.iloc[-1] and df['Close'].iloc[-2] >= kijun_sen.iloc[-2]:
            signals.append("🔴 일목균형표 기준선 하향 이탈 (추세 약세)")
            
        return {
            "price": current_price,
            "rsi": current_rsi,
            "bb_upper": bb_upper.iloc[-1],
            "bb_lower": bb_lower.iloc[-1],
            "kijun_sen": kijun_sen.iloc[-1],
            "fib_382": fib_382,
            "fib_500": fib_500,
            "fib_618": fib_618,
            "signals": signals
        }
    except Exception as e:
        print(f"[{ticker}] 지표 계산 실패: {e}")
        return None

def generate_deep_analysis(name, reason, indicators):
    """구조화된 3줄 요약 강제 적용"""
    prompt = f"""
    월스트리트 수석 투자 분석가로서 '{name}' 종목에 대해 분석해.
    
    - 이슈: {reason}
    - 현재가: {indicators['price']:,.2f}
    - 시그널: {', '.join(indicators['signals']) if indicators['signals'] else '특이사항 없음'}
    - RSI: {indicators['rsi']:.2f} / 볼린저 상단: {indicators['bb_upper']:,.0f} / 볼린저 하단: {indicators['bb_lower']:,.0f}
    - 일목기준선: {indicators['kijun_sen']:,.0f} / 피보나치 50%: {indicators['fib_500']:,.0f}

    [필수 작성 규칙]
    하나의 단락으로 절대 뭉치지 마. 반드시 아래 형식대로 **3줄로 분리하고, 각 줄 앞에 '• ' 기호를 붙여서 작성**해.
    • 1줄 (모멘텀): 이슈에 기반한 모멘텀 진단
    • 2줄 (기술적 평가): 밴드, 지지선, RSI 등을 종합한 현재 주가 평가
    • 3줄 (대응 전략): 단기 대응 가이드
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "user", "content": prompt}], 
            temperature=0.3
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return "• 분석을 불러오는 중 오류가 발생했습니다."

def main():
    print("실시간 시장 감시 시작...")
    headlines = get_finance_news_headlines()
    
    if not headlines: 
        print("뉴스를 가져오지 못했습니다.")
        return
        
    print("AI 타겟 종목 추출 중...")
    target_stocks = extract_tickers_from_news(headlines)
    
    # 여러 종목을 한 번에 모아서 보낼 리스트 준비
    teams_body_elements = [
        {
            "type": "TextBlock",
            "text": "⚡ 실시간 특징주 모니터링",
            "weight": "Bolder",
            "size": "Large",
            "color": "Accent"
        }
    ]
    
    alert_triggered = False
    
    for stock in target_stocks:
        ticker = stock.get('ticker')
        name = stock.get('name')
        reason = stock.get('reason')
        
        indicators = calculate_technical_indicators(ticker)
        if indicators is None: 
            continue
        
        # 시그널이 발생한 종목만 필터링하여 카드에 추가
        if len(indicators['signals']) > 0:
            alert_triggered = True
            print(f"🚨 [{name}] 강력한 기술적 시그널 발생! 리포트 작성 중...")
            
            analysis = generate_deep_analysis(name, reason, indicators)
            # 팀즈에서 줄바꿈이 정상 작동하도록 \n을 \n\n으로 교체
            analysis_formatted = analysis.replace('\n', '\n\n')
            
            signals_text = "\n\n".join([f"• {sig}" for sig in indicators['signals']])
            
            teams_body_elements.extend([
                {
                    "type": "TextBlock",
                    "text": f"🎯 {name} ({ticker})",
                    "weight": "Bolder",
                    "size": "Medium",
                    "spacing": "Medium",
                    "color": "Good"
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "현재가", "value": f"₩ {indicators['price']:,.2f}"},
                        {"title": "주요 이슈", "value": reason},
                        {"title": "기술적 신호", "value": signals_text},
                        {"title": "볼린저 밴드", "value": f"하단 {indicators['bb_lower']:,.0f} ~ 상단 {indicators['bb_upper']:,.0f}"},
                        {"title": "RSI / 기준선", "value": f"{indicators['rsi']:.2f} / ₩ {indicators['kijun_sen']:,.0f}"}
                    ]
                },
                {
                    "type": "TextBlock",
                    "text": analysis_formatted,
                    "wrap": True,
                    "spacing": "Small"
                },
                {
                    "type": "TextBlock",
                    "text": " ", # 구분선 역할
                    "wrap": True,
                    "separator": True
                }
            ])

    # 감지된 종목이 1개라도 있을 때만 묶어서 한 번에 전송
    if alert_triggered and TEAMS_WEBHOOK_URL:
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": teams_body_elements
                    }
                }
            ]
        }
        try:
            requests.post(TEAMS_WEBHOOK_URL, json=payload)
            print("Teams 통합 알림 전송 완료!")
        except Exception as e:
            print(f"알림 전송 실패: {e}")
    else:
        print("현재 강력한 시그널이 발생한 종목이 없습니다.")

if __name__ == "__main__":
    main()