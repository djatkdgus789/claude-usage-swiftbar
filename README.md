# Claude Usage for SwiftBar

A [SwiftBar](https://swiftbar.app) menu bar plugin that shows your Claude subscription
(Pro / Max / Team) usage limits — the same numbers as Claude Code's `/usage` and
claude.ai → Settings → Usage. No Xcode required.

```
M 0% · T 0%            ← menu bar: 5-hour usage per account
─────────────────────
[M] Max
5-hour session   0%
░░░░░░░░░░░░░░░░░░░░
Resets in 3h 34m (Oct 04 14:29)
Weekly   2%
░░░░░░░░░░░░░░░░░░░░
Resets in 5d 8h (Oct 09 18:59)
Weekly Fable   37%
███████░░░░░░░░░░░░░
Resets in 5d 8h (Oct 09 18:59)
Updated: 10:42:00
─────────────────────
[T] Team
...
─────────────────────
Refresh now
Open claude.ai usage
```

- Refreshes every minute. On HTTP 429 it shows the cached values and backs off
  (`Retry-After`, or 5 minutes). **Refresh now** ignores the backoff.
- Bars turn orange at 70% and red at 90%.
- Multiple accounts (e.g. a Team plan and a personal Max plan) are shown together.
- Only needs the `python3` that ships with the Xcode Command Line Tools.

## Install

```bash
git clone https://github.com/djatkdgus789/claude-usage-widget.git
cd claude-usage-widget
swiftbar/install.sh
```

`install.sh` installs SwiftBar with Homebrew if it is missing, sets the plugin folder
(default `~/SwiftBarPlugins`), and symlinks `swiftbar/claude-usage.1m.py` into it.
Later updates are just `git pull`.

If macOS asks for keychain access, choose **Always Allow**.

Requirements:
- macOS with the Command Line Tools (`xcode-select --install`)
- [Claude Code](https://claude.com/claude-code) logged in with a Claude subscription (`claude` → `/login`)

## Multiple accounts

Claude Code keeps one login per config directory. Log in to each extra account with
its own directory:

```bash
claude                                    # first account (default ~/.claude)
CLAUDE_CONFIG_DIR=~/.claude-team claude   # second account → /login
```

Each login gets its own keychain item. Check with:

```bash
security dump-keychain | grep '"svce"' | grep 'Claude Code'
#   "svce"<blob>="Claude Code-credentials"
#   "svce"<blob>="Claude Code-credentials-2c24b9db"
```

The plugin finds every `Claude Code-credentials*` item and every
`~/.claude*/.credentials.json`, skips duplicate tokens, and labels accounts by plan
initial (`M`, `T`, `P`; numbered if two share a plan).

When an access token (about 8 hours) expires, the plugin refreshes it the same way
Claude Code does and saves the new credentials back to the same keychain item or file,
so Claude Code stays logged in. It refreshes only within 2 minutes of expiry or after a
401, at most once every 10 minutes per account, and never retries a refresh token the
server rejected.

## How it works

1. Reads the OAuth token Claude Code stored in the keychain (`security find-generic-password`)
   or in `.credentials.json`. Tokens are only sent to Anthropic (`api.anthropic.com`, and
   `platform.claude.com` when refreshing).
2. Calls `GET https://api.anthropic.com/api/oauth/usage` (header `anthropic-beta: oauth-2025-04-20`).
3. Shows `five_hour`, `seven_day`, other `seven_day_*` limits, and per-model weekly limits
   from the `limits` array (`kind: "weekly_scoped"`, e.g. Fable). Internal codename entries
   such as `iguana_necktie` are ignored.
4. Caches results in `~/Library/Caches/claude-usage-swiftbar.json`.

> The usage endpoint is the one Claude Code uses internally and is not a public API;
> its format may change.

### Settings

| SwiftBar variable | Default | Meaning |
| --- | --- | --- |
| `CLAUDE_FABLE_KEY` | `auto` | Which limit is shown as "Weekly Fable". `auto` = the limit whose key contains `fable`. |

### Inspect the raw response

```bash
TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w | python3 -c 'import json,sys;print(json.load(sys.stdin)["claudeAiOauth"]["accessToken"])')
curl -s https://api.anthropic.com/api/oauth/usage -H "Authorization: Bearer $TOKEN" -H "anthropic-beta: oauth-2025-04-20" | python3 -m json.tool
```

The output contains only usage numbers and reset times, not the token.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "No Claude Code login found" | Run `claude` and `/login` |
| "Token expired" | Run `claude` once with that account, then **Refresh now** |
| "Login expired" | The refresh token was rejected; run `claude` with that account and `/login` |
| "Rate limited" | Wait; the plugin retries automatically |
| Only one account shown | Log in to the other account with `CLAUDE_CONFIG_DIR` (see above) |
| Nothing in the menu bar | Run `swiftbar/claude-usage.1m.py` in a terminal to see its output |

## Development

```bash
python3 -m unittest discover -s tests -v
```

Tests use a fake `security` binary and a local HTTP server; no real credentials or
network access are needed. CI runs them on macOS with the system `/usr/bin/python3`.

```
swiftbar/claude-usage.1m.py   the plugin
swiftbar/install.sh           installer
tests/                        unit + end-to-end tests (fixture: a real usage response)
```
