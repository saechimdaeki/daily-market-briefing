import json
import os
import re
import subprocess

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")


def ask_claude(prompt: str, system: str = "", timeout: int = 400) -> str:
    """claude CLI 헤드리스 모드(-p)로 단일 프롬프트를 실행하고 응답 텍스트를 반환.

    로컬에서는 claude CLI의 구독 로그인, CI에서는 ANTHROPIC_API_KEY 환경변수를
    CLI가 알아서 인식하므로 별도 분기가 필요 없다.
    """
    cmd = [
        "claude",
        "-p",
        "--model", CLAUDE_MODEL,
        "--tools", "",  # 순수 텍스트 생성 — 도구 사용 차단
        "--strict-mcp-config",  # 사용자 MCP 서버 로딩 생략 (속도)
        "--safe-mode",  # 사용자 훅/플러그인/CLAUDE.md 차단 (출력 오염 방지), 인증은 정상 유지
    ]
    if system:
        cmd += ["--append-system-prompt", system]
    result = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 실패 (code {result.returncode}): {result.stderr[:500]}")
    return result.stdout.strip()


def ask_claude_json(prompt: str, system: str = "", timeout: int = 400):
    """JSON 응답이 필요한 호출용 — 코드펜스/잡설 제거 후 파싱해 dict 또는 list 반환."""
    text = ask_claude(
        prompt + "\n\n반드시 유효한 JSON만 출력하라. 설명·코드펜스·백틱 금지.",
        system,
        timeout,
    )
    raw = re.sub(r"^```(?:json)?\s*", "", text.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise
