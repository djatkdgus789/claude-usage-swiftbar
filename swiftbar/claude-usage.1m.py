#!/usr/bin/python3
# <xbar.title>Claude Usage</xbar.title>
# <xbar.version>v1.2</xbar.version>
# <xbar.desc>Claude 구독(Pro/Max/Team)의 5시간 세션 · 주간 사용량을 메뉴 막대에 표시합니다. 여러 계정 지원.</xbar.desc>
# <xbar.dependencies>python3, Claude Code (로그인 상태)</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.environment>[CLAUDE_FABLE_KEY=auto]</swiftbar.environment>
"""
Xcode 없이 쓰는 Claude 사용량 메뉴 막대 플러그인 (SwiftBar / xbar).

파일 이름의 `.1m.` 은 1분마다 실행된다는 뜻이다.
Claude Code 가 저장한 OAuth 토큰을 읽어 Claude Code 의 `/usage` 와 같은 엔드포인트를 조회한다.

여러 계정: Claude Code 를 계정마다 다른 설정 폴더로 로그인하면
(예: `CLAUDE_CONFIG_DIR=~/.claude-max claude` 후 `/login`) 키체인에
`Claude Code-credentials-…` 항목이 따로 생긴다. 이 플러그인은 그런 항목과
`~/.claude*/.credentials.json` 을 모두 찾아 계정별로 표시한다.
429(요청 한도 초과) 응답을 받으면 해당 계정은 캐시를 보여주며 잠시 쉰다.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_BASE = os.environ.get("CLAUDE_USAGE_API_BASE", "https://api.anthropic.com")
SECURITY = os.environ.get("CLAUDE_USAGE_SECURITY_BIN", "/usr/bin/security")
KEYCHAIN_PREFIX = "Claude Code-credentials"
CACHE_PATH = os.path.expanduser("~/Library/Caches/claude-usage-swiftbar.json")
DEFAULT_BACKOFF = 5 * 60
PROFILE_TTL = 24 * 3600

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
# 응답에는 내부 코드명 항목(예: iguana_necktie)이 섞여 올 수 있다.
# 알려진 한도와 5시간 / 주간 계열 키만 표시한다.
DISPLAY_PREFIXES = ("five_hour", "seven_day")


# 주간 줄 오른쪽에 보여줄 Fable 한도의 키. "auto" 면 이름에 fable 이 들어간 항목을 쓴다.
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
    """키체인에서 `Claude Code-credentials*` 서비스 이름을 모두 찾는다 (비밀 값은 읽지 않음)."""
    dump = run_security(["dump-keychain"]) or ""
    names = set(re.findall(r'"svce"<blob>="(%s[^"]*)"' % re.escape(KEYCHAIN_PREFIX), dump))
    names.add(KEYCHAIN_PREFIX)
    # 기본 항목을 먼저, 나머지는 이름순
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
    """[{key, source, token, plan}] — 같은 토큰은 한 번만."""
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
        if not isinstance(value, dict) or not is_displayed(key):
            continue
        util = value.get("utilization")
        if not isinstance(util, (int, float)) or isinstance(util, bool):
            continue
        if value.get("is_enabled") is False:
            continue
        windows.append({"id": key, "utilization": float(util), "resets_at": parse_date(value.get("resets_at"))})
    windows.sort(key=lambda w: (ORDER.index(w["id"]) if w["id"] in ORDER else len(ORDER), w["id"]))
    return windows


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
            raise UsageError("토큰이 만료되었습니다. 이 계정으로 claude 를 한 번 실행하면 갱신됩니다.")
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
        return json.loads(body)
    except ValueError:
        raise UsageError("사용량 응답을 해석할 수 없습니다.")


def fetch_usage(token):
    return parse_windows(api_get("/api/oauth/usage", token))


def fetch_profile_label(token):
    """계정 이메일 / 조직 이름 (실패하면 None). 계정 구분용이라 없어도 동작한다."""
    try:
        data = api_get("/api/oauth/profile", token)
    except UsageError:
        return None
    if not isinstance(data, dict):
        return None
    account = data.get("account") if isinstance(data.get("account"), dict) else {}
    org = data.get("organization") if isinstance(data.get("organization"), dict) else {}
    email = account.get("email") or account.get("email_address")
    org_name = org.get("name")
    if email and org_name and org_name not in email:
        return "%s · %s" % (email, org_name)
    return email or org_name


# ---------------------------------------------------------------- cache

def load_cache():
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {"accounts": {}}
    if not isinstance(cache.get("accounts"), dict):
        return {"accounts": {}}  # 이전 버전(단일 계정) 캐시는 버린다
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


def token_id(token):
    return hashlib.sha256(token.encode()).hexdigest()[:16]


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
    # 이메일 등 계정 이름은 하루에 한 번만 확인한다 (토큰이 바뀌면 다시)
    tid = token_id(account["token"])
    if entry.get("profile_token") != tid or now - entry.get("profile_checked", 0) > PROFILE_TTL:
        entry["label"] = fetch_profile_label(account["token"]) or entry.get("label")
        entry["profile_token"] = tid
        entry["profile_checked"] = now


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
        "Claude Code 로그인 정보를 찾을 수 없습니다. 터미널에서 claude 실행 후 /login 하세요.")
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
    if key not in TITLES and is_fable(key):
        return "주간 Fable"
    return TITLES.get(key, key.replace("_", " ").title())


def plan_name(entry):
    plan = entry.get("plan")
    return plan.capitalize() if plan else "Claude"


def short_names(entries):
    """메뉴 막대용 계정 약칭: 플랜 첫 글자(T, M, P …), 겹치면 번호를 붙인다."""
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
    """계정 하나의 메뉴 막대 요약 (5h 우선, 없으면 첫 한도)."""
    windows = entry.get("windows") or []
    if not windows:
        return None
    primary = next((w for w in windows if w["id"] == "five_hour"), windows[0])
    return effective(primary, now)


def render_full(w, now):
    pct = effective(w, now)
    out = [
        "%s   %d%% | color=%s" % (title(w["id"]), round(pct), color_for(pct)),
        "%s | font=Menlo size=11 color=%s" % (bar(pct), color_for(pct)),
    ]
    r = w.get("resets_at")
    if r and r > now:
        when = datetime.fromtimestamp(r).strftime("%m/%d %H:%M")
        out.append("%s 후 초기화 (%s) | size=11 color=gray" % (humanize(r - now), when))
    elif r:
        out.append("초기화됨 | size=11 color=gray")
    return out


# ---- 주간 줄을 세로로 반 나눠 왼쪽: 주간 전체, 오른쪽: 주간 Fable
SPLIT_BAR = 12
SPLIT_COL = 20  # 왼쪽 칸 표시 폭 (고정폭 글꼴 기준 칸 수)
ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[90m"


def text_width(text):
    """고정폭 글꼴에서 차지하는 칸 수 (한글 등 전각 문자는 2칸)."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def pad(text, width):
    return text + " " * max(0, width - text_width(text))


