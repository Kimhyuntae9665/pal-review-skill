"""Shared, stdlib-only resolution for portable and frozen session configurations."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "references" / "models.json"


def load_config(path=DEFAULT_CONFIG):
    """Resolve relative paths against the config, never the process cwd.

    Absolute runtime paths survive a rounds snapshot in another folder.
    {venv_python} is a fixed platform token, not environment interpolation.
    """
    location = Path(path).resolve()
    config = json.loads(location.read_text(encoding="utf-8-sig"))
    for name in ("pal_source", "pal_python"):
        value = config[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Runtime paths must be nonempty strings")
        value = value.replace("{venv_python}", "Scripts/python.exe" if os.name == "nt" else "bin/python")
        target = location.parent / Path(value)
        # Resolving a venv's final executable symlink can select the base Python
        # instead of the environment that owns its installed dependencies.
        resolved = target.parent.resolve() / target.name if name == "pal_python" else target.resolve()
        config[name] = str(resolved)
    config["_config_path"] = str(location)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--python", action="store_true", help="Print only the resolved runtime Python")
    args = parser.parse_args()
    config = load_config(args.config)
    print(config["pal_python"] if args.python else json.dumps(config, ensure_ascii=True))


if __name__ == "__main__":
    main()
