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
client = OpenAI(api_key=OPENAI_API_KEY)

# ==========================================
# 📊 2. 데이터 및 3. 대본 생성 (기존 로직 유지)
# ==========================================
def fetch_market_context():
    print("[1/5] 시장 데이터 수집 중...")
    tickers = {"나스닥": "^IXIC", "엔비디아": "NVDA", "테슬라": "TSLA", "유가": "CL=F"}
    summary = ""
    for name, ticker in tickers.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                change = ((hist['Close'].iloc[0] - hist['Open'].iloc[0]) / hist['Open'].iloc[0]) * 100
                summary += f"{name}: {change:+.2f}% / 뉴스: {stock.news[0]['title'] if stock.news else 'N/A'}\n"
        except: pass
    return summary

def generate_creative_assets(market_data):
    print("[2/5] 주식 버섯 시나리오 생성 중...")
    system_prompt = """
    당신은 주식 전문 AI 유튜버 '주식하는 버섯'입니다.
    1. 반드시 첫 문장은 "주식하는 버섯이 알려줄게!"로 시작하세요.
    2. 사용자의 이름(준성 등)이나 모든 개인정보는 절대 언급하지 마세요.
    3. 수집된 데이터를 바탕으로 3~5분 분량(약 1500자 이상)의 분석 대본을 쓰세요.
    4. 대본 흐름에 맞춰 10개의 장면을 묘사하는 영문 DALL-E 3 프롬프트를 작성하세요.
    5. 반드시 JSON 형식으로 반환하세요: {"script": "전체 대본...", "prompts": ["prompt1", ...]}
    """
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": market_data}],
        response_format={ "type": "json_object" }
    )
    res = json.loads(response.choices[0].message.content)
    return res['script'], res['prompts']

# ==========================================
# 🎙️ 4. 음성 및 이미지 생성 (기존 로직 유지)
# ==========================================
def generate_ai_voice(text):
    print("[3/5] OpenAI TTS 음성 생성 중...")
    response = client.audio.speech.create(model="tts-1", voice="onyx", input=text)
    audio_path = "voice_output.mp3"
    response.stream_to_file(audio_path)
    return audio_path

def generate_context_images(prompts):
    print(f"[4/5] 상황 맞춤형 이미지 {len(prompts)}장 생성 중...")
    img_paths = []
    for i, p in enumerate(prompts):
        try:
            res = client.images.generate(model="dall-e-3", prompt=f"Cute 3D mushroom, {p}, 4k", size="1024x1024")
            img_url = res.data[0].url
            path = f"scene_{i}.png"
            with open(path, "wb") as f: f.write(requests.get(img_url).content)
            img_paths.append(path)
            time.sleep(1)
        except: pass
    return img_paths

# ==========================================
# 🎬 5. 최종 영상 조립 (자막 분할 로직 추가)
# ==========================================
def assemble_video(script_text, audio_path, image_paths):
    print("[5/5] 자막 분할 및 최종 영상 렌더링 시작...")
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    
    # 5-1. 배경 이미지 클립 생성
    clip_dur = total_duration / len(image_paths)
    bg_clips = []
    for p in image_paths:
        c = ImageClip(p).set_duration(clip_dur).resize(width=1920, height=1080)
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.02 * t).get_frame(t))
        bg_clips.append(c)
    bg_video = concatenate_videoclips(bg_clips, method="compose")

    # 5-2. [핵심] 자막 쪼개기 로직
    # 대본을 문장 단위로 나누어 시간에 맞춰 배분합니다.
    sentences = [s.strip() for s in script_text.split('.') if len(s.strip()) > 5]
    subtitle_clips = []
    sent_dur = total_duration / len(sentences)
    
    for i, sent in enumerate(sentences):
        txt_clip = TextClip(sent, fontsize=50, color='yellow', bg_color='black',
                            font='NanumGothic', size=(1600, None), method='caption')
        txt_clip = (txt_clip.set_start(i * sent_dur)
                            .set_duration(sent_dur)
                            .set_position(('center', 850)))
        subtitle_clips.append(txt_clip)

    # 모든 요소를 합치기
    final_video = CompositeVideoClip([bg_video] + subtitle_clips).set_audio(audio)
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
        
        for f in image_files + [audio_file]:
            if os.path.exists(f): os.remove(f)
        print(f"\n✅ 드디어 성공! 파일명: {video_output}")
    except Exception as e:
        print(f"\n❌ 에러 발생: {e}")