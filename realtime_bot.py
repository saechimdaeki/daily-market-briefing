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

# 환경 변수 세팅 (GitHub Actions의 Secrets에서 주입받음)
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
                
            if len(headlines) >= 15:
                break
                
        return headlines
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")
        return []

def extract_tickers_from_news(headlines):
    """뉴스 헤드라인에서 타겟 종목 추출"""
    if not headlines:
        return []
        
    prompt = f"""
    다음 오늘 증시 관련 뉴스 헤드라인들을 바탕으로, 주가 변동이 클 것으로 예상되는 핵심 종목을 최대 3개만 추출해.
    미국 주식은 티커(예: AAPL), 한국 주식은 종목코드 뒤에 .KS(코스피)나 .KQ(코스닥)를 붙여(예: 005930.KS).
    
    뉴스: {headlines}
    
    응답은 반드시 아래 JSON 배열 포맷만 출력 (마크다운 백틱 등 다른 말 절대 금지):
    [{{"name": "종목명", "ticker": "티커", "reason": "관련 뉴스 핵심 1줄"}}]
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        res_text = response.choices[0].message.content.strip()
        
        # JSON 포맷 마크다운 예외 처리
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
        # 일목균형표(52일) 및 피보나치를 위해 6개월 데이터 확보
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
        
        # 4. 피보나치 되돌림 (최근 6개월 최고/최저 기준)
        recent_high = df['High'].max()
        recent_low = df['Low'].min()
        diff = recent_high - recent_low
        fib_382 = recent_high - diff * 0.382
        fib_500 = recent_high - diff * 0.500
        fib_618 = recent_high - diff * 0.618
        
        # [핵심] 특이점(시그널) 감지 로직
        signals = []
        
        # RSI 시그널
        if current_rsi >= 70: signals.append("🔴 RSI 과매수 (70 이상)")
        elif current_rsi <= 30: signals.append("🟢 RSI 과매도 (30 이하)")
        
        # 볼린저 밴드 시그널
        if current_price >= bb_upper.iloc[-1]: signals.append("🔴 볼린저밴드 상단 돌파 (조정 주의)")
        elif current_price <= bb_lower.iloc[-1]: signals.append("🟢 볼린저밴드 하단 이탈 (반등 기대)")
        
        # 일목균형표 기준선 교차 시그널
        if current_price > kijun_sen.iloc[-1] and df['Close'].iloc[-2] <= kijun_sen.iloc[-2]:
            signals.append("🟢 일목균형표 기준선 상향 돌파 (강세 전환)")
        elif current_price < kijun_sen.iloc[-1] and df['Close'].iloc[-2] >= kijun_sen.iloc[-2]:
            signals.append("🔴 일목균형표 기준선 하향 이탈 (약세 전환)")
            
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
        print(f"지표 계산 실패: {e}")
        return None

def generate_deep_analysis(name, reason, indicators):
    """여러 기술적 지표를 종합한 AI 3줄 브리핑"""
    prompt = f"""
    월스트리트 수석 투자 분석가로서 '{name}' 종목에 대해 정확히 3줄로 요약해.
    
    [현재 데이터 및 기술적 지표]
    - 뉴스 이슈: {reason}
    - 현재가: {indicators['price']:,.2f}
    - 발생한 주요 시그널: {', '.join(indicators['signals'])}
    - 보조지표: RSI({indicators['rsi']:.2f}), 볼린저 상단({indicators['bb_upper']:,.2f}), 볼린저 하단({indicators['bb_lower']:,.2f})
    - 일목균형표 기준선: {indicators['kijun_sen']:,.2f}
    - 피보나치 되돌림 주요 라인: 38.2%({indicators['fib_382']:,.2f}), 50%({indicators['fib_500']:,.2f}), 61.8%({indicators['fib_618']:,.2f})

    [작성 규칙]
    1줄: 뉴스 이슈에 따른 기본적 모멘텀 진단
    2줄: 위 기술적 지표(시그널, 밴드, 되돌림 위치 등)들을 종합한 현재 주가 기술적 평가
    3줄: 단기 대응 전략 (예: 50% 되돌림 지지 확인 후 분할매수, 밴드 상단이므로 차익실현 등)
    """
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "user", "content": prompt}], 
            temperature=0.5
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return "- 분석 불가"

def main():
    print("실시간 시장 감시 시작...")
    headlines = get_finance_news_headlines()
    
    if not headlines: 
        print("뉴스를 가져오지 못했습니다.")
        return
        
    print(f"수집된 핵심 뉴스 {len(headlines)}건 분석 중...")
    target_stocks = extract_tickers_from_news(headlines)
    
    for stock in target_stocks:
        ticker = stock.get('ticker')
        name = stock.get('name')
        reason = stock.get('reason')
        
        indicators = calculate_technical_indicators(ticker)
        if indicators is None: 
            continue
            
        print(f"[{name}] 감지 - 현재가: {indicators['price']:,.0f}, RSI: {indicators['rsi']:.2f}")
        
        # 지표들 중 하나라도 유의미한 시그널(signals)이 발생했을 때만 Teams 전송!
        if len(indicators['signals']) > 0:
            print(f"🚨 [{name}] 강력한 기술적 시그널 발생! 심층 분석 시작...")
            analysis = generate_deep_analysis(name, reason, indicators)
            
            # Teams 카드에 표시할 시그널 텍스트
            signals_text = "\n".join([f"• {sig}" for sig in indicators['signals']])
            
            payload = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard",
                            "version": "1.2",
                            "body": [
                                {
                                    "type": "TextBlock",
                                    "text": f"⚡ 실시간 시장 경고: {name} ({ticker})",
                                    "weight": "Bolder",
                                    "size": "Medium",
                                    "color": "Attention"
                                },
                                {
                                    "type": "FactSet",
                                    "facts": [
                                        {"title": "현재가", "value": f"₩ {indicators['price']:,.2f}"},
                                        {"title": "이슈", "value": reason},
                                        {"title": "기술적 신호", "value": signals_text},
                                        {"title": "볼린저 밴드", "value": f"하단 {indicators['bb_lower']:,.0f} ~ 상단 {indicators['bb_upper']:,.0f}"},
                                        {"title": "일목 기준선", "value": f"₩ {indicators['kijun_sen']:,.0f}"}
                                    ]
                                },
                                {
                                    "type": "TextBlock",
                                    "text": analysis,
                                    "wrap": True,
                                    "separator": True
                                }
                            ]
                        }
                    }
                ]
            }
            try:
                if TEAMS_WEBHOOK_URL:
                    requests.post(TEAMS_WEBHOOK_URL, json=payload)
                    print(f"[{name}] Teams 실시간 알림 전송 완료!")
                else:
                    print("TEAMS_WEBHOOK_URL이 설정되지 않았습니다.")
            except Exception as e:
                print(f"알림 전송 실패: {e}")
        else:
            print(f"[{name}] 특이 시그널 없음. 알림 생략.")

if __name__ == "__main__":
    main()