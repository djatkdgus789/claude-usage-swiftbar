# Claude Usage Widget

Claude 구독(Pro / Max)의 **5시간 세션 한도**와 **주간 한도** 사용률을 보여주는 macOS 위젯 + 메뉴 막대 앱입니다.
Claude Code의 `/usage` 명령, claude.ai의 *설정 → 사용량* 화면과 같은 데이터를 보여줍니다.

| 구성 요소 | 설명 |
| --- | --- |
| **메뉴 막대 앱** | 메뉴 막대에 현재 5시간 세션 사용률(예: `42%`)을 표시하고, 클릭하면 모든 한도의 상세 정보를 보여줍니다. 1분마다 자동 갱신합니다 (429 요청 한도 응답 시 자동으로 잠시 쉬었다가 재시도). |
| **데스크톱 / 알림 센터 위젯** | 소형 · 중형 · 대형 크기를 지원합니다. 사용률 게이지와 초기화까지 남은 시간을 표시합니다. |

사용률은 70% 이상이면 주황색, 90% 이상이면 빨간색으로 바뀝니다.

## 동작 방식

```
Claude Code 로그인 정보 (키체인 "Claude Code-credentials")
        │  OAuth 액세스 토큰
        ▼
메뉴 막대 앱 ── GET https://api.anthropic.com/api/oauth/usage (1분마다)
        │  usage.json 저장 (App Group 공유 컨테이너)
        ▼
WidgetKit 위젯 (샌드박스) ── usage.json 을 읽어 표시
```

- 위젯 확장은 샌드박스 안에서 실행되어 키체인과 네트워크에 직접 접근하기 어렵기 때문에, 메뉴 막대 앱이 데이터를 가져와 App Group 컨테이너에 저장하고 위젯은 그것을 읽기만 합니다.
- 토큰은 Claude Code가 저장해 둔 것을 **읽기만** 하며, 앱이 토큰을 갱신하거나 외부로 보내지 않습니다 (Anthropic API 호출 외).
- 토큰이 만료되면 터미널에서 `claude`를 한 번 실행하면 Claude Code가 토큰을 갱신합니다.

> ⚠️ `api/oauth/usage` 는 Claude Code 내부에서 쓰는 비공개 엔드포인트입니다. 향후 응답 형식이 바뀌면 동작하지 않을 수 있습니다. 새로운 한도 종류가 추가되는 정도는 자동으로 표시되도록 파싱합니다.

## 요구 사항

