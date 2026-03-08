import os
import time
import requests
import datetime
import base64
import yfinance as yf
from openai import OpenAI
from gtts import gTTS
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip

# ==========================================
# ⚙️ 1. 환경 및 API 설정
# ==========================================
OPENAI_API_KEY = os.environ.get("AI_API_KEY")
DID_API_KEY = os.environ.get("DID_API_KEY")

if not OPENAI_API_KEY or not DID_API_KEY:
    raise ValueError("OpenAI 또는 D-ID API 키가 환경변수에 설정되지 않았습니다.")

client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 📊 2. 시장 데이터 수집 모듈
# ==========================================
def fetch_market_data():
    print("[1/6] 미 증시 및 거시 경제 데이터 수집 중...")
    data_str = "--- [거시 경제 지표] ---\n"
    for name, ticker in {"공포지수(VIX)": "^VIX", "WTI 원유": "CL=F"}.items():
        hist = yf.Ticker(ticker).history(period="1d")
        if not hist.empty:
            data_str += f"{name}: {hist['Close'].iloc[0]:.2f}\n"
            
    data_str += "\n--- [주요 특징주 및 뉴스] ---\n"
    for name, ticker in {"나스닥": "^IXIC", "엔비디아": "NVDA", "테슬라": "TSLA"}.items():
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        if not hist.empty:
            change = ((hist['Close'].iloc[0] - hist['Open'].iloc[0]) / hist['Open'].iloc[0]) * 100
            data_str += f"{name} 등락률: {change:.2f}%\n"
            try:
                for news in stock.news[:1]:
                    data_str += f" - 헤드라인: {news.get('title', '')}\n"
            except: pass
    return data_str

# ==========================================
# 📝 3. 대본 작성 모듈
# ==========================================
def generate_script(market_data):
    print("[2/6] 100만 유튜버 페르소나로 대본 생성 중...")
    prompt = f"""
    당신은 구독자 100만 명의 경제 유튜버입니다. 아래 데이터를 바탕으로 1분 분량(약 300자)의 아주 짧고 강렬한 쇼츠(Shorts) 대본을 쓰세요.
    인과관계를 명확히 하고, 구어체("형님들", "난리 났습니다" 등)를 사용하세요. 
    특수기호나 괄호 지문은 절대 넣지 마세요.
    
    데이터: {market_data}
    """
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": prompt}],
        temperature=0.8
    )
    return res.choices[0].message.content

# ==========================================
# 🎨 4. DALL-E 3 메인 아바타 생성
# ==========================================
def generate_avatar_image():
    print("[3/6] DALL-E 3로 오늘의 아바타(버섯 캐릭터) 생성 중...")
    img_filename = "avatar_base.png"
    
    dalle_prompt = "A cute 3d rendered mushroom character in a dynamic stock market background, facing forward directly at the camera, clear mouth, solid lighting, masterpiece."
    
    res = client.images.generate(
        model="dall-e-3", prompt=dalle_prompt, size="1024x1024", quality="standard", n=1
    )
    
    img_data = requests.get(res.data[0].url).content
    with open(img_filename, 'wb') as f:
        f.write(img_data)
        
    return img_filename

# ==========================================
# 🎙️ 5. TTS 및 자막 타임스탬프 추출
# ==========================================
def generate_audio_and_sync(script_text):
    print("[4/6] 음성 합성 및 Whisper API 타임스탬프 추출 중...")
    audio_path = "temp_audio.mp3"
    
    gTTS(text=script_text, lang='ko', slow=False).save(audio_path)
    
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            file=f, model="whisper-1", response_format="verbose_json", timestamp_granularities=["word"]
        )
    return audio_path, transcript.words

# ==========================================
# 🗣️ 6. D-ID API 립싱크 렌더링 모듈
# ==========================================
def animate_avatar_with_did(image_path, audio_path):
    print("[5/6] D-ID 서버에 이미지/음성 업로드 및 립싱크 렌더링 요청...")
    
    # Secrets에서 꺼내온 키를 Base64로 인코딩하여 서버 인증
    encoded_key = base64.b64encode(DID_API_KEY.encode('utf-8')).decode('utf-8')
    headers = {"Authorization": f"Basic {encoded_key}"}
    
    with open(image_path, "rb") as f:
        img_res = requests.post("https://api.d-id.com/images", headers=headers, files={"image": f}).json()
    img_url = img_res.get("url")

    with open(audio_path, "rb") as f:
        aud_res = requests.post("https://api.d-id.com/audios", headers=headers, files={"audio": f}).json()
    aud_url = aud_res.get("url")

    talk_payload = {
        "source_url": img_url,
        "script": {"type": "audio", "audio_url": aud_url},
        "config": {"fluent": True, "pad_audio": 0.0}
    }
    talk_res = requests.post("https://api.d-id.com/talks", headers=headers, json=talk_payload).json()
    talk_id = talk_res.get("id")

    print("  - D-ID 서버 렌더링 대기 중 (약 30초~1분 소요)...")
    while True:
        status_res = requests.get(f"https://api.d-id.com/talks/{talk_id}", headers=headers).json()
        if status_res.get("status") == "done":
            video_url = status_res.get("result_url")
            break
        elif status_res.get("status") == "error":
            raise Exception("D-ID 렌더링 실패:", status_res)
        time.sleep(5)
        
    output_vid = "raw_talking_avatar.mp4"
    with open(output_vid, 'wb') as f:
        f.write(requests.get(video_url).content)
        
    return output_vid

# ==========================================
# 🎬 7. 최종 영상 조립 (자막 오버레이)
# ==========================================
def render_final_video(video_path, word_sync_data, final_name="final_youtube_shorts.mp4"):
    print("[6/6] 최종 자막 오버레이 및 영상 인코딩 중...")
    
    base_video = VideoFileClip(video_path)
    subtitle_clips = []
    for word_info in word_sync_data:
        # GitHub Actions Ubuntu 환경에 맞춰 한글 깨짐 방지 폰트(NanumGothic) 적용
        txt_clip = TextClip(word_info.word, fontsize=80, color='yellow', stroke_color='black', 
                            stroke_width=2, font='NanumGothic')
        txt_clip = (txt_clip
                    .set_position(('center', base_video.h * 0.8))
                    .set_start(word_info.start)
                    .set_end(word_info.end))
        subtitle_clips.append(txt_clip)
        
    final_video = CompositeVideoClip([base_video] + subtitle_clips)
    final_video.write_videofile(final_name, fps=24, codec="libx264", audio_codec="aac", logger=None)
    
    print(f"\n✅ 완벽하게 자동화된 영상이 완성되었습니다: {final_name}")

# ==========================================
# 🚀 메인 실행부
# ==========================================
if __name__ == "__main__":
    try:
        raw_data = fetch_market_data()
        script = generate_script(raw_data)
        print(f"\n[오늘의 대본]\n{script}\n")
        
        avatar_img = generate_avatar_image()
        audio_file, word_sync = generate_audio_and_sync(script)
        
        talking_video = animate_avatar_with_did(avatar_img, audio_file)
        
        output_filename = f"AI_Shorts_{datetime.date.today().strftime('%Y%m%d')}.mp4"
        render_final_video(talking_video, word_sync, output_filename)
        
        # 사용이 끝난 임시 파일 삭제
        for f in [avatar_img, audio_file, talking_video]:
            if os.path.exists(f): os.remove(f)
            
    except Exception as e:
        print(f"\n❌ 시스템 에러 발생: {e}")