#!/usr/bin/env bash
# Installs SwiftBar and links the Claude usage plugin. No Xcode needed.
set -euo pipefail
cd "$(dirname "$0")"
PLUGIN="$PWD/claude-usage.1m.py"

if ! /usr/bin/python3 -c 'import sys; sys.exit(0)' 2>/dev/null; then
  echo "❌ python3 not found. Install the Command Line Tools with 'xcode-select --install'."
  exit 1
fi

if [[ ! -d /Applications/SwiftBar.app && ! -d "$HOME/Applications/SwiftBar.app" ]]; then
  if command -v brew >/dev/null; then
    echo "→ Installing SwiftBar (brew install --cask swiftbar)"
    brew install --cask swiftbar
  else
    echo "❌ SwiftBar not found. Install it from https://swiftbar.app and run this again."
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
echo "✅ Plugin linked: $dir/claude-usage.1m.py → $PLUGIN"

echo "→ Test run (the first line is shown in the menu bar):"
"$PLUGIN" | head -n 1

open -a SwiftBar
echo "✅ SwiftBar started. Claude usage will appear in the menu bar."
echo "   If SwiftBar was already running, choose Refresh All from its menu."
