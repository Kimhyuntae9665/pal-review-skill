"""Install the pinned PAL runtime locally; never connect keys or call a model.

Python 3.11+ and Git are required. --check performs only read-only local checks.
All created files stay in REPO/.runtime; existing unknown/modified files are kept.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/BeehiveInnovations/pal-mcp-server.git"
PIN = "7afc7c1cc96e23992c8f105f960132c657883bb1"


class BootstrapError(RuntimeError):
    pass


def child_env():
    # Bootstrap needs package/source downloads, never provider/account credentials.
    env = {key: value for key, value in os.environ.items()
           if not any(word in key.upper() for word in ("API_KEY", "ACCESS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"))}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["PIP_NO_INPUT"] = "1"
    return env


def run(args, *, capture=False):
    result = subprocess.run([str(x) for x in args], check=True, env=child_env(),
                            stdout=subprocess.PIPE if capture else None,
                            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return result.stdout.strip() if capture else None


def git(source, *args):
    return run(["git", "-c", "credential.helper=", "-C", source, *args], capture=True)


def paths(repo):
    repo = Path(repo).resolve()
    runtime = repo / ".runtime"
    # No redirect through symlinks/junctions, including an existing venv/source.
    for part in (runtime, runtime / "pal-mcp-server", runtime / "venv"):
        if part.is_symlink() or part.resolve() != part:
            raise BootstrapError("Runtime paths must stay inside the chosen repository; links are not accepted.")
    return runtime, runtime / "pal-mcp-server", runtime / "venv"


def interpreter(venv):
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def fingerprint(repo):
    digest = hashlib.sha256()
    for name in ("requirements-runtime.txt", "references/runtime-lock.txt"):
        digest.update((repo / name).read_bytes())
    digest.update(PIN.encode("ascii"))
    return digest.hexdigest()


def validate_source(source):
    if not (source / ".git").is_dir() or not (source / "server.py").is_file():
        raise BootstrapError("PAL checkout is incomplete. Preserve/rename .runtime before a clean installation.")
    if git(source, "rev-parse", "HEAD") != PIN:
        raise BootstrapError("PAL commit differs from the public pin; existing files were preserved.")
    if git(source, "remote", "get-url", "origin") != UPSTREAM:
        raise BootstrapError("PAL origin differs from the official public source.")
    if git(source, "status", "--porcelain", "--untracked-files=no") or (source / ".env").exists():
        raise BootstrapError("PAL contains tracked edits or .env. Existing files were preserved.")


def validate_python(python, lock=None):
    if not python.is_file():
        raise BootstrapError("The managed virtual environment is incomplete.")
    run([python, "-c", "import importlib.metadata as m; import mcp,httpx,openai,google.genai,pydantic,dotenv; "
         "assert m.version('mcp') == '1.30.0'; assert m.version('pal-mcp-server') == '9.8.2'"])
    # Check installed constrained distributions as well as the MCP compatibility pin.
    # A constraints file does not require installing unrelated optional packages.
    code = """import importlib.metadata as m, pathlib, sys
for row in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8-sig').splitlines():
    spec = row.split(';', 1)[0].strip()
    if not spec or spec.startswith('#') or '==' not in spec:
        continue
    name, expected = spec.split('==', 1)
    if name == 'pywin32' and sys.platform != 'win32':
        continue
    try:
        actual = m.version(name)
    except m.PackageNotFoundError:
        continue
    assert actual == expected, f'{name}: {actual} differs from lock {expected}'
"""
    run([python, "-c", code, lock or ROOT / "references/runtime-lock.txt"])
    run([python, "-m", "pip", "--isolated", "check"], capture=True)


def check(repo):
    """Read-only checks: no mkdir, package install, network, keys, or inference."""
    repo = Path(repo).resolve()
    runtime, source, venv = paths(repo)
    result = {"python_supported": sys.version_info >= (3, 11), "git_available": shutil.which("git") is not None,
              "requirements_present": all((repo / x).is_file() for x in ("requirements-runtime.txt", "references/runtime-lock.txt")),
              "runtime_exists": runtime.exists(), "runtime_ready": False,
              "network_called": False, "inference_called": False}
    marker = runtime / "bootstrap.json"
    if runtime.exists():
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            if state != {"schema_version": 1, "pin": PIN, "fingerprint": fingerprint(repo), "state": "ready"}:
                raise BootstrapError("Unknown, incomplete, or changed managed runtime; preserve/rename it before reinstalling.")
            validate_source(source)
            validate_python(interpreter(venv), repo / "references/runtime-lock.txt")
            result["runtime_ready"] = True
        except (OSError, ValueError, BootstrapError, subprocess.CalledProcessError) as error:
            result["runtime_error"] = str(error)
    return result


def install(repo):
    repo = Path(repo).resolve()
    before = check(repo)
    if not all(before[key] for key in ("python_supported", "git_available", "requirements_present")):
        raise BootstrapError("Python 3.11+, Git, and this repository's requirement files are required.")
    runtime, source, venv = paths(repo)
    if before["runtime_ready"]:
        return {"status": "already_ready", "runtime": str(runtime), "inference_called": False, "network_called": False}
    if runtime.exists():
        raise BootstrapError(before.get("runtime_error", "Existing .runtime was preserved; rename it to a backup before reinstalling."))
    # mkdir is exclusive: a simultaneous install or preexisting runtime is refused.
    runtime.mkdir()
    marker = runtime / "bootstrap.json"
    state = {"schema_version": 1, "pin": PIN, "fingerprint": fingerprint(repo), "state": "installing"}
    marker.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    try:
        run(["git", "-c", "credential.helper=", "clone", "--no-checkout", "--filter=blob:none", UPSTREAM, source])
        git(source, "checkout", "--detach", PIN)
        validate_source(source)
        run([sys.executable, "-m", "venv", venv])
        python = interpreter(venv)
        run([python, "-m", "pip", "--isolated", "install", "--no-cache-dir", "-r", repo / "requirements-runtime.txt",
             "-c", repo / "references/runtime-lock.txt"])
        run([python, "-m", "pip", "--isolated", "install", "--no-cache-dir", "--no-deps", "--no-build-isolation", source])
        validate_source(source)
        validate_python(python, repo / "references/runtime-lock.txt")
        state["state"] = "ready"
        marker.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        # Never delete/reset a checkout or silently reuse an unfinished venv.
        print("Installation incomplete; .runtime was preserved. Rename it to a backup before retrying.", file=sys.stderr)
        raise
    return {"status": "installed", "runtime": str(runtime), "pin": PIN, "inference_called": False, "network_called": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT, help="Repository root; only its .runtime is created")
    parser.add_argument("--check", action="store_true", help="Read-only local prerequisite/runtime check")
    args = parser.parse_args()
    try:
        value = check(args.repo) if args.check else install(args.repo)
        print(json.dumps(value, indent=2))
        return 0
    except (OSError, ValueError, BootstrapError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "bootstrap_failed", "message": str(error), "inference_called": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
