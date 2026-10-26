"""Temporary loopback-only password entry; saves Windows DPAPI credentials without inference."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading

PROVIDERS = ("gemini", "groq", "openrouter")
MAX_BODY = 12288
MAX_KEY = 8192
# Only this static script is passed as a subprocess argument. Secret input is stdin.
STORAGE_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# The Codex shell can export a different PowerShell runtime's module path.
# Use this child runtime's signed built-in modules without weakening validation.
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
try {
    [Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
    $entry = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($entry.provider -notin @('gemini','groq','openrouter')) { throw 'Invalid input' }
    if ($entry.key -isnot [string] -or $entry.key.Length -eq 0 -or $entry.key.Length -gt 8192) { throw 'Invalid input' }
    if ($entry.provider -in @('gemini','groq') -and $entry.confirmed -ne $true) { throw 'Invalid input' }
    $directory = Join-Path $env:LOCALAPPDATA 'CodexPalReview'
    $target = Join-Path $directory ($entry.provider + '.credential.xml')
    if (Test-Path -LiteralPath $target) { Write-Output '{"saved":false,"exists":true}'; exit 0 }
    $username = if ($entry.provider -eq 'openrouter') { 'openrouter' } else { $entry.provider + '-free' }
    $secure = ConvertTo-SecureString -String $entry.key -AsPlainText -Force
    $credential = [pscredential]::new($username, $secure)
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $credential | Export-Clixml -LiteralPath $target -NoClobber
    Remove-Variable entry,secure,credential
    Write-Output '{"saved":true,"exists":false}'
} catch {
    Write-Output '{"saved":false,"exists":false}'
    exit 1
}
'''


class DPAPIStorage:
    def __init__(self):
        if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
            raise RuntimeError("Windows DPAPI is required.")
        self.root = Path(os.environ["LOCALAPPDATA"]) / "CodexPalReview"

    def exists(self, provider):
        return provider in PROVIDERS and (self.root / (provider + ".credential.xml")).exists()

    def save(self, provider, key, confirmed):
        if provider not in PROVIDERS or self.exists(provider):
            return {"saved": False, "exists": provider in PROVIDERS and self.exists(provider)}
        encoded = base64.b64encode(STORAGE_SCRIPT.encode("utf-16-le")).decode("ascii")
        try:
            result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                input=json.dumps({"provider": provider, "key": key, "confirmed": confirmed}, ensure_ascii=False).encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
            value = json.loads(result.stdout.decode("utf-8-sig").strip())
            return {"saved": result.returncode == 0 and value.get("saved") is True,
                    "exists": value.get("exists") is True}
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
            return {"saved": False, "exists": False}


PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>PAL local API key setup</title><style nonce="NONCE">body{font:17px system-ui;max-width:700px;margin:40px auto;padding:20px}label{display:block;margin:18px 0}input[type=password],select,button{font:inherit;padding:9px}input[type=password]{width:95%}small{display:block}pre{white-space:pre-wrap}</style>
<h1>PAL local API key setup</h1><p>This page stores your key on this Windows account using DPAPI. No API request is made. Existing credentials cannot be read or replaced here.</p>
<pre id="presence"></pre><form id="entry" autocomplete="off"><label>Provider <select id="provider" name="provider"><option value="gemini">Google Gemini</option><option value="groq">Groq</option><option value="openrouter">OpenRouter</option></select></label>
<label>API key <input id="key" name="key" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" maxlength="8192" required></label>
<label><input id="confirmed" name="confirmed" type="checkbox"> I checked this provider's Free plan and confirmed paid billing is disabled (required for Google and Groq).</label>
<button type="submit">Save encrypted key locally</button></form><p id="result" role="status"></p>
<script nonce="NONCE">const endpoint=location.pathname;const token=TOKEN;const entry=document.getElementById('entry');
async function presence(){const r=await fetch(endpoint+'/status',{cache:'no-store'});const s=await r.json();document.getElementById('presence').textContent=Object.entries(s.present||{}).map(([p,v])=>p+': '+(v?'stored':'not stored')).join('\n');}
entry.addEventListener('submit',async e=>{e.preventDefault();const field=document.getElementById('key');const button=entry.querySelector('button');button.disabled=true;
try{const r=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json','X-Setup-Token':token},body:JSON.stringify({provider:document.getElementById('provider').value,key:field.value,confirmed:document.getElementById('confirmed').checked})});field.value='';const s=await r.json();document.getElementById('result').textContent=s.saved?'Encrypted key saved locally. No API request was made.':s.status==='already_exists'?'A credential already exists; it was not replaced.':s.status==='free_confirmation_required'?'Confirm the Free plan with paid billing disabled first.':'Key was not saved.';await presence();}catch(e){document.getElementById('result').textContent='Local setup unavailable; no success confirmed.';}finally{field.value='';button.disabled=false;}});presence();</script></html>'''


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, storage, lifetime=900):
        if not 1 <= lifetime <= 1800:
            raise ValueError("Lifetime must be between 1 and 1800 seconds.")
        self.storage = storage
        self.path_nonce = "/" + secrets.token_urlsafe(24)
        self.csrf = secrets.token_urlsafe(32)
        self.script_nonce = secrets.token_urlsafe(20)
        self.save_lock = threading.Lock()
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=lifetime)
        super().__init__(("127.0.0.1", 0), SetupHandler)
        self.expected_host = f"127.0.0.1:{self.server_port}"
        self.origin = "http://" + self.expected_host
        self.url = self.origin + self.path_nonce
        self.expiry_timer = threading.Timer(lifetime, self.shutdown)
        self.expiry_timer.daemon = True

    def start_expiry(self):
        self.expiry_timer.start()

    def handle_error(self, request, client_address):
        # Never emit request data, exception details, or credential-bearing locals.
        pass


class SetupHandler(BaseHTTPRequestHandler):
    server_version = "LocalSetup"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"saved": False, "status": "request_rejected"})

    def respond(self, code, value, html=False):
        # Consume only a bounded declared body on early rejection, avoiding a
        # Windows TCP reset that could hide the generic error response.
        if getattr(self, "command", None) == "POST" and not getattr(self, "body_consumed", False):
            self.body_consumed = True
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) == 1 and len(lengths[0]) <= 6 and lengths[0].isascii()
                    and lengths[0].isdigit() and 0 < int(lengths[0]) <= MAX_BODY):
                try:
                    self.rfile.read(int(lengths[0]))
                except OSError:
                    pass
        body = value.encode("utf-8") if html else json.dumps(value).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'nonce-" + self.server.script_nonce +
            "'; style-src 'nonce-" + self.server.script_nonce + "'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host_path(self, status=False):
        hosts = self.headers.get_all("Host", [])
        accepted = [self.server.path_nonce]
        if status:
            accepted.append(self.server.path_nonce + "/status")
        return (hosts == [self.server.expected_host] and self.path in accepted
                and datetime.now(timezone.utc) < self.server.expires_at)

    def do_GET(self):
        if not self.valid_host_path(status=True):
            return self.respond(404, {"status": "not_found"})
        if self.path.endswith("/status"):
            return self.respond(200, {"present": {provider: bool(self.server.storage.exists(provider)) for provider in PROVIDERS}})
        page = PAGE.replace("NONCE", self.server.script_nonce).replace("TOKEN", json.dumps(self.server.csrf))
        self.respond(200, page, html=True)

    def do_POST(self):
        if not self.valid_host_path():
            return self.respond(404, {"saved": False, "status": "not_found"})
        if self.headers.get_all("Origin", []) != [self.server.origin] or self.headers.get_all("X-Setup-Token", []) != [self.server.csrf]:
            return self.respond(403, {"saved": False, "status": "request_rejected"})
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get_all("Transfer-Encoding") or len(lengths) != 1
                or len(lengths[0]) > 6 or not lengths[0].isascii() or not lengths[0].isdigit()):
            return self.respond(400, {"saved": False, "status": "request_rejected"})
        size = int(lengths[0])
        if size <= 0 or size > MAX_BODY:
            return self.respond(413, {"saved": False, "status": "request_rejected"})
        if self.headers.get_all("Content-Type", []) != ["application/json"]:
            return self.respond(415, {"saved": False, "status": "request_rejected"})
        try:
            self.body_consumed = True
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError()
            entry = json.loads(raw.decode("utf-8"))
            provider, key, confirmed = entry["provider"], entry["key"], entry.get("confirmed", False)
            if provider not in PROVIDERS or not isinstance(key, str) or not isinstance(confirmed, bool):
                raise ValueError()
            key = key.strip()
            if not key or len(key) > MAX_KEY or any(character.isspace() or ord(character) < 32 for character in key):
                raise ValueError()
        except (ValueError, TypeError, KeyError, UnicodeError, OSError):
            return self.respond(400, {"saved": False, "status": "request_rejected"})
        if provider != "openrouter" and not confirmed:
            return self.respond(400, {"saved": False, "status": "free_confirmation_required"})
        with self.server.save_lock:
            if self.server.storage.exists(provider):
                return self.respond(409, {"saved": False, "status": "already_exists"})
            try:
                result = self.server.storage.save(provider, key, confirmed)
            except Exception:
                result = {"saved": False, "exists": False}
        key = None
        entry = None
        if result.get("saved"):
            self.respond(200, {"saved": True, "status": "stored"})
        else:
            self.respond(409 if result.get("exists") else 500,
                         {"saved": False, "status": "already_exists" if result.get("exists") else "storage_failed"})

    def do_OPTIONS(self):
        self.respond(405, {"saved": False, "status": "request_rejected"})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-file", required=True, help="New absolute local startup status JSON path; contains no API key")
    parser.add_argument("--lifetime-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    server = None
    try:
        path = Path(args.status_file)
        if not path.is_absolute() or not 1 <= args.lifetime_seconds <= 1800:
            raise ValueError()
        server = SetupServer(DPAPIStorage(), args.lifetime_seconds)
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"url": server.url, "pid": os.getpid(), "expires_at": server.expires_at.isoformat(),
                       "present": {provider: server.storage.exists(provider) for provider in PROVIDERS}}, stream)
        print(json.dumps({"url": server.url, "pid": os.getpid()}), flush=True)
        server.start_expiry()
        server.serve_forever(poll_interval=0.2)
    except (OSError, ValueError, RuntimeError):
        print("Local credential setup unavailable.", file=sys.stderr)
        return 1
    finally:
        if server:
            server.expiry_timer.cancel()
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
