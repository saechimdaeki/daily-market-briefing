import os
import time
import requests
import datetime
import json
import yfinance as yf
from openai import OpenAI
from moviepy.editor import ImageClip, TextClip, CompositeVideoClip, AudioFileClip, concatenate_videoclips

# ==========================================
# ⚙️ 1. 환경 및 API 설정
# ==========================================
OPENAI_API_KEY = os.environ.get("AI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("AI_API_KEY 환경변수가 설정되지 않았습니다.")

client = OpenAI(api_key=OPENAI_API_KEY)

# [핵심] 리치 고슴도치 캐릭터 정의 (DALL-E 3 일관성 유지용)
RICH_HEDGEHOG = (
    "A cute 3D rendered hedgehog character with dark aviator sunglasses, "
    "a chunky gold dollar-sign pendant on a thick chain, and a small luxury gold watch on its wrist. "
    "It has a confident, smiling, flexing expression. The background should be a high-end financial office."
)

# ==========================================
# 📊 2. 퀀트 데이터 수집 (2026-03-08 실시간)
# ==========================================
def fetch_market_data():
    print(f"[1/6] {datetime.date.today()} 실시간 데이터를 수집 중...")
    tickers = {"나스닥": "^IXIC", "엔비디아": "NVDA", "테슬라": "TSLA", "애플": "AAPL"}
    summary = ""
    for name, ticker in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                current = hist['Close'].iloc[-1]
                change = ((current - hist['Open'].iloc[-1]) / hist['Open'].iloc[-1]) * 100
                summary += f"{name}: {current:.2f} ({change:+.2f}%) / 뉴스: {stock.news[0]['title'] if stock.news else 'N/A'}\n"
        except: pass
    return summary

# ==========================================
# 📝 3. 롱폼 대본 및 🎙️ 4. 음성/Whisper 싱크 생성
# ==========================================
def generate_assets(data):
    print("[2/6] '플렉스 고슴도치' 롱폼 시나리오 생성 중...")
    system_prompt = f"""
    당신은 주식 전문 AI 유튜버 '플렉스 고슴도치'입니다. 
    1. 반드시 첫 문장은 "플렉스 고슴도치가 알려줄게!"로 시작하세요.
    2. 김준성이라는 이름이나 CJ OliveNetworks 등 개인정보는 절대 언급하지 마세요.
    3. 2026년 실시간 데이터를 바탕으로 1500자 이상의 상세 분석 대본을 작성하세요.
    4. 장면별 {RICH_HEDGEHOG} 이미지 프롬프트 10개를 작성하여 JSON으로 반환하세요.
    5. 대본 말투는 자신감 넘치는 리치(Rich) 페르소나를 유지하세요.
    """
    res = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": data}],
        response_format={"type": "json_object"}
    )
    res_data = json.loads(res.choices[0].message.content)
    
    print("[3/6] OpenAI TTS(onyx) 음성 및 Whisper 정밀 분석 중...")
    audio_res = client.audio.speech.create(model="tts-1", voice="onyx", input=res_data['script'])
    audio_res.stream_to_file("voice.mp3")
    
    with open("voice.mp3", "rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f, model="whisper-1", response_format="verbose_json", timestamp_granularities=["segment"]
        )
    return res_data['script'], res_data['prompts'], transcript.segments

# ==========================================
# 🎨 5. 상황별 이미지 생성 및 🎬 6. 최종 렌더링
# ==========================================
def assemble_video(prompts, segments):
    print(f"[4/6] DALL-E 3 이미지 10장 생성 중...")
    img_paths = []
    for i, p in enumerate(prompts):
        res = client.images.generate(model="dall-e-3", prompt=f"{RICH_HEDGEHOG} {p}", size="1024x1024")
        path = f"scene_{i}.png"
        with open(path, "wb") as f: f.write(requests.get(res.data[0].url).content)
        img_paths.append(path)

    print("[5/6] 정밀 싱크 및 자막 최적화 조립 중...")
    audio = AudioFileClip("voice.mp3")
    total_dur = audio.duration
    
    # 자막 생성 (seg.text, seg.start 등 객체 접근 방식 적용)
    subtitle_clips = []
    for seg in segments:
        t_clip = TextClip(seg.text, fontsize=38, color='yellow', bg_color='rgba(0,0,0,0.6)',
                          font='NanumGothicBold', size=(1600, None), method='caption', align='center')
        t_clip = t_clip.set_start(seg.start).set_end(seg.end).set_position(('center', 780))
        subtitle_clips.append(t_clip)

    # 이미지 배경 (10장 균등 배분 및 Ken Burns 효과)
    img_dur = total_dur / len(img_paths)
    bg_clips = []
    for i, p in enumerate(img_paths):
        c = ImageClip(p).set_start(i * img_dur).set_duration(img_dur).resize(width=1920, height=1080)
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.02 * t).get_frame(t))
        bg_clips.append(c)
    
    final = CompositeVideoClip([CompositeVideoClip(bg_clips)] + subtitle_clips).set_audio(audio)
    output_name = f"Flex_Hedgehog_{datetime.date.today().strftime('%Y%m%d')}.mp4"
    
    print(f"[6/6] 최종 인코딩 시작: {output_name}")
    final.write_videofile(output_name, fps=24, codec="libx264", audio_codec="aac", threads=4)
    return output_name

if __name__ == "__main__":
    try:
        m_data = fetch_market_data()
        script, prompts, segments = generate_assets(m_data)
        assemble_video(prompts, segments)
        print("✅ 파이프라인 가동 성공! 리치 고슴도치 영상이 생성되었습니다.")
    except Exception as e:
        print(f"❌ 시스템 오류 발생: {e}")