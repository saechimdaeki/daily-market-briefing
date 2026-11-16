import json
import os
import re
import shutil
import subprocess
import tempfile

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CHATGPT_CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"


class CodexUnavailable(RuntimeError):
    """로컬 Codex가 분석 결과를 생성하지 못했다."""


def _ask_codex(prompt: str, system: str, timeout: int) -> str:
    env = os.environ.copy()
    env.pop("CODEX_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)
    executable = shutil.which("codex") or CHATGPT_CODEX
    print("[AI] 로컬 Codex CLI 호출", flush=True)
    cmd = [
        executable, "--ask-for-approval", "never", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "-c", 'web_search="disabled"',
        "-c", 'shell_environment_policy.inherit="none"',
        "-",
    ]
    instructions = "제공된 프롬프트에 텍스트로만 답하라. 도구를 사용하거나 파일을 읽지 마라."
    if system:
        instructions += f"\n\n{system}"
    try:
        with tempfile.TemporaryDirectory(prefix="market-briefing-codex-") as workdir:
            result = subprocess.run(
                cmd, input=f"{instructions}\n\n{prompt}", cwd=workdir,
                env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout,
            )
    except OSError as exc:
        raise CodexUnavailable(f"Codex CLI를 실행할 수 없습니다: {executable}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CodexUnavailable(f"Codex CLI 응답 시간 초과 ({timeout}초)") from exc
    if result.returncode != 0:
        raise CodexUnavailable(
            f"Codex CLI 실패 (code {result.returncode}). 실행 권한과 Codex 인증 설정을 확인하세요."
        )
    response = result.stdout.strip()
    if not response:
        raise CodexUnavailable("Codex CLI가 빈 응답을 반환했습니다.")
    print("[AI] 로컬 Codex CLI 응답 수신", flush=True)
    return response


def _claude_logged_in(env: dict, timeout: int) -> bool:
    try:
        status = subprocess.run(
            ["claude", "auth", "status", "--json"], env=env,
            capture_output=True, text=True, timeout=min(timeout, 10),
        )
        return status.returncode == 0 and json.loads(status.stdout).get("loggedIn") is True
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def ask_claude(prompt: str, system: str = "", timeout: int = 400) -> str:
    """로컬 Claude 세션을 우선 사용하고, 사용할 수 없으면 Codex로 전환한다."""
    env = os.environ.copy()
    in_github_actions = env.get("GITHUB_ACTIONS") == "true"
    if not in_github_actions:
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        if not _claude_logged_in(env, timeout):
            return _ask_codex(prompt, system, timeout)

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
        cmd, input=prompt, env=env, capture_output=True, text=True, timeout=timeout
    )
    response = result.stdout.strip()
    limited = re.match(r"^(?:you['’]ve hit your .*limit|usage limit|rate limit)", response, re.IGNORECASE)
    if not in_github_actions and (result.returncode != 0 or not response or limited):
        print("[AI] Claude CLI 응답 실패 또는 사용량 제한. Codex로 전환합니다.", flush=True)
        return _ask_codex(prompt, system, timeout)
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI 실패 (code {result.returncode}): {result.stderr[:500]}")
    return response


def _parse_json(text: str):
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


def ask_claude_json(prompt: str, system: str = "", timeout: int = 400, retries: int = 1):
    """JSON 응답이 필요한 호출용 — 코드펜스/잡설 제거 후 파싱해 dict 또는 list 반환.
    LLM이 깨진 JSON을 내면(따옴표 미이스케이프 등) 한 번 더 요청한다."""
    for attempt in range(retries + 1):
        text = ask_claude(
            prompt + "\n\n반드시 유효한 JSON만 출력하라. 설명·코드펜스·백틱 금지. 문자열 안 큰따옴표는 쓰지 말 것.",
            system,
            timeout,
        )
        try:
            return _parse_json(text)
        except json.JSONDecodeError as e:
            if attempt == retries:
                raise
            print(f"JSON 파싱 실패({e}) → 재요청")
