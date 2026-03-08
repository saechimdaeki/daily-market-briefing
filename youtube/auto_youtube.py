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
# 📊 2. 시장 상황 데이터 수집 (Fact 수집)
# ==========================================
def fetch_market_news():
    print("[1/5] 오늘의 실시간 시장 데이터를 수집 중...")
    tickers = {"나스닥": "^IXIC", "S&P500": "^GSPC", "엔비디아": "NVDA", "테슬라": "TSLA", "국제유가": "CL=F"}
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
# 📝 3. 대본 작성 및 이미지 프롬프트 생성
# ==========================================
def generate_assets(market_data):
    print("[2/5] 시각적 스토리텔링 대본 및 이미지 프롬프트 생성 중...")
    
    system_prompt = """
    당신은 주식 전문 AI 유튜버 '주식하는 버섯'입니다. 
    1. 반드시 첫 문장은 "주식하는 버섯이 알려줄게!"로 시작하세요.
    2. 사용자의 이름(준성 등)이나 개인정보는 절대로 언급하지 마세요.
    3. 수집된 데이터를 바탕으로 3~5분 분량(약 1500자 이상)의 심도 있는 분석 대본을 쓰세요.
    4. 대본의 흐름에 맞춰 10개의 장면을 설명하는 영문 DALL-E 3 프롬프트를 작성하세요. 
    5. 이미지는 '귀여운 버섯 캐릭터'가 각 경제 상황(환희, 공포, 분석 등)을 겪는 모습이어야 합니다.
    6. 반드시 JSON 형식으로 반환하세요: {"script": "전체 대본...", "prompts": ["prompt1", "prompt2", ...]}
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
def generate_pro_audio(text):
    print("[3/5] OpenAI TTS로 고품질 목소리 생성 중...")
    # 'alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer' 중 선택 가능 (onyx는 신뢰감 있는 남성형)
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text
    )
    audio_path = "vibrant_voice.mp3"
    response.stream_to_file(audio_path)
    return audio_path

# ==========================================
# 🎨 5. 상황 맞춤형 이미지 생성 (DALL-E 3)
# ==========================================
def generate_scene_images(prompts):
    print(f"[4/5] 상황별 맞춤 이미지 {len(prompts)}장 생성 시작...")
    paths = []
    for i, p in enumerate(prompts):
        try:
            # 일관성을 위해 'Cute 3D Mushroom' 스타일 고정
            final_p = f"A cute 3D rendered mushroom character, {p}, financial news style, vibrant colors, 4k."
            res = client.images.generate(model="dall-e-3", prompt=final_p, size="1024x1024", n=1)
            img_url = res.data[0].url
            path = f"scene_{i}.png"
            with open(path, "wb") as f:
                f.write(requests.get(img_url).content)
            paths.append(path)
            time.sleep(2) # 안정적인 API 호출을 위한 텀
        except Exception as e:
            print(f"이미지 생성 실패 {i}: {e}")
    return paths

# ==========================================
# 🎬 6. 최종 3~5분 영상 렌더링
# ==========================================
def render_final_longform(script_text, audio_path, image_paths):
    print("[5/5] 최종 영상 조립 및 자막 작업 중...")
    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    
    # 이미지별 노출 시간 계산
    clip_dur = total_duration / len(image_paths)
    clips = []
    for p in image_paths:
        # 서서히 커지는 효과(Ken Burns)로 지루함 방지
        c = ImageClip(p).set_duration(clip_dur).resize(width=1920, height=1080)
        c = c.fl(lambda gf, t: ImageClip(gf(t)).resize(1 + 0.03 * t).get_frame(t))
        clips.append(c)
        
    bg_video = concatenate_videoclips(clips, method="compose")
    
    # 가독성 좋은 자막 (하단 검정 반투명 바 배경 추천)
    txt = TextClip(script_text, fontsize=42, color='yellow', bg_color='black',
                   font='NanumGothic', size=(1700, None), method='caption').set_duration(total_duration).set_position(('center', 820))
    
    final = CompositeVideoClip([bg_video, txt]).set_audio(audio)
    output_name = f"Mushroom_Briefing_{datetime.date.today().strftime('%Y%m%d')}.mp4"
    
    # 롱폼이므로 스레드를 활용해 빠르게 인코딩
    final.write_videofile(output_name, fps=24, codec="libx264", audio_codec="aac", threads=4)
    return output_name

if __name__ == "__main__":
    try:
        news_data = fetch_market_news()
        script, prompts = generate_assets(news_data)
        
        audio_file = generate_pro_audio(script)
        image_files = generate_scene_images(prompts)
        
        final_video = render_final_longform(script, audio_file, image_files)
        
        # 임시 파일 정리
        for f in image_files + [audio_file]:
            if os.path.exists(f): os.remove(f)
            
        print(f"\n🎉 성공! '주식하는 버섯'의 롱폼 영상이 완성되었습니다: {final_video}")
        
    except Exception as e:
        print(f"\n❌ 시스템 오류: {e}")