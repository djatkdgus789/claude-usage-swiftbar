"""Tests for swiftbar/claude-usage.1m.py.

Run with:  python3 -m unittest discover -s tests -v
No network access or real credentials are used: the keychain is replaced by a
fake `security` script and the API by a local HTTP server.
"""
import copy
import http.server
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "swiftbar", "claude-usage.1m.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "usage_response.json")

with open(FIXTURE, encoding="utf-8") as f:
    REAL_RESPONSE = json.load(f)


def load_plugin():
    spec = importlib.util.spec_from_file_location("claude_usage_plugin", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


plugin = load_plugin()


def fable_response(percent):
    data = copy.deepcopy(REAL_RESPONSE)
    for item in data["limits"]:
        if item["kind"] == "weekly_scoped":
            item["percent"] = percent
    return data


class ParsingTests(unittest.TestCase):
    def test_parse_date_variants(self):
        expected = 1791090000.0  # 2026-10-04T05:00:00Z
        for value in [
            "2026-10-04T05:00:00Z",
            "2026-10-04T05:00:00+00:00",
            "2026-10-04T14:00:00+09:00",
            "2026-10-04T05:00:00.000Z",
            "2026-10-04T05:00:00.000000+00:00",
        ]:
            self.assertAlmostEqual(plugin.parse_date(value), expected, places=2, msg=value)
        self.assertAlmostEqual(plugin.parse_date("2026-10-04T05:29:59.992470+00:00"), 1791091799.99247, places=3)
        self.assertIsNone(plugin.parse_date("garbage"))
        self.assertIsNone(plugin.parse_date(None))

    def test_real_response(self):
        windows = plugin.parse_windows(REAL_RESPONSE)
        self.assertEqual([w["id"] for w in windows], ["five_hour", "seven_day", "seven_day_model_fable"])
        fable = windows[2]
        self.assertEqual(fable["title"], "Weekly Fable")
        self.assertEqual(fable["utilization"], 0.0)
        self.assertIsNotNone(fable["resets_at"])
        self.assertTrue(plugin.is_fable(fable["id"]))

    def test_hides_codenames_and_disabled_entries(self):
        windows = plugin.parse_windows({
            "five_hour": {"utilization": 10, "resets_at": None},
            "iguana_necktie": {"utilization": 5, "resets_at": None},
            "tangelo": {"utilization": 5, "resets_at": None},
            "extra_usage": {"is_enabled": False, "utilization": 3},
            "seven_day_new_limit": {"utilization": 1, "resets_at": None},
        })
        self.assertEqual([w["id"] for w in windows], ["five_hour", "seven_day_new_limit"])

    def test_scoped_model_not_duplicated(self):
        data = {
            "seven_day_opus": {"utilization": 30, "resets_at": None},
            "limits": [
                {"kind": "weekly_scoped", "percent": 30, "scope": {"model": {"display_name": "Opus"}}},
                {"kind": "weekly_scoped", "percent": 12, "scope": {"model": {"display_name": "Fable"}}},
                {"kind": "weekly_scoped", "percent": 1, "scope": {"surface": "web"}},
                {"kind": "session", "percent": 50, "scope": None},
            ],
        }
        ids = [w["id"] for w in plugin.parse_windows(data)]
        self.assertEqual(ids, ["seven_day_opus", "seven_day_model_fable"])

    def test_parse_credentials(self):
        creds = plugin.parse_credentials('{"claudeAiOauth":{"accessToken":"t","subscriptionType":"max"}}')
        self.assertEqual(creds, {"token": "t", "plan": "max"})
        self.assertIsNone(plugin.parse_credentials("{}"))
        self.assertIsNone(plugin.parse_credentials('{"claudeAiOauth":{"accessToken":""}}'))
        self.assertIsNone(plugin.parse_credentials("not json"))

    def test_effective_resets_to_zero(self):
        w = {"utilization": 80.0, "resets_at": 1000.0}
        self.assertEqual(plugin.effective(w, 999), 80.0)
        self.assertEqual(plugin.effective(w, 1000), 0.0)
        self.assertEqual(plugin.effective({"utilization": 150.0, "resets_at": None}, 0), 100.0)

    def test_short_names(self):
        self.assertEqual(plugin.short_names([{"plan": "team"}, {"plan": "max"}]), ["T", "M"])
        self.assertEqual(plugin.short_names([{"plan": "max"}, {"plan": "max"}]), ["M1", "M2"])
        self.assertEqual(plugin.short_names([{}]), ["C"])

    def test_humanize(self):
        self.assertEqual(plugin.humanize(59), "0m")
        self.assertEqual(plugin.humanize(2 * 3600 + 15 * 60), "2h 15m")
        self.assertEqual(plugin.humanize(3 * 86400 + 4 * 3600), "3d 4h")


# ---------------------------------------------------------------- end to end

FAKE_SECURITY = r"""#!/bin/sh
case "$1" in
dump-keychain)
  printf '%s\n' 'class: "genp"' 'attributes:' '    "svce"<blob>="Claude Code-credentials"' \
                'class: "genp"' 'attributes:' '    "svce"<blob>="Claude Code-credentials-2c24b9db"' \
                'class: "genp"' 'attributes:' '    "svce"<blob>="Some Other App"';;
find-generic-password)
  case "$3" in
    "Claude Code-credentials") echo '{"claudeAiOauth":{"accessToken":"tok-max","subscriptionType":"max"}}';;
    "Claude Code-credentials-2c24b9db") echo '{"claudeAiOauth":{"accessToken":"tok-team","subscriptionType":"team"}}';;
    *) exit 44;;
  esac;;
*) exit 1;;
esac
"""


class FakeAPI(http.server.BaseHTTPRequestHandler):
    responses = {}  # token -> (status, body dict, headers)
    hits = []

    def do_GET(self):
        token = self.headers.get("Authorization", "").split(" ")[-1]
        FakeAPI.hits.append((self.path, token))
        status, body, headers = FakeAPI.responses.get(token, (404, {}, {}))
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if status == 200:
            self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), FakeAPI)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, ".claude"))
        self.security = os.path.join(self.tmp, "security")
        with open(self.security, "w") as f:
            f.write(FAKE_SECURITY)
        os.chmod(self.security, os.stat(self.security).st_mode | stat.S_IEXEC)
        FakeAPI.hits = []
        FakeAPI.responses = {
            "tok-max": (200, fable_response(37), {}),
            "tok-team": (200, REAL_RESPONSE, {}),
        }

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_plugin(self, **env):
        full_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.home,
            "CLAUDE_USAGE_API_BASE": "http://127.0.0.1:%d" % self.server.server_address[1],
            "CLAUDE_USAGE_SECURITY_BIN": self.security,
            "NO_PROXY": "127.0.0.1",
            "no_proxy": "127.0.0.1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        full_env.update(env)
        out = subprocess.run([sys.executable, PLUGIN], env=full_env, capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_two_accounts(self):
        # A credentials file with the same token as a keychain item must not add a third account.
        with open(os.path.join(self.home, ".claude", ".credentials.json"), "w") as f:
            f.write('{"claudeAiOauth":{"accessToken":"tok-max","subscriptionType":"max"}}')

        output = self.run_plugin()
        lines = output.splitlines()
        self.assertTrue(lines[0].startswith("M 0% · T 0%"), lines[0])
        self.assertIn("[M] Max | size=13", lines)
        self.assertIn("[T] Team | size=13", lines)
        self.assertEqual(output.count("5-hour session"), 2)
        self.assertIn("Weekly Fable   37%", output)
        self.assertIn("Weekly Fable   0%", output)
        self.assertNotIn("Iguana", output)
        self.assertNotIn("@", output)  # no account names / emails
        self.assertEqual(sorted(t for _, t in FakeAPI.hits), ["tok-max", "tok-team"])
        self.assertTrue(all(path == "/api/oauth/usage" for path, _ in FakeAPI.hits))

        # Fable row sits right below the weekly row
        weekly = next(i for i, l in enumerate(lines) if l.startswith("Weekly   2%"))
        self.assertTrue(lines[weekly + 3].startswith("Weekly Fable"), lines[weekly:weekly + 4])

    def test_no_korean_text(self):
        output = self.run_plugin()
        self.assertFalse(any("가" <= c <= "힣" for c in output), output)

    def test_rate_limit_backoff(self):
        self.run_plugin()
        FakeAPI.responses["tok-team"] = (429, {}, {"Retry-After": "120"})
        output = self.run_plugin(SWIFTBAR_PLUGIN_REFRESH_REASON="MenuAction")
        self.assertIn("Rate limited", output)
        self.assertIn("T 0%", output.splitlines()[0])  # cached value still shown

        FakeAPI.hits = []
        self.run_plugin()
        self.assertEqual([t for _, t in FakeAPI.hits], ["tok-max"])  # team account is backing off

        FakeAPI.hits = []
        FakeAPI.responses["tok-team"] = (200, REAL_RESPONSE, {})
        output = self.run_plugin(SWIFTBAR_PLUGIN_REFRESH_REASON="MenuAction")
        self.assertEqual(sorted(t for _, t in FakeAPI.hits), ["tok-max", "tok-team"])
        self.assertNotIn("Rate limited", output)

    def test_expired_token(self):
        FakeAPI.responses["tok-team"] = (401, {}, {})
        output = self.run_plugin()
        self.assertIn("Token expired", output)
        self.assertIn("⚠︎", output.splitlines()[0])

    def test_no_credentials(self):
        with open(self.security, "w") as f:
            f.write("#!/bin/sh\nexit 44\n")
        output = self.run_plugin()
        self.assertTrue(output.startswith("Claude ⚠︎"), output)
        self.assertIn("No Claude Code login found", output)
        self.assertEqual(FakeAPI.hits, [])


if __name__ == "__main__":
    unittest.main()
