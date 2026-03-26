# Teams `!주가` 명령 연동 가이드

이 문서는 Microsoft Teams Workflow/Power Automate에서 `!주가 SK하이닉스` 같은 메시지를 감지해 GitHub Actions를 호출하고, 실행 결과를 다시 Teams 채널로 보내는 구성을 설명합니다.

## 1. GitHub 쪽 준비

이 저장소에는 아래 워크플로우가 추가되어 있습니다.

- [teams_stock_command.yml](/Users/junseongkim/Desktop/daily-market-briefing/.github/workflows/teams_stock_command.yml)

필수 GitHub Secrets:

- `AI_API_KEY`
- `TEAMS_WEBHOOK_URL`

워크플로우 입력값:

- `stock_query`: 종목명 또는 티커

직접 실행 예:

- `SK하이닉스`
- `효성중공업`
- `000660.KS`
- `NVDA`

## 2. Teams Workflow 권장 흐름

권장 플로우:

1. Teams 채널 메시지 트리거
2. 메시지 본문에서 `!주가` 감지
3. 종목명 부분만 잘라내기
4. GitHub REST API로 `workflow_dispatch` 호출
5. GitHub Actions가 카드 생성 후 Teams 웹후크로 결과 전송

## 3. Teams Workflow에서 쓸 GitHub API

호출 메서드:

- `POST`

호출 URL:

```text
https://api.github.com/repos/<OWNER>/<REPO>/actions/workflows/teams_stock_command.yml/dispatches
```

예시:

```text
https://api.github.com/repos/saechimdaeki/daily-market-briefing/actions/workflows/teams_stock_command.yml/dispatches
```

필수 헤더:

```text
Accept: application/vnd.github+json
Authorization: Bearer <GITHUB_PAT>
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

요청 바디 예시:

```json
{
  "ref": "main",
  "inputs": {
    "stock_query": "SK하이닉스"
  }
}
```

## 4. Teams Workflow에서 메시지 파싱

메시지가 아래처럼 들어온다고 가정합니다.

```text
!주가 SK하이닉스
```

파싱 규칙:

1. 메시지가 `!주가`로 시작하는지 확인
2. 앞의 `!주가`를 제거
3. 남은 값을 trim 해서 `stock_query`로 전달

정규식 예시:

```text
^!주가\s+(.+)$
```

캡처 그룹 1:

```text
SK하이닉스
```

## 5. GitHub Personal Access Token 권한

Teams Workflow에서 GitHub API를 직접 호출하려면 별도의 토큰이 필요합니다.

권장:

- Fine-grained PAT

필요 권한:

- Actions: `Read and write`
- Contents: `Read-only`
- Metadata: `Read-only`

대상 저장소:

- 이 저장소 하나만 허용

## 6. 응답 방식

현재 구현은 GitHub Actions 실행이 끝나면 저장소 시크릿 `TEAMS_WEBHOOK_URL`로 Adaptive Card를 전송합니다.

즉, Teams Workflow는 GitHub 실행만 시키고 응답을 기다릴 필요가 없습니다.

## 7. 동작 확인 체크리스트

1. GitHub Actions 탭에서 `Teams Stock Command` 수동 실행
2. `stock_query = SK하이닉스` 입력
3. Teams 채널에 카드가 정상 도착하는지 확인
4. Teams Workflow에서 같은 값을 API로 넘겨도 동작하는지 확인

## 8. 주의 사항

- Teams 채널 정책에 따라 Incoming Webhook 사용이 제한될 수 있습니다.
- 그런 경우 마지막 전송 단계는 Teams Workflow 쪽 `Flow bot으로 카드 게시` 방식으로 바꾸는 것이 더 안정적입니다.
- 현재 스크립트는 한국 종목명 검색과 한국 티커 검증에 강하게 맞춰져 있습니다.
