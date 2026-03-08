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

# ==========================================
# 📊 2. 시장 데이터 수집
# ==========================================
def fetch_market_context():
    print("[1/5] 오늘의 주요 증시 데이터 수집 중...")
    tickers = {"나스닥": "^IXIC", "엔비디아": "NVDA", "테슬라": "TSLA", "유가": "CL=F"}
    summary = ""
    for name, ticker in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                change = ((hist['Close'].iloc[0] - hist['Open'].iloc[0]) / hist['Open'].iloc[0]) * 100
                summary += f"{name}: {change:+.2f}% / 최신뉴스: {stock.news[0]['title'] if stock.news else 'N/A'}\n"
        except: pass
    return summary

# ==========================================
# 📝 3. 대본 및 상황별 이미지 프롬프트 생성
# ==========================================
def generate_creative_assets(market_data):
    print("[2/5] 시나리오 기반 대본 및 이미지 프롬프트 10개 생성 중...")
    
    system_prompt = """
    당신은 주식 전문 AI 유튜버 '주식하는 버섯'입니다.
    1. 반드시 첫 문장은 "주식하는 버섯이 알려줄게!"로 시작하세요.
    2. 사용자의 이름(준성 등)이나 모든 개인정보는 절대 언급하지 마세요.
    3. 수집된 데이터를 바탕으로 3~5분 분량(약 1500자 이상)의 심도 있는 분석 대본을 쓰세요.
    4. 대본 흐름에 맞춰 10개의 장면을 묘사하는 영문 DALL-E 3 프롬프트를 작성하세요.
    5. 이미지는 '귀여운 3D 버섯'이 주인공으로 나오는 경제 상황 묘사여야 합니다.
    6. 반드시 JSON 형식으로 반환하세요: {"script": "전체 대본...", "prompts": ["prompt1", ..., "prompt10"]}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": market_data}],
        response_format={ "type": "json_object" }
    )
    
    res = json.loads(response.choices[0].message.content)
    return res['script'], res['prompts']

# ==========================================
# 🎙️ 4. 고품질 AI 음성 생성 (OpenAI TTS)
# ==========================================
def generate_ai_voice(text):
    print("[3/5] OpenAI TTS로 고품질 음성 생성 중...")
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx", # 신뢰감 있는 남성 목소리
        input=text
    )
    audio_path = "voice_output.mp3"
    response.stream_to_file(audio_path)
    return audio_path

# ==========================================
# 🎨 5. DALL-E 3 상황 맞춤형 이미지 10장 생성
# ==========================================
def generate_context_images(prompts):
    print(f"[4/5] 경제 상황에 맞는 이미지 {len(prompts)}장 생성 중...")
    img_paths = []
    for i, p in enumerate(prompts):
        try:
            full_p = f"A cute 3D rendered mushroom character, {p}, financial atmosphere, high quality, 4k."
            res = client.images.generate(model="dall-e-3", prompt=full_p, size="1024x1024", n=1)
            img_url = res.data[0].url
            path = f"scene_{i}.png"
            with open(path, "wb") as f:
                f.write(requests.get(img_url).content)
            img_paths.append(path)
            time.sleep(1) 
        except Exception as e:
            print(f"이미지 {i} 생성 실패: {e}")
    return img_paths

# ==========================================
# 🎬 6. 최종 3~5분 영상 조립 및 렌더링
# ==========================================
def assemble_video(script_text, audio_path, image_paths):
    print("[5/5] 최종 영상 인코딩 시작 (3~5분 분량)...")
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    
    # 이미지당 노출 시간 계산
    clip_dur = total_duration / len(image_paths)
    clips = []
    
    for p in image_paths:
        # Ken Burns 효과 (서서히 확대)
        c = ImageClip(p).set_duration(clip_dur).resize(width=1920, height=1080)
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.02 * t).get_frame(t))
        clips.append(c)
        
    bg_video = concatenate_videoclips(clips, method="compose")
    
    # 한글 자막 (NanumGothic)
    txt = TextClip(script_text, fontsize=42, color='yellow', bg_color='black',
                   font='NanumGothic', size=(1700, None), method='caption').set_duration(total_duration).set_position(('center', 820))
    
    final_video = CompositeVideoClip([bg_video, txt]).set_audio(audio)
    output_name = f"Mushroom_Briefing_{datetime.date.today().strftime('%Y%m%d')}.mp4"
    
    final_video.write_videofile(output_name, fps=24, codec="libx264", audio_codec="aac", threads=4)
    return output_name

if __name__ == "__main__":
    try:
        context = fetch_market_context()
        script, prompts = generate_creative_assets(context)
        
        audio_file = generate_ai_voice(script)
        image_files = generate_context_images(prompts)
        
        video_output = assemble_video(script, audio_file, image_files)
        
        # 임시 파일 정리
        for f in image_files + [audio_file]:
            if os.path.exists(f): os.remove(f)
            
        print(f"\n✅ 제작 완료! 파일명: {video_output}")
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")