- macOS 14 Sonoma 이상
- Xcode 15 이상
- [XcodeGen](https://github.com/yonaskolb/XcodeGen): `brew install xcodegen`
- Claude Code에 Claude 구독 계정으로 로그인되어 있을 것 (`claude` 실행 후 `/login`)
- Xcode에 Apple ID 로그인 (*Xcode → Settings → Accounts*). 무료 Apple ID의 Personal Team으로도 충분합니다.
  위젯과 앱이 데이터를 공유하는 App Group 서명에 팀 ID가 필요합니다.

## 설치

```bash
git clone https://github.com/djatkdgus789/claude-usage-widget.git
cd claude-usage-widget
make install
```

`make install` 은 다음을 수행합니다.

1. `scripts/setup.sh` — 키체인의 *Apple Development* 인증서에서 팀 ID를 찾아 `Local.xcconfig` 생성
   (자동 탐지가 안 되면 `make setup TEAM=XXXXXXXXXX` 로 직접 지정. 번들 ID는 `BUNDLE_ID=com.you.claudeusage` 로 변경 가능)
2. `xcodegen generate` 로 `ClaudeUsage.xcodeproj` 생성
3. `xcodebuild` 로 Release 빌드
4. `/Applications/ClaudeUsage.app` 에 복사 후 실행

설치 후:

1. 메뉴 막대에 게이지 아이콘과 사용률이 나타납니다.
2. 바탕화면을 우클릭 → **위젯 편집…** → "Claude 사용량"을 검색해 원하는 크기를 추가합니다.
3. 메뉴의 **로그인 시 자동 실행**을 켜 두면 위젯이 항상 최신 상태로 유지됩니다.

Xcode에서 직접 빌드하려면 `make open` 으로 프로젝트를 연 뒤 `ClaudeUsage` 스킴을 실행하세요.

## Xcode 없이 쓰기: 메뉴 막대 플러그인 (SwiftBar)

Xcode 를 설치하지 않았다면 [SwiftBar](https://swiftbar.app) 플러그인으로 메뉴 막대에 사용량을 띄울 수 있습니다.
바탕화면 위젯은 없지만 Command Line Tools 의 `python3` 만 있으면 됩니다.

```bash
git clone -b main https://github.com/djatkdgus789/claude-usage-widget.git
cd claude-usage-widget
swiftbar/install.sh
```

- `install.sh` 는 SwiftBar 가 없으면 Homebrew 로 설치하고, 플러그인 폴더(기본 `~/SwiftBarPlugins`)에 `claude-usage.1m.py` 를 연결합니다.
- 메뉴 막대에 `5h 42% · 7d 18%` 처럼 표시되고, 클릭하면 한도별 막대 · 초기화까지 남은 시간이 나옵니다.
- 1분마다 갱신하며, 429 응답을 받으면 캐시된 값을 보여주며 잠시 쉽니다. **지금 새로고침** 메뉴로 즉시 갱신할 수 있습니다.
- 처음 실행할 때 키체인 접근 허용 창이 뜨면 **항상 허용**을 누르세요.
- 수동 확인: `swiftbar/claude-usage.1m.py` 를 터미널에서 직접 실행하면 메뉴 내용이 출력됩니다.

### 주간 전체 │ 주간 Fable

메뉴의 주간 줄은 세로로 반 나뉘어 왼쪽에 주간 전체, 오른쪽에 주간 Fable 한도를 보여줍니다.

```
Weekly  76%       │ Fable   30%
[=========...]    │ [====........]
reset 3d 1h       │ reset 3d 1h
```

- 기본값(`auto`)은 응답에서 키 이름에 `fable` 이 들어간 항목을 Fable 한도로 사용합니다.
- 다른 이름으로 온다면 SwiftBar → 플러그인 설정에서 `CLAUDE_FABLE_KEY` 를 그 키로 바꾸세요.
  응답 키 확인: README 아래 "API 응답 확인" 명령 참고.
- 오른쪽 칸이 "응답에 없음" 이면 해당 계정의 응답에 Fable 한도가 없다는 뜻입니다.

### 여러 계정 함께 보기 (예: Team + 개인 Max)

Claude Code 는 설정 폴더 하나에 로그인 하나만 저장합니다. 두 번째 계정은 **다른 설정 폴더**로 로그인하세요.

```bash
# 첫 번째 계정: 평소처럼 (기본 폴더 ~/.claude)
claude          # → /login 으로 Team 계정 로그인

# 두 번째 계정: 별도 폴더
CLAUDE_CONFIG_DIR=~/.claude-max claude    # → /login 으로 개인 Max 계정 로그인
```

플러그인은 키체인의 `Claude Code-credentials*` 항목과 `~/.claude*/.credentials.json` 을 모두 찾아
계정별로 표시합니다. 메뉴 막대에는 `T 42% · M 18%` 처럼 플랜 첫 글자와 5시간 사용률이 나오고,
메뉴에서 계정별 상세(가능하면 이메일 표시)를 볼 수 있습니다.

- 두 번째 계정을 평소에 쓰려면 `alias claude-max='CLAUDE_CONFIG_DIR=~/.claude-max claude'` 를 셸 설정에 추가하세요.
- 저장된 계정 목록 확인: `security dump-keychain | grep '"Claude Code-credentials'`
- 토큰은 각 계정으로 `claude` 를 실행할 때 갱신되므로, 오래 안 쓴 계정은 "토큰이 만료되었습니다" 가 뜰 수 있습니다.

### API 응답 확인

```bash
TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w | python3 -c 'import json,sys;print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])')
curl -s https://api.anthropic.com/api/oauth/usage -H "Authorization: Bearer $TOKEN" -H "anthropic-beta: oauth-2025-04-20" | python3 -m json.tool
```
출력에는 사용률과 초기화 시각만 있고 토큰은 포함되지 않습니다.

## 문제 해결

| 증상 | 해결 |
| --- | --- |
| "로그인 정보를 찾을 수 없습니다" | 터미널에서 `claude` 실행 후 `/login` 으로 Claude 구독 계정에 로그인 |
| "토큰이 만료되었습니다" | 터미널에서 `claude` 를 한 번 실행 (토큰 자동 갱신) 후 메뉴에서 새로고침 |
| 키체인 접근 허용 창이 뜸 | **항상 허용**을 누르면 이후에는 묻지 않습니다 |
| 위젯 목록에 보이지 않음 | 앱이 `/Applications` 에 있고 한 번 이상 실행되었는지 확인. 그래도 안 되면 로그아웃 후 재로그인 |
| 위젯에 "Claude Usage 앱을 실행하세요" | 메뉴 막대 앱이 실행 중인지 확인 |
| "개발 팀 ID 를 찾지 못했습니다" | Xcode → Settings → Accounts → **Manage Certificates…** → `+` → *Apple Development* 로 인증서를 만들거나, Accounts 화면의 팀 ID(10자리)로 `make install TEAM=XXXXXXXXXX` |
| 서명 오류 | Xcode → Settings → Accounts 에서 Apple ID 로그인 후 `make setup TEAM=<팀 ID>` |

## 프로젝트 구조

```
App/        메뉴 막대 앱 (데이터 수집, 키체인 읽기, API 호출)
Widget/     WidgetKit 확장 (소형/중형/대형 위젯)
swiftbar/   Xcode 없이 쓰는 SwiftBar 메뉴 막대 플러그인
Shared/     앱과 위젯이 공유하는 모델, App Group 저장소, 게이지 뷰
project.yml XcodeGen 프로젝트 정의
Config.xcconfig  공통 빌드 설정 (개인 설정은 Local.xcconfig)
```
