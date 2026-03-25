import os
import json
import re
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


def _strip_llm_json_fence(text):
    t = (text or "").strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    return t.strip()


def _parse_model_json_loose(text):
    """
    모델 출력을 dict 또는 list로 파싱. json_object 모드가 실패하거나
    레거시 배열만 온 경우 보조 처리.
    """
    raw = _strip_llm_json_fence(text)
    try:
        data = json.loads(raw)
        return data
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("모델 응답을 JSON으로 파싱할 수 없음")


def normalize_company_name(name):
    if not name:
        return ""
    normalized = re.sub(r"\(주\)|주식회사|\s+", "", str(name))
    return re.sub(r"[^0-9A-Za-z가-힣]", "", normalized).lower()

def get_korean_stock_code(ticker):
    match = re.fullmatch(r"(\d{6})\.(KS|KQ)", str(ticker or "").upper())
    if not match:
        return None
    return match.group(1)


def is_korean_equity_ticker(ticker):
    return get_korean_stock_code(ticker) is not None


def normalize_us_ticker_for_yf(ticker):
    """yfinance 호환: BRK.B → BRK-B 등"""
    t = str(ticker or "").strip().upper()
    return t.replace(".", "-")


def resolve_us_listed_equity(name, ticker):
    """
    나스닥·NYSE 등 미국 상장 여부를 yfinance로 확인하고,
    공식 표시명·정규 티커를 반환. 실패 시 None (할루시네이션 방지로 제외).
    """
    yf_symbol = normalize_us_ticker_for_yf(ticker)
    if not yf_symbol or not re.match(r"^[A-Z0-9.\-]+$", yf_symbol):
        return None
    if re.fullmatch(r"[0-9]+", yf_symbol):
        return None
    try:
        stock = yf.Ticker(yf_symbol)
        hist = stock.history(period="1mo")
        if hist.empty:
            return None
        info = getattr(stock, "info", None) or {}
        long_name = (info.get("longName") or info.get("shortName") or "").strip()
        display_name = long_name or (name or "").strip() or yf_symbol
        canonical = (info.get("symbol") or yf_symbol).strip().upper()
        return {"name": display_name, "ticker": canonical}
    except Exception as e:
        print(f"[{ticker}] 미국 종목 검증 실패: {e}")
        return None


def format_money(value, market):
    if market == "US":
        return f"$ {value:,.2f}"
    return f"₩ {value:,.2f}"

def fetch_company_name_by_code(code):
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'euc-kr'
        soup = BeautifulSoup(response.text, 'html.parser')

        title_text = soup.title.text.strip() if soup.title and soup.title.text else ""
        if title_text:
            return title_text.split(":")[0].strip()

        company_anchor = soup.select_one(".wrap_company h2 a")
        if company_anchor:
            return company_anchor.get_text(strip=True)
    except Exception as e:
        print(f"[{code}] 종목명 조회 실패: {e}")
    return None

def resolve_market_suffix(code):
    for suffix in ("KS", "KQ"):
        try:
            df = yf.Ticker(f"{code}.{suffix}").history(period="1mo")
            if not df.empty:
                return suffix
        except Exception:
            continue
    return None

