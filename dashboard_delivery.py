"""Publish only dashboard artifacts; leave the working tree and other Pages files intact."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

DEFAULT_SITE_URL = 'https://saechimdaeki.github.io/daily-market-briefing/'


def dashboard_url():
    return os.environ.get('TRADING_DESK_URL') or os.environ.get('GITHUB_PAGES_URL', DEFAULT_SITE_URL).rstrip('/') + '/performance.html'


def publish_performance(output_dir=None, repository=None):
    root = Path(__file__).resolve().parent
    output = Path(output_dir or os.environ.get('OUTPUT_DIR', 'public')).resolve()
    artifacts = ['performance.html', 'performance.json']
    for name in artifacts:
        if not (output / name).is_file():
            raise FileNotFoundError(f'대시보드 결과물 없음: {name}')

    def git(*args, cwd=root):
        attempts = 2 if args[0] == 'push' else 1
        for attempt in range(attempts):
            try:
                result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=120,
                                        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
            except subprocess.TimeoutExpired:
                if attempt+1 < attempts:
                    print('[대시보드] push 응답 지연: 같은 커밋 재확인',flush=True)
                    continue
                raise RuntimeError('대시보드 배포 응답 시간 초과') from None
            if not result.returncode:
                return result.stdout.strip()
            diagnostic = (result.stdout+' '+result.stderr).lower()
            groups = [
                ('인증/접근 권한',('authentication failed','could not read username','permission denied','user interaction is not allowed','repository not found','403')),
                ('연결/DNS',('could not resolve host','failed to connect','connection reset','connection timed out','unable to access','remote end hung up','502','503')),
                ('동시 배포 충돌',('non-fast-forward','fetch first','failed to push some refs')),
            ]
            reason=next((label for label,markers in groups if any(marker in diagnostic for marker in markers)),'원인 미분류')
            if attempt+1 < attempts and result.returncode==128:
                print(f'[대시보드] push 실패: {reason} · 1회 재시도',flush=True)
                time.sleep(1)
                continue
            # Classify failures without exposing remote URLs or credential-helper output.
            raise RuntimeError(f'대시보드 배포 git {args[0]} 실패: {reason} (종료 코드 {result.returncode})')

    remote = repository or git('remote', 'get-url', 'origin')
    with tempfile.TemporaryDirectory(prefix='desk-pages-') as temp:
        checkout = Path(temp) / 'pages'
        git('clone', '--depth', '1', '--single-branch', '--branch', 'gh-pages', remote, str(checkout))
        for name in artifacts:
            shutil.copyfile(output / name, checkout / name)
        git('add', '--', *artifacts, cwd=checkout)
        if not git('diff', '--cached', '--name-only', cwd=checkout):
            return False
        name = git('config', 'user.name') or 'Trading Desk'
        email = git('config', 'user.email') or 'trading-desk@users.noreply.github.com'
        git('-c', f'user.name={name}', '-c', f'user.email={email}', 'commit', '-m',
            'Update trading desk dashboard', cwd=checkout)
        # A normal push rejects concurrent changes; never force or overwrite other reports.
        git('push', 'origin', 'HEAD:gh-pages', cwd=checkout)
    return True


if __name__ == '__main__':
    changed = publish_performance()
    print('대시보드 배포 반영 완료' if changed else '대시보드 변경 없음')
    print(dashboard_url())
