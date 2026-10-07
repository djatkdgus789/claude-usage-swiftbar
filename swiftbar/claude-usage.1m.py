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

Token refresh: the access token lasts about 8 hours. When it expires, the plugin uses the
refresh token the same way Claude Code does and writes the new credentials back to the
original keychain item (or file) in the same format. Refresh tokens rotate, so not saving
them would log Claude Code out. Refreshes happen only near expiry or on a 401, at most once
per REFRESH_COOLDOWN per account, and never again with a refresh token the server rejected.
"""
import binascii
import fcntl
import hashlib
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

TOKEN_URL = os.environ.get("CLAUDE_USAGE_TOKEN_URL", "https://platform.claude.com/v1/oauth/token")
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"  # Claude Code's OAuth client
# Only refresh this close to expiry. Before that, leave it to Claude Code.
REFRESH_MARGIN = 2 * 60
# Minimum time between refresh attempts per account (successful or not)
REFRESH_COOLDOWN = 10 * 60
# Serializes refreshes so two plugin runs never spend the same refresh token.
REFRESH_LOCK = os.path.expanduser("~/Library/Caches/claude-usage-token-refresh.lock")

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
        raw = json.loads(text)
        oauth = raw["claudeAiOauth"]
        token = oauth["accessToken"]
    except (ValueError, KeyError, TypeError):
        return None
    if not token:
        return None
    expires_at = oauth.get("expiresAt")
    scopes = oauth.get("scopes")
    return {
        "token": token,
        "plan": oauth.get("subscriptionType"),
        "refresh_token": oauth.get("refreshToken") or None,
        "expires_at": expires_at / 1000.0 if isinstance(expires_at, (int, float)) else None,
        "scopes": scopes if isinstance(scopes, list) else [],
        "raw": raw,
    }


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
        add("keychain:" + service, service, read_source("keychain:" + service))
    for path in credential_files():
        add("file:" + path, path.replace(os.path.expanduser("~"), "~"), read_source("file:" + path))
    return accounts


def read_source(key):
    """Read the credentials for an account key (`keychain:<service>` / `file:<path>`)."""
    kind, _, where = key.partition(":")
    if kind == "keychain":
        raw = run_security(["find-generic-password", "-s", where, "-w"])
        return parse_credentials(raw.strip()) if raw and raw.strip() else None
    try:
        with open(where, encoding="utf-8") as f:
            return parse_credentials(f.read())
    except OSError:
        return None


def security_quote(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def write_source(key, raw):
    """Save refreshed credentials back where they came from, in Claude Code's format."""
    kind, _, where = key.partition(":")
    text = json.dumps(raw, separators=(",", ":"))
    if kind == "file":
        tmp = where + ".tmp"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, where)
            return True
        except OSError:
            return False
    attrs = run_security(["find-generic-password", "-s", where]) or ""
    m = re.search(r'"acct"<blob>="([^"]*)"', attrs)
    account = m.group(1) if m else (os.environ.get("USER") or "")
    # Like Claude Code, pass the command on stdin of `security -i` so the secret never
    # shows up in process arguments.
    command = "add-generic-password -U -a %s -s %s -X %s\n" % (
        security_quote(account), security_quote(where),
        security_quote(binascii.hexlify(text.encode("utf-8")).decode("ascii")))
    try:
        out = subprocess.run([SECURITY, "-i"], input=command, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    # `security -i` exits 0 even when the command fails, so check stderr too.
    return out.returncode == 0 and not out.stderr.strip()


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


class Unauthorized(UsageError):
    pass


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
            raise Unauthorized("Token expired. Run claude once with this account to refresh it.")
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


# ---------------------------------------------------------------- token refresh

def fingerprint(secret):
    """Short digest stored in the cache instead of the secret itself."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def needs_refresh(account, now):
    exp = account.get("expires_at")
    return exp is not None and exp - REFRESH_MARGIN <= now


def request_refresh(creds):
    """(response, rejected) — rejected means the refresh token can no longer be used."""
    body = {"grant_type": "refresh_token", "refresh_token": creds["refresh_token"], "client_id": CLIENT_ID}
    if creds.get("scopes"):
        body["scope"] = " ".join(creds["scopes"])
    req = urllib.request.Request(TOKEN_URL, data=json.dumps(body).encode("utf-8"), headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "claude-usage-swiftbar/1.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return None, e.code in (400, 401, 403)
    except (urllib.error.URLError, OSError, ValueError):
        return None, False
    if not isinstance(data, dict) or not data.get("access_token") or \
            isinstance(data.get("expires_in"), bool) or not isinstance(data.get("expires_in"), (int, float)):
        return None, False
    return data, False


def refresh_account(entry, account, now):
    """Refresh and save the token, returning the updated account, or None if not refreshed."""
    if not account.get("refresh_token"):
        return None
    if entry.get("refresh_rejected") == fingerprint(account["refresh_token"]):
        return None
    if now < entry.get("refresh_attempted_at", 0) + REFRESH_COOLDOWN:
        return None
    try:
        os.makedirs(os.path.dirname(REFRESH_LOCK), exist_ok=True)
        lock = open(REFRESH_LOCK, "w")
    except OSError:
        return None
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Claude Code may have refreshed it while we waited for the lock.
        current = read_source(account["key"])
        if current is None:
            return None
        if current["token"] != account["token"] and not needs_refresh(current, now):
            return dict(account, **current)
        if not current.get("refresh_token"):
            return None
        entry["refresh_attempted_at"] = now
        data, rejected = request_refresh(current)
        if data is None:
            if rejected:
                entry["refresh_rejected"] = fingerprint(current["refresh_token"])
            return None
        raw = current["raw"]
        oauth = raw["claudeAiOauth"]
        oauth["accessToken"] = data["access_token"]
        oauth["refreshToken"] = data.get("refresh_token") or current["refresh_token"]
        oauth["expiresAt"] = int((time.time() + data["expires_in"]) * 1000)
        if isinstance(data.get("refresh_token_expires_in"), (int, float)):
            oauth["refreshTokenExpiresAt"] = int((time.time() + data["refresh_token_expires_in"]) * 1000)
        if isinstance(data.get("scope"), str) and data["scope"].strip():
            oauth["scopes"] = data["scope"].split()
        saved = write_source(account["key"], raw)
        entry["refresh_error"] = None if saved else (
            "Could not save the refreshed token. Claude Code may need /login.")
        return dict(account, **parse_credentials(json.dumps(raw)))


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
    refreshed = False
    if needs_refresh(account, now):
        account = refresh_account(entry, account, now) or account
        refreshed = not needs_refresh(account, now)
    try:
        try:
            windows = fetch_usage(account["token"])
        except Unauthorized:
            # Rejected before its expiry time (e.g. revoked elsewhere): try one refresh.
            fresh = None if refreshed else refresh_account(entry, account, now)
            if fresh is None:
                raise
            account = fresh
            windows = fetch_usage(account["token"])
        entry["windows"] = windows
        entry["fetched_at"] = now
        entry["error"] = entry.get("refresh_error")
        entry["next_allowed"] = 0
    except UsageError as e:
        entry["error"] = str(e)
        if isinstance(e, Unauthorized) and account.get("refresh_token") and \
                entry.get("refresh_rejected") == fingerprint(account["refresh_token"]):
            entry["error"] = "Login expired. Run claude with this account and /login."
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