def search_korean_stock_by_name(name):
    if not name:
        return None

    url = "https://finance.naver.com/search/searchList.naver"
    headers = {'User-Agent': 'Mozilla/5.0'}
    normalized_target = normalize_company_name(name)

    try:
        response = requests.get(url, params={"query": name}, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'euc-kr'
        soup = BeautifulSoup(response.text, 'html.parser')

        candidates = []
        for anchor in soup.select('a[href*="/item/main.naver?code="]'):
            href = anchor.get("href", "")
            match = re.search(r"code=(\d{6})", href)
            candidate_name = anchor.get_text(strip=True)
            if not match or not candidate_name:
                continue
            candidates.append({
                "name": candidate_name,
                "code": match.group(1),
            })

        if not candidates:
            return None

        exact_candidate = next(
            (candidate for candidate in candidates if normalize_company_name(candidate["name"]) == normalized_target),
            candidates[0],
        )
        suffix = resolve_market_suffix(exact_candidate["code"])
        if not suffix:
            return None

        return {
            "name": exact_candidate["name"],
            "ticker": f'{exact_candidate["code"]}.{suffix}',
        }
    except Exception as e:
        print(f"[{name}] 종목 검색 실패: {e}")
        return None

def validate_and_correct_stock(name, ticker):
    ticker_raw = str(ticker or "").strip()
    code = get_korean_stock_code(ticker_raw)
    if code:
        official_name = fetch_company_name_by_code(code)
        if official_name and normalize_company_name(official_name) == normalize_company_name(name):
            return {"name": official_name, "ticker": ticker_raw, "market": "KR"}

        corrected = search_korean_stock_by_name(name)
        if corrected:
            print(f"종목 보정: {name} {ticker_raw} -> {corrected['name']} {corrected['ticker']}")
            corrected["market"] = "KR"
            return corrected

        if official_name:
            print(f"종목 불일치 감지: 요청={name}({ticker_raw}), 실제={official_name}. 보정 실패로 원본 유지")
        return {"name": name, "ticker": ticker_raw, "market": "KR"}

    if re.fullmatch(r"\d{6}", ticker_raw):
        suffix = resolve_market_suffix(ticker_raw)
        if suffix:
            return validate_and_correct_stock(name, f"{ticker_raw}.{suffix}")
        print(f"한국 6자리 코드 시장 확인 실패(제외): {ticker_raw}")
        return None

    resolved = resolve_us_listed_equity(name, ticker_raw)
    if resolved:
        resolved["market"] = "US"
        return resolved

    print(f"미국/기타 티커 검증 실패(제외): name={name!r} ticker={ticker_raw!r}")
    return None

def validate_target_stocks(target_stocks):
    validated = []
    seen = set()

    for stock in target_stocks:
        corrected = validate_and_correct_stock(stock.get("name"), stock.get("ticker"))
        if not corrected:
            continue
        corrected["reason"] = stock.get("reason")

        dedupe_key = (corrected.get("name"), corrected.get("ticker"))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        validated.append(corrected)

    return validated

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
                
            if len(headlines) >= 45:
                break
                
        return headlines
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")
        return []

def extract_tickers_from_news(headlines):
    """뉴스 헤드라인에서 타겟 종목 추출 (강제성 부여)"""
    if not headlines:
        return []
        
    prompt = f"""
    다음 오늘 증시 관련 뉴스 헤드라인들을 분석해서, 주가 변동이 예상되는 핵심 기업을 **최소 12개에서 최대 20개**까지 추출해.
    특정 기업 하나만 추출하고 멈추면 안 됨. 한국·미국 등 **서로 다른 섹터·지역**을 골고루 포함해 다양하게 찾아야 함.

    [종목명-티커 매칭 규칙 (할루시네이션 방지)]
    0. **추출 대상: 현재 코스피/코스닥/나스닥/NYSE 등에 이미 상장되어 실거래되는 종목만**. 미상장·IPO 예정 기업은 절대 포함하지 말 것.
    1. **뉴스에 나온 표현과 실제 상장 종목을 정확히 1:1로 매칭**해야 함. 비슷한 이름이라도 다른 종목이면 절대 혼동 금지.
    2. **한국 주식: 보통주 vs 우선주 구분 필수**
       - 삼성전자 = 005930.KS (보통주) | 삼성전자우 = 005935.KS (우선주). 뉴스에 "삼성전자"만 나오면 005930.KS만 사용. "우"가 없으면 우선주 티커(005935 등) 사용 금지.
       - 현대차 = 005380.KS | 현대차우 = 005387.KS 등 동일 원칙 적용.
    3. **복합·약어 표현은 구성 종목으로 분리해서 추출**
       - "삼전닉스" = 삼성전자(005930.KS) + SK하이닉스(000660.KS). 삼전닉스는 삼성전자우(005935.KS)가 아님. 반드시 005930.KS, 000660.KS 두 종목으로 각각 추출.
       - "삼성계열", "반도체 빅3" 등은 언급된 구체적 회사명만 추출하고, 각각 정확한 티커 부여.
    4. **자주 혼동되는 한국 종목 참고**
       - 삼성전자: 005930.KS | 삼성전자우: 005935.KS
       - 삼성SDI: 006400.KS (전지) | SK하이닉스: 000660.KS (메모리)
       - 추출한 name과 ticker 쌍은 위 표와 일치해야 함.
    5. **이미 상장된 종목만 추출** (가장 중요). 아직 상장되지 않은 기업은 절대 추출하지 말 것.
       - "IPO 예정", "상장 예정", "다음 주자", "공모 예정", "상장 준비", "코스닥/코스피 상장 예정" 등으로 **앞으로 상장할 회사**가 나오면 그 회사는 제외. 해당 뉴스에서 이미 상장된 다른 기업만 추출.
       - 예: "아이엠바이오로직스가 다음 주자로 기대" → 아이엠바이오로직스는 아직 비상장이므로 추출 금지. 티커를 붙이거나 다른 상장 종목 코드를 억지로 매칭하지 말 것.
    6. 펀드/운용사('한화운용', 'KB자산운용' 등)는 제외. 상장된 **개별 주식**만 추출.
    7. **미국 주식**: 나스닥/NYSE 등 미국 본장 상장만. 티커는 **정확한 야후 파이낸스 심볼** 형태로만 (예: AAPL, MSFT, NVDA, GOOGL, AMZN, TSLA, META). OTC·핑크시트는 뉴스에 명시된 경우에만, 불확실하면 제외.
    8. **한국 주식**: 반드시 6자리코드+.KS(코스피) 또는 .KQ(코스닥) (예: 005930.KS, 000660.KS).
    9. 뉴스에 티커가 잘못 표기되어 있어도(예: 삼전닉스에 005935 표기) 위 규칙을 우선 적용해 **올바른 티커로 보정**할 것.

    뉴스: {headlines}

    응답은 **유효한 JSON 객체 하나만** 출력한다 (마크다운·설명·백틱 금지).
    reason 문자열 안에 큰따옴표(")를 넣지 말 것 (깨짐 방지).
    형식:
    {{"stocks": [{{"name": "정확한 상장기업명", "ticker": "티커", "reason": "관련 뉴스 핵심 1줄 요약"}}, ...]}}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        res_text = response.choices[0].message.content or ""
        data = _parse_model_json_loose(res_text)
        if isinstance(data, dict):
            stocks = data.get("stocks")
            if isinstance(stocks, list):
                return [s for s in stocks if isinstance(s, dict)]
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
        print("AI 추출: stocks 배열 없음 → 빈 목록")
        return []
    except Exception as e:
        print(f"AI 추출 실패: {e}")
        return []


def align_stocks_to_news_context(headlines, stocks):
    """
    1차 추출(name/ticker/reason)이 뉴스 맥락과 맞는지 LLM이 판단·교정.
    (예: 금 시세 이슈인데 GOLD 법인 티커가 붙은 경우 → GLD 등으로 정정)
    이후 단계에서 yfinance로 실존·거래 여부를 다시 검증한다.
    """
    if not stocks:
        return []
    try:
        listing = json.dumps(
            [
                {"index": i, "name": s.get("name"), "ticker": s.get("ticker"), "reason": s.get("reason")}
                for i, s in enumerate(stocks)
            ],
            ensure_ascii=False,
        )
        hl = json.dumps(headlines, ensure_ascii=False)
        prompt = f"""너는 한국·미국 상장 증권과 뉴스 맥락을 연결하는 편집자다.

[뉴스 헤드라인]
{hl}

[1차 추출 종목 — 각 reason은 해당 줄과 연결된 한 줄 요약]
{listing}

각 index에 대해 다음을 수행한다.
1) 헤드라인·reason이 말하는 **주체**가 무엇인지 구분한다 (특정 상장사 vs 원자재·금값·유가·지수·환율 등 거시 이슈).
2) 그 주체에 투자자가 실제로 매매하는 **상장 종목/ETF 등**의 이름·티커가 맞는지 판단한다. 티커가 단어와만 비슷해 **다른 법인·상품**에 붙은 경우, 야후 파이낸스에서 쓰는 **올바른 심볼**로 고친다.
3) 한국: 반드시 ######.KS 또는 ######.KQ. 미국: 야후 표준 티커(예: BRK-B).
4) **명백히 뉴스와 무관**하거나 종목 지정이 틀렸다고 확신하면 exclude: true. 애매하면 exclude: false로 두고 ticker는 유지해도 된다.

