#!/usr/bin/env bash
# SwiftBar 를 설치하고 Claude 사용량 플러그인을 연결한다. Xcode 가 필요 없다.
set -euo pipefail
cd "$(dirname "$0")"
PLUGIN="$PWD/claude-usage.1m.py"

if ! /usr/bin/python3 -c 'import sys; sys.exit(0)' 2>/dev/null; then
  echo "❌ python3 가 없습니다. 'xcode-select --install' 로 Command Line Tools 를 설치하세요."
  exit 1
fi

if [[ ! -d /Applications/SwiftBar.app && ! -d "$HOME/Applications/SwiftBar.app" ]]; then
  if command -v brew >/dev/null; then
    echo "→ SwiftBar 설치 중 (brew install --cask swiftbar)"
    brew install --cask swiftbar
  else
    echo "❌ SwiftBar 가 없습니다. https://swiftbar.app 에서 받아 설치한 뒤 다시 실행하세요."
    exit 1
  fi
fi

dir="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
if [[ -z "$dir" ]]; then
  dir="$HOME/SwiftBarPlugins"
  defaults write com.ameba.SwiftBar PluginDirectory -string "$dir"
fi
mkdir -p "$dir"
chmod +x "$PLUGIN"
ln -sf "$PLUGIN" "$dir/claude-usage.1m.py"
echo "✅ 플러그인 연결: $dir/claude-usage.1m.py → $PLUGIN"

echo "→ 동작 확인 (첫 줄이 메뉴 막대에 표시됩니다):"
"$PLUGIN" | head -n 1

open -a SwiftBar
echo "✅ SwiftBar 실행. 메뉴 막대에 'Claude' 사용률이 나타납니다."
echo "   이미 실행 중이었다면 SwiftBar 메뉴 > Refresh All 을 누르세요."
