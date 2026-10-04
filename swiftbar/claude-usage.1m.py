#!/usr/bin/python3
# <xbar.title>Claude Usage</xbar.title>
# <xbar.version>v1.2</xbar.version>
# <xbar.desc>Shows Claude subscription (Pro/Max/Team) 5-hour session and weekly usage in the menu bar. Supports multiple accounts.</xbar.desc>
# <xbar.dependencies>python3, Claude Code (logged in)</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.environment>[CLAUDE_FABLE_KEY=auto]</swiftbar.environment>
"""
Claude usage menu bar plugin for SwiftBar / xbar (no Xcode needed).

The `.1m.` in the file name means it runs every minute.
It reads the OAuth token stored by Claude Code and queries the same endpoint as Claude Code's `/usage`.

Multiple accounts: log in to Claude Code with a separate config dir per account
(e.g. `CLAUDE_CONFIG_DIR=~/.claude-max claude`, then `/login`) and each gets its own
`Claude Code-credentials-…` keychain item. This plugin finds all of those items plus
`~/.claude*/.credentials.json` and shows each account.
On HTTP 429 (rate limited) an account shows its cached data and backs off for a while.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = os.environ.get("CLAUDE_USAGE_API_BASE", "https://api.anthropic.com")
SECURITY = os.environ.get("CLAUDE_USAGE_SECURITY_BIN", "/usr/bin/security")
KEYCHAIN_PREFIX = "Claude Code-credentials"
CACHE_PATH = os.path.expanduser("~/Library/Caches/claude-usage-swiftbar.json")
DEFAULT_BACKOFF = 5 * 60

TITLES = {
    "five_hour": "5-hour session",
    "seven_day": "Weekly",
    "seven_day_sonnet": "Weekly Sonnet",
    "seven_day_opus": "Weekly Opus",
    "seven_day_oauth_apps": "Weekly OAuth apps",
    "extra_usage": "Extra usage",
}
ORDER = list(TITLES)
SHORT = {"five_hour": "5h", "seven_day": "7d"}
# The response may contain internal codename entries (e.g. iguana_necktie).
# Only show known limits and five_hour* / seven_day* keys.
DISPLAY_PREFIXES = ("five_hour", "seven_day")


# Key of the Fable weekly limit. "auto" uses the entry whose key contains "fable".
FABLE_KEY = (os.environ.get("CLAUDE_FABLE_KEY") or "auto").strip()


def is_fable(key):
    if FABLE_KEY.lower() != "auto":
        return key == FABLE_KEY
    return "fable" in key.lower()


def is_displayed(key):
    return key in TITLES or key.startswith(DISPLAY_PREFIXES) or is_fable(key)

CLAUDE_ORANGE = "#D97757"


class UsageError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------- credentials

def parse_credentials(text):
    try:
        oauth = json.loads(text)["claudeAiOauth"]
        token = oauth["accessToken"]
    except (ValueError, KeyError, TypeError):
        return None
    if not token:
        return None
    return {"token": token, "plan": oauth.get("subscriptionType")}


def run_security(args):
    try:
        out = subprocess.run([SECURITY] + args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def keychain_services():
    """Find all `Claude Code-credentials*` service names in the keychain (does not read secrets)."""
    dump = run_security(["dump-keychain"]) or ""
    names = set(re.findall(r'"svce"<blob>="(%s[^"]*)"' % re.escape(KEYCHAIN_PREFIX), dump))
    names.add(KEYCHAIN_PREFIX)
    # Default item first, the rest by name
    return sorted(names, key=lambda n: (n != KEYCHAIN_PREFIX, n))


def credential_files():
    home = os.path.expanduser("~")
    dirs = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        dirs.append(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"]))
    try:
        dirs += sorted(os.path.join(home, d) for d in os.listdir(home) if d.startswith(".claude"))
    except OSError:
        pass
    seen, files = set(), []
    for d in dirs:
        path = os.path.join(d, ".credentials.json")
        if path not in seen and os.path.isfile(path):
            seen.add(path)
            files.append(path)
    return files


def discover_accounts():
    """[{key, source, token, plan}] — each token only once."""
    accounts, tokens = [], set()

    def add(key, source, creds):
        if creds and creds["token"] not in tokens:
            tokens.add(creds["token"])
            accounts.append(dict(creds, key=key, source=source))

    for service in keychain_services():
        raw = run_security(["find-generic-password", "-s", service, "-w"])
        if raw and raw.strip():
            add("keychain:" + service, service, parse_credentials(raw.strip()))
    for path in credential_files():
        try:
            with open(path, encoding="utf-8") as f:
                add("file:" + path, path.replace(os.path.expanduser("~"), "~"), parse_credentials(f.read()))
        except OSError:
            continue
    return accounts


# ---------------------------------------------------------------- API

def parse_date(value):
    """ISO8601 string -> epoch seconds. Works around Python 3.9 fromisoformat limits (Z suffix, fraction digits)."""
    if not isinstance(value, str):
        return None
    s = value.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(.*)$", s)
    if not m:
        return None
    base, frac, tz = m.groups()
    if frac:
        base += "." + (frac + "000000")[:6]
    try:
        dt = datetime.fromisoformat(base + tz)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def parse_windows(data):
    if not isinstance(data, dict):
        raise UsageError("Could not parse the usage response.")
    windows = []
    for key, value in data.items():
        if not isinstance(value, dict) or not is_displayed(key):
            continue
        util = value.get("utilization")
        if not isinstance(util, (int, float)) or isinstance(util, bool):
            continue
        if value.get("is_enabled") is False:
            continue
        windows.append({"id": key, "utilization": float(util), "resets_at": parse_date(value.get("resets_at"))})
    windows.extend(parse_model_limits(data.get("limits"), {w["id"] for w in windows}))
    windows.sort(key=lambda w: (ORDER.index(w["id"]) if w["id"] in ORDER else len(ORDER), w["id"]))
    return windows


def parse_model_limits(limits, existing):
    """Per-model weekly limits from the `limits` array (e.g. Fable).

    Example entry: {"kind": "weekly_scoped", "group": "weekly", "percent": 13,
             "resets_at": "...", "scope": {"model": {"display_name": "Fable"}}}
    -> {"id": "seven_day_model_fable", "title": "Weekly Fable", ...}
    Models already reported by a fixed key (e.g. seven_day_opus) are skipped.
    """
    out = []
    if not isinstance(limits, list):
        return out
    for item in limits:
        if not isinstance(item, dict) or item.get("kind") != "weekly_scoped":
            continue
        scope = item.get("scope") if isinstance(item.get("scope"), dict) else {}
        model = scope.get("model") if isinstance(scope.get("model"), dict) else {}
        name = model.get("display_name") or model.get("id")
        pct = item.get("percent")
        if not isinstance(name, str) or not name or isinstance(pct, bool) or not isinstance(pct, (int, float)):
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        if "seven_day_" + slug in existing:
            continue
        wid = "seven_day_model_" + slug
        if wid in existing:
            continue
        existing.add(wid)
        out.append({"id": wid, "title": "Weekly " + name, "utilization": float(pct),
                    "resets_at": parse_date(item.get("resets_at"))})
    return out


def api_get(path, token):
    req = urllib.request.Request(API_BASE + path, headers={
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": "claude-usage-swiftbar/1.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UsageError("Token expired. Run claude once with this account to refresh it.")
        if e.code == 429:
            retry = e.headers.get("Retry-After") if e.headers else None
            try:
                retry = float(retry) if retry else None
            except ValueError:
                retry = None
            raise UsageError("Rate limited. Will retry shortly.", retry_after=retry or DEFAULT_BACKOFF)
        raise UsageError("HTTP error %d" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise UsageError("Network error: %s" % getattr(e, "reason", e))
    try:
        return json.loads(body)
    except ValueError:
        raise UsageError("Could not parse the usage response.")


def fetch_usage(token):
    return parse_windows(api_get("/api/oauth/usage", token))


# ---------------------------------------------------------------- cache

def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {"accounts": {}}
    if not isinstance(cache.get("accounts"), dict):
        return {"accounts": {}}  # Discard caches from the old single-account version
    return cache


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def update_account(entry, account, now, force):
    entry["source"] = account["source"]
    if account.get("plan"):
        entry["plan"] = account["plan"]
    if not force and now < entry.get("next_allowed", 0):
        return
    try:
        entry["windows"] = fetch_usage(account["token"])
        entry["fetched_at"] = now
        entry["error"] = None
        entry["next_allowed"] = 0
    except UsageError as e:
        entry["error"] = str(e)
        if e.retry_after:
            entry["next_allowed"] = now + e.retry_after
        return


def update(now, force=False):
    cache = load_cache()
    accounts = discover_accounts()
    old = cache["accounts"]
    cache["accounts"] = {}
    cache["order"] = [a["key"] for a in accounts]
    for account in accounts:
        entry = old.get(account["key"], {})
        update_account(entry, account, now, force)
        cache["accounts"][account["key"]] = entry
    cache["error"] = None if accounts else (
        "No Claude Code login found. Run claude in a terminal and /login.")
    save_cache(cache)
    return cache


# ---------------------------------------------------------------- rendering

def effective(window, now):
    r = window.get("resets_at")
    if r and r <= now:
        return 0.0
    return max(0.0, min(100.0, window["utilization"]))


def color_for(pct):
    if pct >= 90:
        return "#FF3B30"
    if pct >= 70:
        return "#FF9500"
    return CLAUDE_ORANGE


def bar(pct, width=20):
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def humanize(seconds):
    minutes = max(0, int(seconds // 60))
    days, rem = divmod(minutes, 60 * 24)
    hours, mins = divmod(rem, 60)
    if days:
        return "%dd %dh" % (days, hours)
    if hours:
        return "%dh %dm" % (hours, mins)
    return "%dm" % mins


def title(key):
    if key not in TITLES and is_fable(key):
        return "Weekly Fable"
    return TITLES.get(key, key.replace("_", " ").title())


def plan_name(entry):
    plan = entry.get("plan")
    return plan.capitalize() if plan else "Claude"


def short_names(entries):
    """Short account names for the menu bar: plan initial (T, M, P …), numbered when duplicated."""
    names = [plan_name(e)[0].upper() for e in entries]
    counts = {n: names.count(n) for n in names}
    seen = {}
    out = []
    for n in names:
        if counts[n] > 1:
            seen[n] = seen.get(n, 0) + 1
            out.append("%s%d" % (n, seen[n]))
        else:
            out.append(n)
    return out


def headline(entry, now):
    """Menu bar summary for one account (5-hour limit, else the first limit)."""
    windows = entry.get("windows") or []
    if not windows:
        return None
    primary = next((w for w in windows if w["id"] == "five_hour"), windows[0])
    return effective(primary, now)


def render_full(w, now):
    pct = effective(w, now)
    out = [
        "%s   %d%% | color=%s" % (w.get("title") or title(w["id"]), round(pct), color_for(pct)),
        "%s | font=Menlo size=11 color=%s" % (bar(pct), color_for(pct)),
    ]
    r = w.get("resets_at")
    if r and r > now:
        when = datetime.fromtimestamp(r).strftime("%b %d %H:%M")
        out.append("Resets in %s (%s) | size=11 color=gray" % (humanize(r - now), when))
    elif r:
        out.append("Reset | size=11 color=gray")
    return out


def render(cache, now):
    entries = [cache["accounts"][k] for k in cache.get("order", []) if k in cache["accounts"]]
    lines = []

    # ---- Menu bar title
    with_data = [e for e in entries if e.get("windows")]
    any_error = any(e.get("error") for e in entries) or cache.get("error")
    if len(entries) == 1 and with_data:
        e = entries[0]
        parts = ["%s %d%%" % (SHORT[w["id"]], round(effective(w, now)))
                 for w in e["windows"] if w["id"] in SHORT] or ["%d%%" % round(headline(e, now))]
        head = " · ".join(parts)
    elif with_data:
        shorts = short_names(entries)
        parts = []
        for short, e in zip(shorts, entries):
            pct = headline(e, now)
            parts.append("%s %s" % (short, "–" if pct is None else "%d%%" % round(pct)))
        head = " · ".join(parts)
    else:
        head = "Claude"
    if any_error:
        head += " ⚠︎"
    worst = max([effective(w, now) for e in with_data for w in e["windows"]] or [0])
    attrs = "sfimage=gauge.with.dots.needle.%s" % ("50percent" if with_data else "0percent")
    if worst >= 90:
        attrs += " color=#FF3B30"
    lines.append("%s | %s" % (head, attrs))
    lines.append("---")

    if cache.get("error"):
        lines.append("⚠︎ %s | color=#FF3B30 size=11" % cache["error"])

    # ---- Per-account details
    shorts = short_names(entries)
    for i, (short, e) in enumerate(zip(shorts, entries)):
        if i:
            lines.append("---")
        name = plan_name(e)
        if len(entries) > 1:
            name = "[%s] %s" % (short, name)
        lines.append("%s | size=13" % name)
        windows = list(e.get("windows") or [])
        # Put Weekly Fable right below Weekly
        fable = next((w for w in windows if is_fable(w["id"])), None)
        if fable is not None and any(w["id"] == "seven_day" for w in windows):
            windows.remove(fable)
            at = next(i for i, w in enumerate(windows) if w["id"] == "seven_day") + 1
            windows.insert(at, fable)
        for w in windows:
            lines.extend(render_full(w, now))
        if e.get("error"):
            lines.append("⚠︎ %s | color=#FF3B30 size=11" % e["error"])
        if e.get("fetched_at"):
            lines.append("Updated: %s | size=11 color=gray"
                         % datetime.fromtimestamp(e["fetched_at"]).strftime("%H:%M:%S"))

    lines.append("---")
    lines.append("Refresh now | refresh=true sfimage=arrow.clockwise")
    lines.append("Open claude.ai usage | href=https://claude.ai/settings/usage sfimage=safari")
    return "\n".join(lines)


def main():
    now = time.time()
    # A manual refresh from the SwiftBar menu ignores the backoff.
    force = os.environ.get("SWIFTBAR_PLUGIN_REFRESH_REASON") == "MenuAction"
    print(render(update(now, force=force), now))


if __name__ == "__main__":
    sys.exit(main())
