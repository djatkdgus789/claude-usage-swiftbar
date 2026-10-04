#!/usr/bin/python3
# <xbar.title>Claude Usage</xbar.title>
# <xbar.version>v1.0</xbar.version>
# <xbar.desc>Claude 구독(Pro/Max)의 5시간 세션 · 주간 사용량을 메뉴 막대에 표시합니다.</xbar.desc>
# <xbar.dependencies>python3, Claude Code (로그인 상태)</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
"""
Xcode 없이 쓰는 Claude 사용량 메뉴 막대 플러그인 (SwiftBar / xbar).

파일 이름의 `.1m.` 은 1분마다 실행된다는 뜻이다.
Claude Code 가 키체인에 저장한 OAuth 토큰을 읽어 Claude Code 의 `/usage` 와
같은 엔드포인트를 조회한다. 429(요청 한도 초과) 응답을 받으면 캐시를 보여주며 잠시 쉰다.
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

ENDPOINT = os.environ.get("CLAUDE_USAGE_ENDPOINT", "https://api.anthropic.com/api/oauth/usage")
KEYCHAIN_SERVICE = "Claude Code-credentials"
CACHE_PATH = os.path.expanduser("~/Library/Caches/claude-usage-swiftbar.json")
DEFAULT_BACKOFF = 5 * 60

TITLES = {
    "five_hour": "5시간 세션",
    "seven_day": "주간 한도",
    "seven_day_sonnet": "주간 Sonnet",
    "seven_day_opus": "주간 Opus",
    "seven_day_oauth_apps": "주간 OAuth 앱",
    "extra_usage": "추가 사용량",
}
ORDER = list(TITLES)
SHORT = {"five_hour": "5h", "seven_day": "7d"}

CLAUDE_ORANGE = "#D97757"


class UsageError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


# ---------------------------------------------------------------- credentials

def read_keychain():
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else None


def parse_credentials(text):
    try:
        oauth = json.loads(text)["claudeAiOauth"]
        token = oauth["accessToken"]
    except (ValueError, KeyError, TypeError):
        return None
    if not token:
        return None
    return {"token": token, "plan": oauth.get("subscriptionType")}


def load_credentials():
    raw = read_keychain()
    if raw:
        creds = parse_credentials(raw)
        if creds:
            return creds
    dirs = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        dirs.append(os.path.expanduser(os.environ["CLAUDE_CONFIG_DIR"]))
    dirs.append(os.path.expanduser("~/.claude"))
    for d in dirs:
        try:
            with open(os.path.join(d, ".credentials.json"), encoding="utf-8") as f:
                creds = parse_credentials(f.read())
        except OSError:
            continue
        if creds:
            return creds
    raise UsageError("Claude Code 로그인 정보를 찾을 수 없습니다. 터미널에서 claude 실행 후 /login 하세요.")


# ---------------------------------------------------------------- API

def parse_date(value):
    """ISO8601 문자열 → epoch 초. Python 3.9 의 fromisoformat 제약(Z, 소수점 자릿수)을 보완한다."""
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
        raise UsageError("사용량 응답을 해석할 수 없습니다.")
    windows = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        util = value.get("utilization")
        if not isinstance(util, (int, float)) or isinstance(util, bool):
            continue
        if value.get("is_enabled") is False:
            continue
        windows.append({"id": key, "utilization": float(util), "resets_at": parse_date(value.get("resets_at"))})
    windows.sort(key=lambda w: (ORDER.index(w["id"]) if w["id"] in ORDER else len(ORDER), w["id"]))
    return windows


def fetch(token):
    req = urllib.request.Request(ENDPOINT, headers={
        "Authorization": "Bearer " + token,
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": "claude-usage-swiftbar/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise UsageError("토큰이 만료되었습니다. 터미널에서 claude 를 한 번 실행하면 갱신됩니다.")
        if e.code == 429:
            retry = e.headers.get("Retry-After") if e.headers else None
            try:
                retry = float(retry) if retry else None
            except ValueError:
                retry = None
            raise UsageError("요청이 너무 잦아 잠시 후 다시 시도합니다.", retry_after=retry or DEFAULT_BACKOFF)
        raise UsageError("HTTP %d 오류" % e.code)
    except (urllib.error.URLError, OSError) as e:
        raise UsageError("네트워크 오류: %s" % getattr(e, "reason", e))
    try:
        return parse_windows(json.loads(body))
    except ValueError:
        raise UsageError("사용량 응답을 해석할 수 없습니다.")


# ---------------------------------------------------------------- cache

def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_cache(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def update(now, force=False):
    """API 를 조회해 캐시를 갱신하고 캐시를 돌려준다."""
    cache = load_cache()
    if not force and now < cache.get("next_allowed", 0):
        return cache
    try:
        creds = load_credentials()
        if creds.get("plan"):
            cache["plan"] = creds["plan"]
        cache["windows"] = fetch(creds["token"])
        cache["fetched_at"] = now
        cache["error"] = None
        cache["next_allowed"] = 0
    except UsageError as e:
        cache["error"] = str(e)
        if e.retry_after:
            cache["next_allowed"] = now + e.retry_after
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
        return "%d일 %d시간" % (days, hours)
    if hours:
        return "%d시간 %d분" % (hours, mins)
    return "%d분" % mins


def title(key):
    return TITLES.get(key, key.replace("_", " ").title())


def render(cache, now):
    windows = cache.get("windows") or []
    error = cache.get("error")
    lines = []

    # 메뉴 막대 제목
    if windows:
        parts = []
        for w in windows:
            if w["id"] in SHORT:
                parts.append("%s %d%%" % (SHORT[w["id"]], round(effective(w, now))))
        if not parts:
            parts.append("%d%%" % round(effective(windows[0], now)))
        worst = max(effective(w, now) for w in windows)
        head = " · ".join(parts)
        if error:
            head += " ⚠︎"
        attrs = "sfimage=gauge.with.dots.needle.50percent"
        if worst >= 90:
            attrs += " color=#FF3B30"
        lines.append("%s | %s" % (head, attrs))
    else:
        lines.append("Claude ⚠︎ | sfimage=gauge.with.dots.needle.0percent" if error else "Claude …")

    lines.append("---")
    plan = cache.get("plan")
    lines.append("Claude 사용량%s | size=13" % ("  ·  " + plan.capitalize() if plan else ""))

    for w in windows:
        pct = effective(w, now)
        lines.append("---")
        lines.append("%s   %d%% | color=%s" % (title(w["id"]), round(pct), color_for(pct)))
        lines.append("%s | font=Menlo size=11 color=%s" % (bar(pct), color_for(pct)))
        r = w.get("resets_at")
        if r and r > now:
            when = datetime.fromtimestamp(r).strftime("%m/%d %H:%M")
            lines.append("%s 후 초기화 (%s) | size=11 color=gray" % (humanize(r - now), when))
        elif r:
            lines.append("초기화됨 | size=11 color=gray")

    lines.append("---")
    if error:
        lines.append("⚠︎ %s | color=#FF3B30 size=11" % error)
    fetched = cache.get("fetched_at")
    if fetched:
        lines.append("업데이트: %s | size=11 color=gray" % datetime.fromtimestamp(fetched).strftime("%H:%M:%S"))
    lines.append("지금 새로고침 | refresh=true sfimage=arrow.clockwise")
    lines.append("claude.ai 사용량 열기 | href=https://claude.ai/settings/usage sfimage=safari")
    return "\n".join(lines)


def main():
    now = time.time()
    # SwiftBar 의 '새로고침' 메뉴는 백오프를 무시하도록 한다.
    force = os.environ.get("SWIFTBAR_PLUGIN_REFRESH_REASON") == "MenuAction"
    print(render(update(now, force=force), now))


if __name__ == "__main__":
    sys.exit(main())
