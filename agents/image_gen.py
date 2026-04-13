import os
import time

import requests
from openai import OpenAI

from agents.state import MarketBriefingState

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "public")


def generate_image(state: MarketBriefingState) -> dict:
    """
    [Node] DALL-E-3 이미지 생성
    - image_prompt를 받아 1024x1024 이미지를 생성하고 public/cover.png로 저장
    """
    t0 = time.time()
    try:
        client = OpenAI(api_key=os.environ.get("AI_API_KEY"))
        response = client.images.generate(
            model="dall-e-3",
            prompt=state["image_prompt"],
            size="1024x1024",
            quality="standard",
            n=1,
        )
        image_url = response.data[0].url

        img_data = requests.get(image_url, timeout=30).content
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "cover.png"), "wb") as f:
            f.write(img_data)

        duration_ms = int((time.time() - t0) * 1000)
        return {
            "image_url": image_url,
            "execution_log": [{"node": "generate_image", "label": "DALL-E 이미지 생성",
                                "status": "success", "duration_ms": duration_ms,
                                "detail": "1024×1024 커버 이미지 저장 완료"}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "image_url": "",
            "execution_log": [{"node": "generate_image", "label": "DALL-E 이미지 생성",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"generate_image: {e}"],
        }
