#!/usr/bin/env bash
# Local.xcconfig 를 생성한다. 사용법: scripts/setup.sh [TEAM_ID] [BUNDLE_ID_PREFIX]
set -euo pipefail
cd "$(dirname "$0")/.."

team="${1:-${TEAM:-}}"
bundle="${2:-${BUNDLE_ID:-}}"

# Xcode 에 로그인된 계정의 팀 ID 목록 (Xcode 설정에서)
xcode_teams() {
  for key in IDEProvisioningTeamByIdentifier IDEProvisioningTeams; do
    defaults read com.apple.dt.Xcode "$key" 2>/dev/null || true
  done | sed -n 's/.*teamID = "\{0,1\}\([A-Z0-9]\{10\}\)"\{0,1\};.*/\1/p'
}

# 키체인의 Apple Development 인증서들에서 팀 ID(OU) 추출
cert_teams() {
  security find-certificate -a -c "Apple Development" -p 2>/dev/null \
    | awk '/BEGIN CERT/{buf=""} {buf=buf $0 "\n"} /END CERT/{printf "%s", buf | "openssl x509 -noout -subject"; close("openssl x509 -noout -subject")}' 2>/dev/null \
    | sed -n 's/.*OU *= *\([A-Z0-9]\{10\}\).*/\1/p' || true
}

if [[ -z "$team" ]]; then
  candidates="$( { xcode_teams; cert_teams; } | awk '!seen[$0]++')"
  team="$(printf '%s\n' "$candidates" | head -n1)"
  if [[ "$(printf '%s\n' "$candidates" | grep -c .)" -gt 1 ]]; then
    echo "ℹ️  여러 팀 ID 를 찾았습니다: $(echo $candidates)"
    echo "   첫 번째($team)를 사용합니다. 다른 팀을 쓰려면 make setup TEAM=<팀 ID>"
  fi
fi

if [[ -z "$team" ]]; then
  echo "❌ 개발 팀 ID 를 찾지 못했습니다."
  echo "   1) Xcode > Settings > Accounts 에서 Apple ID 로 로그인하고"
  echo "      Manage Certificates… > + > Apple Development 로 인증서를 만든 뒤 다시 실행하거나,"
  echo "   2) Accounts 화면에서 팀 ID(10자리)를 확인해 make install TEAM=XXXXXXXXXX 처럼 직접 지정하세요."
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
