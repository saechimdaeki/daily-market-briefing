import os
import time
import base64

import requests
from openai import OpenAI

from agents.state import MarketBriefingState

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "public")
IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
IMAGE_QUALITY = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")


def generate_image(state: MarketBriefingState) -> dict:
    """
    [Node] GPT Image 이미지 생성
    - image_prompt를 받아 1024x1024 이미지를 생성하고 public/cover.png로 저장
    """
    t0 = time.time()
    try:
        client = OpenAI(api_key=os.environ.get("AI_API_KEY"))
        response = client.images.generate(
            model=IMAGE_MODEL,
            prompt=state["image_prompt"],
            size="1024x1024",
            quality=IMAGE_QUALITY,
            n=1,
        )
        image = response.data[0]

        image_url = getattr(image, "url", None) or ""
        image_base64 = getattr(image, "b64_json", None)
        if image_base64:
            img_data = base64.b64decode(image_base64)
        elif image_url:
            img_data = requests.get(image_url, timeout=30).content
        else:
            raise RuntimeError("Image API response did not include url or b64_json")

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(os.path.join(OUTPUT_DIR, "cover.png"), "wb") as f:
            f.write(img_data)

        duration_ms = int((time.time() - t0) * 1000)
        return {
            "image_url": image_url,
            "execution_log": [{"node": "generate_image", "label": "GPT Image 생성",
                                "status": "success", "duration_ms": duration_ms,
                                "detail": f"{IMAGE_MODEL} 1024×1024 커버 이미지 저장 완료"}],
            "errors": [],
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        return {
            "image_url": "",
            "execution_log": [{"node": "generate_image", "label": "GPT Image 생성",
                                "status": "error", "duration_ms": duration_ms, "detail": str(e)[:120]}],
            "errors": [f"generate_image: {e}"],
        }
