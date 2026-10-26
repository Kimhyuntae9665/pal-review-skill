"""Portable configuration, installer preservation, and wrapper regression tests."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap
import pal_review
from runtime_config import load_config


class PortableConfigTests(unittest.TestCase):
    def test_default_paths_stay_in_repository_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
            config = load_config(ROOT / "references" / "models.json")
        self.assertEqual(Path(config["pal_source"]), ROOT / ".runtime" / "pal-mcp-server")
        self.assertEqual(Path(config["pal_python"]), bootstrap.interpreter(ROOT / ".runtime" / "venv"))
        self.assertNotIn("C:/Users/", (ROOT / "references" / "models.json").read_text())

    def test_relative_custom_paths_and_rounds_snapshot_have_same_meaning(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "configs" / "models.json"
            original.parent.mkdir()
            value = json.loads((ROOT / "references" / "models.json").read_text())
            value["pal_source"] = "../runtime/PAL"
            value["pal_python"] = "../runtime/venv/{venv_python}"
            original.write_text(json.dumps(value))
            resolved = pal_review.read_config(original)
            snapshot = root / "session-config.json"
            snapshot.write_text(json.dumps(resolved))
            frozen = pal_review.read_config(snapshot)
            self.assertEqual(frozen["pal_source"], resolved["pal_source"])
            self.assertEqual(frozen["pal_python"], resolved["pal_python"])
            self.assertEqual(frozen["_config_path"], str(snapshot))
            route = frozen["profiles"]["free"][0]
            with patch.dict(os.environ, {route["key_env"]: "offline-test-value"}):
                env = pal_review.launcher_env(frozen, route["id"])
            self.assertEqual(env["PAL_REVIEW_CONFIG_PATH"], str(snapshot))
            self.assertEqual(env["PAL_REVIEW_SOURCE"], resolved["pal_source"])

    def test_missing_runtime_doctor_remains_read_only(self):
        config = load_config(ROOT / "references" / "models.json")
        with tempfile.TemporaryDirectory() as folder:
            config["pal_source"] = str(Path(folder) / "missing-source")
            config["pal_python"] = str(Path(folder) / "missing-python")
            result = pal_review.doctor(config)
            self.assertFalse(result["ready_for_live_review"])
            self.assertFalse(result["checks"]["pal_source_exists"])
            self.assertFalse(result["checks"]["inference_called"])
            self.assertFalse(result["checks"]["network_called"])
            self.assertEqual(list(Path(folder).iterdir()), [])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell is needed for wrapper cross-check")
    def test_wrapper_uses_custom_config_python_and_does_not_touch_real_store(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = json.loads((ROOT / "references" / "models.json").read_text())
            value["pal_python"] = sys.executable
            config = root / "models.json"
            config.write_text(json.dumps(value))
            environment = dict(os.environ)
            environment["LOCALAPPDATA"] = str(root / "empty-store")
            for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
                environment.pop(key, None)
            result = subprocess.run(["pwsh", "-NoLogo", "-NoProfile", "-File", str(ROOT / "scripts" / "pal-review.ps1"),
                                     "--config", str(config), "doctor"], env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["checks"]["python"], sys.executable)
            self.assertFalse((root / "empty-store").exists())


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / "references").mkdir()
        for name in ("requirements-runtime.txt", "references/runtime-lock.txt"):
            (self.repo / name).write_bytes((ROOT / name).read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def test_check_does_not_create_runtime_or_call_network(self):
        with patch.object(bootstrap, "run") as run:
            result = bootstrap.check(self.repo)
        run.assert_not_called()
        self.assertFalse(result["runtime_exists"])
        self.assertFalse(result["network_called"])
        self.assertFalse((self.repo / ".runtime").exists())

    def test_existing_unknown_runtime_and_backups_are_preserved(self):
        runtime = self.repo / ".runtime"
        runtime.mkdir()
        sentinel = runtime / "keep.txt"
        sentinel.write_text("Keep user data")
        backup = self.repo / ".runtime-backup"
        backup.mkdir()
        (backup / "old.txt").write_text("Previous runtime")
        with patch.object(bootstrap, "run") as run, self.assertRaises(bootstrap.BootstrapError):
            bootstrap.install(self.repo)
        run.assert_not_called()
        self.assertEqual(sentinel.read_text(), "Keep user data")
        self.assertEqual((backup / "old.txt").read_text(), "Previous runtime")

    def test_ready_runtime_is_idempotent_no_clone_or_install(self):
        runtime = self.repo / ".runtime"
        runtime.mkdir()
        state = {"schema_version": 1, "pin": bootstrap.PIN, "fingerprint": bootstrap.fingerprint(self.repo), "state": "ready"}
        marker = runtime / "bootstrap.json"
        marker.write_text(json.dumps(state))
        before = marker.read_bytes()
        with patch.object(bootstrap, "validate_source"), patch.object(bootstrap, "validate_python"), patch.object(bootstrap, "run") as run:
            result = bootstrap.install(self.repo)
        run.assert_not_called()
        self.assertEqual(result["status"], "already_ready")
        self.assertEqual(marker.read_bytes(), before)

    def test_failed_install_keeps_partial_runtime_and_retry_refuses(self):
        with patch.object(bootstrap, "run", side_effect=subprocess.CalledProcessError(1, "git")):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.install(self.repo)
        state = json.loads((self.repo / ".runtime" / "bootstrap.json").read_text())
        self.assertEqual(state["state"], "installing")
        with patch.object(bootstrap, "run") as run, self.assertRaises(bootstrap.BootstrapError):
            bootstrap.install(self.repo)
        run.assert_not_called()

    def test_source_pin_dirty_and_origin_are_enforced(self):
        _, source, _ = bootstrap.paths(self.repo)
        source.mkdir(parents=True)
        (source / ".git").mkdir()
        (source / "server.py").write_text("# fixture")
        for outputs in (("wrong-pin",), (bootstrap.PIN, "https://example.invalid/other"), (bootstrap.PIN, bootstrap.UPSTREAM, " M server.py")):
            with patch.object(bootstrap, "git", side_effect=outputs), self.assertRaises(bootstrap.BootstrapError):
                bootstrap.validate_source(source)
        with patch.object(bootstrap, "git", side_effect=[bootstrap.PIN, bootstrap.UPSTREAM, ""]):
            bootstrap.validate_source(source)

    def test_install_uses_only_official_pin_and_isolated_venv(self):
        commands = []
        def fake_run(args, **kwargs):
            commands.append([str(x) for x in args])
        with patch.object(bootstrap, "run", side_effect=fake_run), patch.object(bootstrap, "git") as git, \
                patch.object(bootstrap, "validate_source"), patch.object(bootstrap, "validate_python"):
            result = bootstrap.install(self.repo)
        self.assertEqual(result["status"], "installed")
        self.assertIn(bootstrap.UPSTREAM, commands[0])
        git.assert_called_once_with(self.repo / ".runtime" / "pal-mcp-server", "checkout", "--detach", bootstrap.PIN)
        self.assertEqual(commands[1][:3], [sys.executable, "-m", "venv"])
        self.assertIn("--isolated", commands[2])
        self.assertIn("--no-deps", commands[3])
        self.assertEqual(json.loads((self.repo / ".runtime" / "bootstrap.json").read_text())["state"], "ready")


if __name__ == "__main__":
    unittest.main()