출력: 유효한 JSON 객체 하나만 (코드펜스·설명 금지). reason 안에 큰따옴표(") 금지.
길이는 입력과 동일하고 index는 0부터 N-1까지 정확히 한 번씩.
형식: {{"alignments": [{{"index": 0, "exclude": false, "name": "...", "ticker": "...", "reason": "한 줄"}}, ...]}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        res_text = response.choices[0].message.content or ""
        data = _parse_model_json_loose(res_text)
        if isinstance(data, dict):
            parsed = data.get("alignments")
        elif isinstance(data, list):
            parsed = data
        else:
            parsed = None
        if not isinstance(parsed, list):
            print("AI 맥락 정렬: alignments 배열 없음 → 원본 유지")
            return stocks

        parsed_sorted = sorted(
            (x for x in parsed if isinstance(x, dict) and isinstance(x.get("index"), int)),
            key=lambda x: x["index"],
        )
        if len(parsed_sorted) != len(stocks) or any(
            parsed_sorted[i].get("index") != i for i in range(len(stocks))
        ):
            print("AI 맥락 정렬: index/개수 불일치 → 원본 유지")
            return stocks

        out = []
        for i, item in enumerate(parsed_sorted):
            if item.get("exclude"):
                print(
                    f"AI 맥락 정렬 제외: #{i} "
                    f"{stocks[i].get('ticker')} {stocks[i].get('name')}"
                )
                continue
            new_ticker = (item.get("ticker") or stocks[i].get("ticker") or "").strip()
            new_name = (item.get("name") or stocks[i].get("name") or "").strip()
            new_reason = (item.get("reason") or stocks[i].get("reason") or "").strip()
            old_t = (stocks[i].get("ticker") or "").strip()
            if new_ticker.upper() != old_t.upper():
                print(f"AI 맥락 정렬 교정: #{i} {old_t} → {new_ticker} ({new_name})")
            out.append({"name": new_name, "ticker": new_ticker, "reason": new_reason})
        return out
    except Exception as e:
        print(f"AI 맥락 정렬 실패: {e} → 원본 유지")
        return stocks


def calculate_technical_indicators(ticker):
    """RSI, MACD, 볼린저 밴드, 일목균형표 종합 지표 계산 (조건 완화)"""
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
        
        # 4. MACD (12, 26, 9) - 신규 추가 (트렌드 전환 감지)
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal_line = macd.ewm(span=9, adjust=False).mean()
        
        # 5. 피보나치 되돌림
        recent_high = df['High'].max()
        recent_low = df['Low'].min()
        diff = recent_high - recent_low
        fib_382 = recent_high - diff * 0.382
        fib_500 = recent_high - diff * 0.500
        
        signals = []
        
        # 조건 완화: 65 / 35 로 터치 영역 확대
        if current_rsi >= 65: signals.append("🔴 RSI 과매수 진입권 (조정 주의)")
        elif current_rsi <= 35: signals.append("🟢 RSI 과매도 진입권 (반등 기회)")
        
        if current_price >= bb_upper.iloc[-1]: signals.append("🔴 볼린저밴드 상단 돌파 (차익 실현 고려)")
        elif current_price <= bb_lower.iloc[-1]: signals.append("🟢 볼린저밴드 하단 이탈 (단기 지지선)")
        
        # MACD 크로스 감지 추가
        if macd.iloc[-1] > signal_line.iloc[-1] and macd.iloc[-2] <= signal_line.iloc[-2]:
            signals.append("🟢 MACD 골든크로스 (상승 모멘텀 전환)")
        elif macd.iloc[-1] < signal_line.iloc[-1] and macd.iloc[-2] >= signal_line.iloc[-2]:
            signals.append("🔴 MACD 데드크로스 (하락 모멘텀 전환)")
        
        if current_price > kijun_sen.iloc[-1] and df['Close'].iloc[-2] <= kijun_sen.iloc[-2]:
            signals.append("🟢 일목균형표 기준선 상향 돌파")
        elif current_price < kijun_sen.iloc[-1] and df['Close'].iloc[-2] >= kijun_sen.iloc[-2]:
            signals.append("🔴 일목균형표 기준선 하향 이탈")
            
        return {
            "price": current_price,
            "rsi": current_rsi,
            "bb_upper": bb_upper.iloc[-1],
            "bb_lower": bb_lower.iloc[-1],
            "kijun_sen": kijun_sen.iloc[-1],
            "fib_500": fib_500,
            "signals": signals
        }
    except Exception as e:
        print(f"[{ticker}] 지표 계산 실패: {e}")
        return None

def generate_deep_analysis(name, reason, indicators, market="KR"):
    """구조화된 3줄 요약 강제 적용"""
    if market == "US":
        currency_note = "모든 가격·밴드·기준선 수치는 미국 달러(USD) 기준이며, 본문에서 '원'·'₩' 표현을 쓰지 말고 달러($)로만 서술할 것."
    else:
        currency_note = "모든 가격·밴드·기준선 수치는 원화(KRW) 기준이며, 달러 표현을 쓰지 말 것."

    prompt = f"""
    월스트리트 수석 투자 분석가로서 '{name}' 종목에 대해 분석해.
    
    - 이슈: {reason}
    - 현재가: {indicators['price']:,.2f}
    - 시그널: {', '.join(indicators['signals']) if indicators['signals'] else '특이사항 없음'}
    - RSI: {indicators['rsi']:.2f} / 볼린저 상단: {indicators['bb_upper']:,.0f} / 볼린저 하단: {indicators['bb_lower']:,.0f}
    - 일목기준선: {indicators['kijun_sen']:,.0f} / 피보나치 50%: {indicators['fib_500']:,.0f}

    [{currency_note}]

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
    print("AI 뉴스 맥락 정렬 중...")
    target_stocks = align_stocks_to_news_context(headlines, target_stocks)
    target_stocks = validate_target_stocks(target_stocks)
    print(f"-> 타겟 종목 수 (맥락 정렬·검증 후): {len(target_stocks)}개")
    
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
        market = stock.get('market') or ("KR" if is_korean_equity_ticker(ticker) else "US")
        
        indicators = calculate_technical_indicators(ticker)
        if indicators is None: 
            continue
        
        # 시그널이 발생한 종목만 필터링 (조건을 완화하여 더 많이 통과됨)
        if len(indicators['signals']) > 0:
            alert_triggered = True
            print(f"🚨 [{name}] 강력한 기술적 시그널 발생! 리포트 작성 중...")
            
            analysis = generate_deep_analysis(name, reason, indicators, market=market)
            analysis_formatted = analysis.replace('\n', '\n\n')
            
            signals_text = "\n\n".join([f"• {sig}" for sig in indicators['signals']])
            price_str = format_money(indicators['price'], market)
            kijun_str = format_money(indicators['kijun_sen'], market)
            bb_unit = "$" if market == "US" else "₩"
            
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
                        {"title": "현재가", "value": price_str},
                        {"title": "주요 이슈", "value": reason},
                        {"title": "기술적 신호", "value": signals_text},
                        {"title": "볼린저 밴드", "value": f"하단 {bb_unit} {indicators['bb_lower']:,.0f} ~ 상단 {bb_unit} {indicators['bb_upper']:,.0f}"},
                        {"title": "RSI / 기준선", "value": f"{indicators['rsi']:.2f} / {kijun_str}"}
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

    # 감지된 종목이 있을 때 전송
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
