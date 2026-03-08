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

# 플렉스 고슴도치 페르소나 (DALL-E 3용 프롬프트 고정)
RICH_HEDGEHOG = (
    "A cute 3D rendered hedgehog character with round brown eyes, a soft cream-colored belly, "
    "and distinct but friendly brown quills. The hedgehog wears dark aviator sunglasses, a chunky gold dollar-sign pendant on a thick chain, "
    "and a small luxury gold watch on its wrist. It has a confident, smiling, flexing expression."
)

# ==========================================
# 📊 2. 시장 데이터 및 📝 3. 대본/프롬프트 생성
# ==========================================
def fetch_rich_market_news():
    print(f"[1/6] {datetime.date.today()} 플렉스 데이터를 수집 중...")
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
    print("[2/6] '플렉스 고슴도치' 페르소나 대본 및 이미지 시나리오 생성 중...")
    system_prompt = f"""
    당신은 주식 전문 AI 유튜버 '플렉스 고슴도치'입니다. 
    1. 오프닝: "플렉스 고슴도치가 알려줄게!" 고정.
    2. 분량: 1500자 이상의 상세 분석. (개인정보 언급 절대 금지)
    3. 말투: 여유 있고 자신감 넘치는 태도, "이게 돈 버는 형의 비결이야"처럼 플렉스 하는 말투.
    4. 이미지: {RICH_HEDGEHOG} 이 캐릭터가 주인공인 장면 10개를 묘사하세요.
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
# 🎙️ 4. 음성 생성 및 Whisper 정밀 싱크 분석
# ==========================================
def generate_pro_audio(text):
    print("[3/6] OpenAI TTS 음성 생성 및 Whisper 정밀 분석 중...")
    response = client.audio.speech.create(model="tts-1", voice="onyx", input=text)
    audio_path = "voice.mp3"
    response.stream_to_file(audio_path)
    
    with open(audio_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            file=audio_file, 
            model="whisper-1", 
            response_format="verbose_json", 
            timestamp_granularities=["segment"]
        )
    return audio_path, transcript.segments

# ==========================================
# 🎨 5. '플렉스 고슴도치' 상황 이미지 10장 생성
# ==========================================
def generate_rich_images(prompts):
    print(f"[4/6] 상황별 이미지 {len(prompts)}장 생성 중...")
    paths = []
    for i, p in enumerate(prompts):
        try:
            full_prompt = f"{RICH_HEDGEHOG} is {p}. In a 4k financial background with money."
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
# 🎬 6. 최종 영상 조립 (Object Access 방식 수정 완료)
# ==========================================
def assemble_flex_video(audio_path, segments, image_paths):
    print("[5/6] 자막/이미지 정밀 싱크 렌더링 중...")
    audio = AudioFileClip(audio_path)
    total_dur = audio.duration
    
    # 6-1. 자막 클립 생성 (seg['text'] -> seg.text 로 수정)
    subtitle_clips = []
    for seg in segments:
        txt = seg.text.strip() # 이 부분을 도트 연산자로 수정함
        if not txt: continue
        
        t_clip = TextClip(txt, fontsize=42, color='yellow', bg_color='rgba(0,0,0,0.6)',
                          font='NanumGothicBold', size=(1600, None), method='caption', align='center')
        # seg.start, seg.end 로 수정
        t_clip = (t_clip.set_start(seg.start)
                        .set_end(seg.end)
                        .set_position(('center', 780)))
        subtitle_clips.append(t_clip)
        
    # 6-2. 이미지 클립 생성 (이미지 10장을 오디오 길이에 맞게 균등 배분)
    bg_clips = []
    num_imgs = len(image_paths)
    img_dur = total_dur / num_imgs
    
    for i, img_p in enumerate(image_paths):
        c = ImageClip(img_p).set_start(i * img_dur).set_duration(img_dur).resize(width=1920, height=1080)
        # 서서히 커지는 효과
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.02 * t).get_frame(t))
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
        print("✅ 싱크 완벽! 리치 고슴도치 영상 제작 성공!")
    except Exception as e:
        print(f"❌ 에러 발생: {e}")