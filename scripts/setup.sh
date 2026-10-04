#!/usr/bin/env bash
# Local.xcconfig 를 생성한다. 사용법: scripts/setup.sh [TEAM_ID] [BUNDLE_ID_PREFIX]
set -euo pipefail
cd "$(dirname "$0")/.."

team="${1:-${TEAM:-}}"
bundle="${2:-${BUNDLE_ID:-}}"

if [[ -z "$team" ]]; then
  # 키체인의 Apple Development 인증서에서 팀 ID(OU)를 추출
  team="$(security find-certificate -c "Apple Development" -p 2>/dev/null \
    | openssl x509 -noout -subject 2>/dev/null \
    | sed -n 's/.*OU *= *\([A-Z0-9]\{10\}\).*/\1/p' | head -n1 || true)"
fi

if [[ -z "$team" ]]; then
  echo "❌ 개발 팀 ID 를 찾지 못했습니다."
  echo "   Xcode > Settings > Accounts 에서 Apple ID 로 로그인한 뒤 다시 실행하거나,"
  echo "   make setup TEAM=XXXXXXXXXX 처럼 직접 지정하세요."
  exit 1
fi

if [[ -z "$bundle" ]]; then
  user="$(id -un | tr -cd '[:alnum:]' | tr '[:upper:]' '[:lower:]')"
  bundle="com.${user:-me}.claudeusage"
fi

cat > Local.xcconfig <<CFG
DEVELOPMENT_TEAM = $team
BUNDLE_ID_PREFIX = $bundle
CFG

echo "✅ Local.xcconfig 생성: TEAM=$team, BUNDLE_ID=$bundle"
