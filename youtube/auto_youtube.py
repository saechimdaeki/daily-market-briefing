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

# [핵심] 플렉스 고슴도치 페르소나 정의 (DALL-E 3용 프롬프트 최적화)
RICH_HEDGEHOG = (
    "A cute 3D rendered hedgehog character, identical to previous scenes, with round brown eyes, a soft cream-colored belly, "
    "and distinct but friendly brown quills. The hedgehog wears dark aviator sunglasses, a chunky gold dollar-sign pendant on a thick chain, "
    "and a small luxury gold watch on its wrist. It has a confident, smiling, flexing expression."
)

# ==========================================
# 📊 2. 시장 데이터 및 📝 3. 플렉스 대본/프롬프트 생성
# ==========================================
def fetch_rich_market_news():
    print("[1/6] 오늘의 플렉스 데이터를 수집 중...")
    tickers = {"나스닥": "^IXIC", "엔비디아": "NVDA", "테슬라": "TSLA", "비트코인": "BTC-USD"}
    summary = ""
    for name, ticker in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = hist['Close'].iloc[-1]
                open_price = hist['Open'].iloc[-1]
                change_pct = ((current_price - open_price) / open_price) * 100
                summary += f"{name}: {current_price:.2f} 달러 ({change_pct:+.2f}%)\n"
        except: pass
    return summary

def generate_flex_assets(market_data):
    print("[2/6] '플렉스 고슴도치' 페르소나로 대본 및 이미지 시나리오 생성 중...")
    
    system_prompt = f"""
    당신은 주식 전문 AI 유튜버 '플렉스 고슴도치'입니다. 
    1. 오프닝: "플렉스 고슴도치가 알려줄게!" 고정.
    2. 분량: 1500자 이상의 상세 분석. (준성 이름 언급 금지)
    3. 말투: 여유 있고 자신감 넘치는 태도, "이게 돈 버는 형의 비결이야"처럼 플렉스 하는 말투.
    4. 이미지: {RICH_HEDGEHOG} 이 캐릭터가 주인공인 장면 10개를 묘사하세요. (배경엔 돈다발, 고급 차트 등)
    5. 반드시 JSON 반환: {{"script": "전체 대본...", "prompts": ["prompt1", ..., "prompt10"]}}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": market_data}],
        response_format={ "type": "json_object" }
    )
    
    res = json.loads(response.choices[0].message.content)
    return res['script'], res['prompts']

# ==========================================
# 🎙️ 4. 음성 생성 및 Whisper 정밀 싱크 분석 ( onyx 목소리 추천 )
# ==========================================
def generate_pro_audio(text):
    print("[3/6] OpenAI TTS로 '플렉스 고슴도치' 목소리 생성 중...")
    # 신뢰감 있으면서도 여유로운 'onyx' 목소리 추천
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text
    )
    audio_path = "voice.mp3"
    response.stream_to_file(audio_path)
    
    # Whisper로 문장별 시작/종료 시간 정밀 추출
    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file, 
            model="whisper-1", 
            response_format="verbose_json", 
            timestamp_granularities=["segment"]
        )
    return audio_path, transcript.segments

# ==========================================
# 🎨 5. '플렉스 고슴도치' 상황 이미지 10장 생성 (DALL-E 3)
# ==========================================
def generate_rich_images(prompts):
    print(f"[4/6] 상황별 '플렉스 고슴도치' 이미지 {len(prompts)}장 생성 중...")
    paths = []
    for i, p in enumerate(prompts):
        try:
            # 고정된 페르소나 + 장면 묘사를 합쳐서 일관성 유지
            full_prompt = f"{RICH_HEDGEHOG} is {p} In a vibrant, 4k financial background with money, high detailed."
            res = client.images.generate(model="dall-e-3", prompt=full_prompt, size="1024x1024", n=1)
            img_url = res.data[0].url
            path = f"scene_{i}.png"
            with open(path, "wb") as f:
                f.write(requests.get(img_url).content)
            paths.append(path)
            time.sleep(1) 
        except Exception as e:
            print(f"이미지 {i} 생성 실패: {e}")
    return paths

# ==========================================
# 🎬 6. 최종 3~5분 영상 조립 및 렌더링 (자막 최적화 완료)
# ==========================================
def assemble_flex_video(audio_path, segments, image_paths):
    print("[5/6] Whisper 데이터를 기반으로 자막/이미지 정밀 싱크 중...")
    audio = AudioFileClip(audio_path)
    total_dur = audio.duration
    
    # 1. 자막 클립 생성 (타임스탬프 기반, 잘림 방지 레이아웃)
    subtitle_clips = []
    for seg in segments:
        txt = seg['text'].strip()
        if not txt: continue
        # 가로폭 제한 및 반투명 배경 추가
        t_clip = TextClip(txt, fontsize=45, color='yellow', bg_color='black',
                          font='NanumGothicBold', size=(1600, None), method='caption').set_duration(total_dur).set_position(('center', 820))
        t_clip = t_clip.set_start(seg['start']).set_end(seg['end']).set_position(('center', 850))
        subtitle_clips.append(t_clip)
        
    # 2. 이미지 클립 생성 (대본 흐름에 맞춰 교체)
    bg_clips = []
    img_switch_interval = len(segments) // len(image_paths)
    for i, img_p in enumerate(image_paths):
        start_t = segments[i * img_switch_interval]['start']
        # 마지막 이미지는 영상 끝까지
        end_t = segments[(i+1) * img_switch_interval]['start'] if (i+1) * img_switch_interval < len(segments) else total_dur
        
        c = ImageClip(img_p).set_start(start_t).set_end(end_t).resize(width=1920, height=1080)
        # 서서히 확대되는 효과 (Ken Burns)
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.03 * t).get_frame(t))
        bg_clips.append(c)
        
    bg_video = CompositeVideoClip(bg_clips)
    final_video = CompositeVideoClip([bg_video] + subtitle_clips).set_audio(audio)
    
    output_name = f"Flex_Hedgehog_{datetime.date.today().strftime('%Y%m%d')}.mp4"
    print(f"[6/6] 최종 인코딩 시작: {output_name}")
    final_video.write_videofile(output_name, fps=24, codec="libx264", audio_codec="aac", threads=4)
    return output_name

if __name__ == "__main__":
    try:
        data = fetch_rich_market_news()
        script, prompts = generate_flex_assets(data)
        audio_file, segments = generate_pro_audio(script)
        images = generate_rich_images(prompts)
        assemble_flex_video(audio_file, segments, images)
        print("✅ 싱크 완벽! 캐릭터 플렉스 완료!")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")