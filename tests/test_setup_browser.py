"""Loopback HTTP checks with fake storage; no real keys, providers, or DPAPI writes."""
import base64
from datetime import datetime, timedelta, timezone
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_browser.py"
spec = importlib.util.spec_from_file_location("setup_browser", SCRIPT)
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeStorage:
    def __init__(self):
        self.present = set()
        self.saved = []

    def exists(self, provider):
        return provider in self.present

    def save(self, provider, key, confirmed):
        self.saved.append((provider, key, confirmed))
        self.present.add(provider)
        return {"saved": True, "exists": False}


class SetupHTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeStorage()
        self.server = setup.SetupServer(self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method="GET", path=None, entry=None, headers=None, raw=None):
        headers = {"Host": self.server.expected_host, **(headers or {})}
        body = raw
        if entry is not None:
            body = json.dumps(entry)
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path or self.server.path_nonce, body=body, headers=headers)
        response = connection.getresponse()
        value = response.read().decode("utf-8")
        result = response.status, dict(response.getheaders()), value
        connection.close()
        return result

    def post(self, entry=None, **changes):
        headers = {"Origin": self.server.origin, "X-Setup-Token": self.server.csrf, "Content-Type": "application/json"}
        headers.update(changes.pop("headers", {}))
        return self.request("POST", entry=entry or {"provider": "gemini", "key": "synthetic-test-value", "confirmed": True}, headers=headers, **changes)

    def test_loopback_password_page_and_security_headers(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, body = self.request()
        self.assertEqual(status, 200)
        self.assertIn('type="password"', body)
        self.assertIn('autocomplete="off"', body)
        self.assertIn("field.value=''", body)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store, max-age=0")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertNotIn("https://", body)

    def test_served_browser_script_has_valid_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is unavailable; served JavaScript syntax requires a Node check.")
        status, _, body = self.request()
        self.assertEqual(status, 200)
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", body, re.DOTALL)
        self.assertEqual(len(scripts), 1)
        self.assertIn(".join('\\n')", scripts[0])
        result = subprocess.run([node, "--check"], input=scripts[0], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_status_presence_only(self):
        self.store.present.add("groq")
        status, _, body = self.request(path=self.server.path_nonce + "/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"present": {"gemini": False, "groq": True, "openrouter": False}})
        self.assertNotIn("key", body)

    def test_valid_post_saves_only_allowlisted_value_no_echo(self):
        status, _, body = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(self.store.saved, [("gemini", "synthetic-test-value", True)])
        self.assertNotIn("synthetic-test-value", body)
        self.assertEqual(json.loads(body), {"saved": True, "status": "stored"})

    def test_free_confirmation_and_openrouter_rule(self):
        for provider in ("gemini", "groq"):
            status, _, body = self.post({"provider": provider, "key": "synthetic-test-value", "confirmed": False})
            self.assertEqual(status, 400)
            self.assertEqual(json.loads(body)["status"], "free_confirmation_required")
        self.assertEqual(self.store.saved, [])
        status, _, _ = self.post({"provider": "openrouter", "key": "synthetic-test-value", "confirmed": False})
        self.assertEqual(status, 200)

    def test_existing_credential_is_not_overwritten_or_loaded(self):
        self.store.present.add("gemini")
        status, _, body = self.post()
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["status"], "already_exists")
        self.assertEqual(self.store.saved, [])

    def test_host_origin_token_path_restrictions(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Origin": "null"}, {"Origin": ""}, {"X-Setup-Token": "wrong"}):
            status, _, _ = self.post(headers=headers)
            self.assertIn(status, (403, 404))
        for path in ("/", self.server.path_nonce + "?query=1", self.server.path_nonce + "/status", "http://evil.example" + self.server.path_nonce):
            status, _, _ = self.post(path=path)
            self.assertEqual(status, 404)
        self.assertEqual(self.store.saved, [])

    def test_body_bounds_and_content_type(self):
        headers = {"Origin": self.server.origin, "X-Setup-Token": self.server.csrf, "Content-Type": "application/json"}
        status, _, _ = self.request("POST", raw="x" * (setup.MAX_BODY + 1), headers=headers)
        self.assertEqual(status, 413)
        status, _, _ = self.post(headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 415)

    def test_invalid_json_provider_key_and_confirmation_types(self):
        entries = [{"provider": "../outside", "key": "safe", "confirmed": True},
                   {"provider": "gemini", "key": "x" * (setup.MAX_KEY + 1), "confirmed": True},
                   {"provider": "gemini", "key": "", "confirmed": True},
                   {"provider": "gemini", "key": "contains\nnewline", "confirmed": True},
                   {"provider": "gemini", "key": "safe", "confirmed": "true"},
                   {"provider": "gemini", "key": 123, "confirmed": True}]
        for entry in entries:
            status, _, body = self.post(entry)
            self.assertEqual(status, 400)
            self.assertNotIn("safe", body)
        self.assertEqual(self.store.saved, [])

    def test_storage_exception_is_not_disclosed(self):
        with patch.object(self.store, "save", side_effect=RuntimeError("synthetic-private-value")):
            status, _, body = self.post()
        self.assertEqual(status, 500)
        self.assertNotIn("synthetic-private-value", body)

    def test_expired_server_rejects_requests_and_lifetime_is_bounded(self):
        self.server.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        status, _, _ = self.post()
        self.assertEqual(status, 404)
        self.assertEqual(self.store.saved, [])
        for lifetime in (0, 1801):
            with self.assertRaises(ValueError):
                setup.SetupServer(FakeStorage(), lifetime)

    def test_preflight_has_no_cors_headers_or_storage(self):
        status, headers, _ = self.request("OPTIONS")
        self.assertEqual(status, 405)
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.store.saved, [])


class StorageTests(unittest.TestCase):
    def storage(self):
        # Construct without requiring the host OS or touching actual storage.
        value = object.__new__(setup.DPAPIStorage)
        value.root = Path(self.tmp.name)
        return value

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_secret_only_piped_stdin_and_static_script_no_temporary_files(self):
        store = self.storage()
        returned = subprocess.CompletedProcess([], 0, b'{"saved":true,"exists":false}')
        with patch.object(setup.subprocess, "run", return_value=returned) as run:
            result = store.save("groq", "synthetic-private-value", True)
        self.assertEqual(result, {"saved": True, "exists": False})
        args, kwargs = run.call_args
        self.assertNotIn("synthetic-private-value", repr(args))
        self.assertEqual(json.loads(kwargs["input"]), {"provider": "groq", "key": "synthetic-private-value", "confirmed": True})
        decoded_script = base64.b64decode(args[0][-1]).decode("utf-16-le")
        self.assertEqual(decoded_script, setup.STORAGE_SCRIPT)
        self.assertIn("-NoClobber", decoded_script)
        self.assertIn("'-free'", decoded_script)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_storage_does_not_replace_existing_or_accept_invalid_provider(self):
        store = self.storage()
        target = store.root / "gemini.credential.xml"
        target.write_text("encrypted-placeholder", encoding="utf-8")
        with patch.object(setup.subprocess, "run") as run:
            self.assertEqual(store.save("gemini", "unused", True), {"saved": False, "exists": True})
            self.assertFalse(store.save("../elsewhere", "unused", True)["saved"])
        run.assert_not_called()
        self.assertEqual(target.read_text(encoding="utf-8"), "encrypted-placeholder")

    def test_subprocess_failure_never_exposes_exception_or_payload(self):
        with patch.object(setup.subprocess, "run", side_effect=subprocess.TimeoutExpired("static", 20, output=b"synthetic-private-value")):
            result = self.storage().save("openrouter", "synthetic-private-value", False)
        self.assertEqual(result, {"saved": False, "exists": False})

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is required for this isolated synthetic credential check.")
    def test_real_windows_dpapi_roundtrip_in_temporary_localappdata(self):
        dummy = "SYNTHETIC-DUMMY-NOT-A-REAL-API-KEY"
        # Point every credential operation at a fresh temporary directory. An
        # unrelated inherited module path must not affect Windows PowerShell.
        environment = {"LOCALAPPDATA": self.tmp.name,
                       "PSModulePath": str(Path(self.tmp.name) / "foreign-runtime-modules")}
        verify_script = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json
$path = [IO.Path]::Combine($env:LOCALAPPDATA, 'CodexPalReview', $inputData.provider + '.credential.xml')
$credential = Import-Clixml -LiteralPath $path
$expectedUser = if ($inputData.provider -eq 'openrouter') { 'openrouter' } else { $inputData.provider + '-free' }
@{credential_type=($credential -is [pscredential]); username_matches=($credential.UserName -eq $expectedUser); password_matches=($credential.GetNetworkCredential().Password -ceq $inputData.expected)} | ConvertTo-Json -Compress
'''
        encoded = base64.b64encode(verify_script.encode("utf-16-le")).decode("ascii")
        with patch.dict(os.environ, environment):
            store = setup.DPAPIStorage()
            for provider in setup.PROVIDERS:
                result = store.save(provider, dummy, provider != "openrouter")
                self.assertEqual(result, {"saved": True, "exists": False})
                target = Path(self.tmp.name) / "CodexPalReview" / (provider + ".credential.xml")
                before = target.read_bytes()
                self.assertNotIn(dummy.encode("utf-8"), before)
                verified = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                    input=json.dumps({"provider": provider, "expected": dummy}).encode("utf-8"),
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(verified.returncode, 0)
                self.assertEqual(json.loads(verified.stdout.decode("utf-8-sig")),
                                 {"credential_type": True, "username_matches": True, "password_matches": True})
                self.assertEqual(store.save(provider, "OTHER-SYNTHETIC-DUMMY", True), {"saved": False, "exists": True})
                self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