def ansi_for(pct):
    if pct >= 90:
        return "\033[91m"  # 빨강
    if pct >= 70:
        return "\033[33m"  # 주황(노랑)
    return ""


def paint(text, code):
    return code + text + ANSI_RESET if code else text


def split_cells(w, label, now):
    """(제목 줄, 막대 줄, 초기화 줄, 색) — 항목이 없으면 회색 자리 표시."""
    if w is None:
        return ("%s  –" % label, "·" * SPLIT_BAR, "응답에 없음", ANSI_DIM)
    pct = effective(w, now)
    r = w.get("resets_at")
    if r and r > now:
        reset = "↻ " + humanize(r - now)
    elif r:
        reset = "초기화됨"
    else:
        reset = ""
    return ("%s  %d%%" % (label, round(pct)), bar(pct, SPLIT_BAR), reset, ansi_for(pct))


def render_split(weekly, fable, now):
    left = split_cells(weekly, "주간 전체", now)
    right = split_cells(fable, "주간 Fable", now)
    out = []
    for i in range(3):
        l_text, r_text = left[i], right[i]
        l_code = left[3] if i < 2 else ANSI_DIM
        r_code = right[3] if i < 2 else ANSI_DIM
        line = paint(pad(l_text, SPLIT_COL), l_code) + "│ " + paint(r_text, r_code)
        out.append("%s | font=Menlo size=%d ansi=true trim=false" % (line, 12 if i == 0 else 11))
    return out


def render(cache, now):
    entries = [cache["accounts"][k] for k in cache.get("order", []) if k in cache["accounts"]]
    lines = []

    # ---- 메뉴 막대 제목
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

    # ---- 계정별 상세
    shorts = short_names(entries)
    for i, (short, e) in enumerate(zip(shorts, entries)):
        if i:
            lines.append("---")
        name = plan_name(e)
        if len(entries) > 1:
            name = "[%s] %s" % (short, name)
        lines.append("%s | size=13" % name)
        lines.append("%s | size=11 color=gray" % (e.get("label") or e.get("source", "")))
        windows = e.get("windows") or []
        fable = next((w for w in windows if is_fable(w["id"])), None)
        weekly = next((w for w in windows if w["id"] == "seven_day"), None)
        for w in windows:
            if w is fable and weekly is not None:
                continue  # 주간 줄 오른쪽 칸에 함께 표시
            if w is weekly:
                lines.extend(render_split(weekly, fable, now))
            else:
                lines.extend(render_full(w, now))
        if e.get("error"):
            lines.append("⚠︎ %s | color=#FF3B30 size=11" % e["error"])
        if e.get("fetched_at"):
            lines.append("업데이트: %s | size=11 color=gray"
                         % datetime.fromtimestamp(e["fetched_at"]).strftime("%H:%M:%S"))

    lines.append("---")
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
