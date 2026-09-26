#!/usr/bin/env python3
"""Entry point of the wikipedia-interest-trends skill.

    python scripts/wt.py analyze --topic "Astronomy" --langs uk --pdf
    python scripts/wt.py --help

Dependencies: the analysis core is pure standard library. Charts and PDF need
matplotlib + reportlab; on first use they are installed (hash-pinned, from
requirements.lock) into a private folder next to the cache, not into the
system Python. ``python scripts/wt.py setup`` does this explicitly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOCK = ROOT / "requirements.lock"
NEEDS_DEPS = {"analyze", "report", "doctor", "setup"}

if sys.version_info < (3, 10):
    sys.exit(f"wikitrends needs Python 3.10+ (found {sys.version.split()[0]}). Try `python3.11 scripts/wt.py ...`.")


def _home() -> Path:
    explicit = os.environ.get("WIKITRENDS_HOME")
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".cache") / "wikitrends"


def _site_dir() -> Path:
    tag = hashlib.sha256(LOCK.read_bytes()).hexdigest()[:10]
    return _home() / f"site-py{sys.version_info[0]}{sys.version_info[1]}-{tag}"


def _deps_importable() -> bool:
    try:
        import matplotlib  # noqa: F401
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def _install(target: Path) -> bool:
    print(f"[wikitrends] one-time setup: installing pinned matplotlib + reportlab into {target} "
          "(~30-60 s)...", file=sys.stderr, flush=True)
    tmp = target.with_name(f"{target.name}.partial-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    commands = []
    if uv:
        commands.append([uv, "pip", "install", "--quiet", "--python", sys.executable, "--target", str(tmp),
                         "--require-hashes", "-r", str(LOCK)])
    commands.append([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                     "--no-warn-script-location", "--target", str(tmp), "--require-hashes", "-r", str(LOCK)])
    for cmd in commands:
        try:
            subprocess.run(cmd, check=True, stdout=sys.stderr)
            (tmp / ".wikitrends-ready").write_text("ok", encoding="utf-8")
            try:
                tmp.rename(target)  # atomic; loses harmlessly if a parallel run finished first
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
                if not (target / ".wikitrends-ready").exists():
                    raise
            print("[wikitrends] dependencies ready", file=sys.stderr, flush=True)
            return True
        except (subprocess.CalledProcessError, OSError) as exc:
            print(f"[wikitrends] install attempt failed: {exc}", file=sys.stderr, flush=True)
            shutil.rmtree(tmp, ignore_errors=True)
    print("[wikitrends] could not install chart/PDF dependencies; text analysis still works. "
          "Check network access to pypi.org or install matplotlib and reportlab manually.", file=sys.stderr)
    return False


def ensure_deps(install: bool) -> bool:
    target = _site_dir()
    if (target / ".wikitrends-ready").exists():
        sys.path.insert(0, str(target))
        return _deps_importable()
    if _deps_importable():
        return True
    if not install or os.environ.get("WIKITRENDS_NO_INSTALL"):
        return False
    if _install(target):
        sys.path.insert(0, str(target))
        return _deps_importable()
    return False


def main() -> int:
    argv = sys.argv[1:]
    command = next((a for a in argv if not a.startswith("-")), None)
    ok = ensure_deps(install=command in NEEDS_DEPS)
    if command == "setup":
        print("dependencies OK" if ok else "dependencies NOT installed (see messages above)")
        return 0 if ok else 4
    sys.path.insert(0, str(HERE))
    from wikitrends.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
