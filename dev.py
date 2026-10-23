"""TenderBridge developer commands. Works the same on macOS, Linux and Windows.

    uv run python dev.py <command>        (or `make <command>` where make exists)

Run `uv run python dev.py help` for the list. Only uv is required; Docker is
needed only for the Postgres commands.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTAINER = "tenderbridge-db"
PG_USER = PG_DB = "tenderbridge"
PG_TEST_DB = "tenderbridge_test"


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _env_value(key: str, default: str | None = None) -> str | None:
    """Value from the process environment, then .env, then default."""
    if key in os.environ:
        return os.environ[key]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return v.strip()
    return default


def _pg_port() -> str:
    return _env_value("POSTGRES_PORT", "5433") or "5433"


def _pg_test_url() -> str:
    return f"postgresql+psycopg://{PG_USER}:{PG_USER}@localhost:{_pg_port()}/{PG_TEST_DB}"


def _run(*cmd: str, env: dict[str, str] | None = None, check: bool = True) -> int:
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})})
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result.returncode


def _py(*args: str, env: dict[str, str] | None = None) -> int:
    """Run Python inside the project's environment (we are already under `uv run`)."""
    return _run(sys.executable, *args, env=env)


def _require_docker() -> None:
    if shutil.which("docker") is None:
        sys.exit("Docker is not installed. Install Docker Desktop, or keep the default SQLite "
                 "DATABASE_URL in .env (no Docker needed).")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        sys.exit("Docker is installed but not running. Start Docker Desktop and retry.")


def _psql(sql: str, *, db: str = PG_DB, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", CONTAINER, "psql", "-U", PG_USER, "-d", db, "-tAc", sql],
                          capture_output=capture, text=True)


# --------------------------------------------------------------------------- #
# commands                                                                     #
# --------------------------------------------------------------------------- #
def cmd_env() -> None:
    """create .env from .env.example if missing"""
    env_file = ROOT / ".env"
    if env_file.exists():
        print(".env already exists")
        return
    shutil.copyfile(ROOT / ".env.example", env_file)
    print("created .env from .env.example (SQLite + fake LLMs; no keys needed)")


def cmd_setup() -> None:
    """install dependencies (uv sync) and create .env"""
    cmd_env()
    _run("uv", "sync")


def cmd_init_db() -> None:
    """create tables on DATABASE_URL (pgvector extension on Postgres)"""
    _py("-m", "backend.scripts.init_db")


def cmd_migrate() -> None:
    """apply Alembic migrations to DATABASE_URL"""
    _py("-m", "alembic", "upgrade", "head")


def cmd_seed() -> None:
    """create tables and seed structured company facts (idempotent)"""
    _py("-m", "backend.scripts.seed_company_facts")


def cmd_reset_db() -> None:
    """drop and recreate tables, then seed (destroys local data)"""
    _py("-m", "backend.scripts.init_db", "--drop")
    cmd_seed()


def cmd_test() -> None:
    """backend tests on a throwaway SQLite database"""
    _py("-m", "pytest")


def cmd_test_pg() -> None:
    """backend tests on the Postgres test database (starts Docker Postgres)"""
    cmd_db_up(quiet=True)
    exists = _psql(f"SELECT 1 FROM pg_database WHERE datname='{PG_TEST_DB}'", capture=True)
    if "1" not in (exists.stdout or ""):
        _psql(f"CREATE DATABASE {PG_TEST_DB}")
    _py("-m", "pytest", env={"TEST_DATABASE_URL": _pg_test_url()})


def cmd_lint() -> None:
    """ruff on backend, evals and dev.py"""
    _py("-m", "ruff", "check", "backend", "evals", "dev.py")


def cmd_typecheck() -> None:
    """mypy on backend/app"""
    _py("-m", "mypy", "backend/app")


def cmd_db_up(quiet: bool = False) -> None:
    """start Postgres 16 + pgvector in Docker (localhost:5433 by default)"""
    _require_docker()
    cmd_env()
    _run("docker", "compose", "up", "-d", "--wait", "db")
    url = _env_value("DATABASE_URL", "") or ""
    if not quiet and not url.startswith("postgresql"):
        print("\nnote: .env still uses SQLite. To use Postgres, uncomment the Postgres "
              "DATABASE_URL / CHECKPOINT_URL lines in .env (comment out the SQLite ones), then run\n"
              "      uv run python dev.py migrate && uv run python dev.py seed")


def cmd_db_down() -> None:
    """stop Postgres (data kept in the Docker volume)"""
    _require_docker()
    _run("docker", "compose", "down")


def cmd_db_psql() -> None:
    """open psql in the database container"""
    _require_docker()
    _run("docker", "exec", "-it", CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB, check=False)


def cmd_doctor() -> None:
    """check this machine: tools, Python, demo data integrity, .env, database"""
    problems: list[str] = []

    def ok(msg: str) -> None:
        print(f"  ok    {msg}")

    def bad(msg: str, fix: str) -> None:
        print(f"  FAIL  {msg}\n        fix: {fix}")
        problems.append(msg)

    def warn(msg: str) -> None:
        print(f"  warn  {msg}")

    print("TenderBridge doctor")
    v = sys.version_info
    if (v.major, v.minor) >= (3, 13):
        ok(f"Python {v.major}.{v.minor}.{v.micro} ({sys.executable})")
    else:
        bad(f"Python {v.major}.{v.minor} found, 3.13 required", "run through uv: `uv run python dev.py doctor`")
    if shutil.which("uv"):
        ok("uv found")
    else:
        bad("uv not found", "install uv: https://docs.astral.sh/uv/")
    try:
        import langgraph  # noqa: F401
        import sqlalchemy  # noqa: F401

        import backend.app.core.config  # noqa: F401
        ok("project dependencies importable")
    except ImportError as exc:
        bad(f"dependency missing: {exc.name}", "uv sync")

    # demo data: every file present with the hash recorded in its manifest
    checked, mismatched, missing = 0, [], []
    manifests = [
        (ROOT / "demo_data/demo_config/company_manifest.json", ROOT / "demo_data/company_kb",
         "documents", "file_path"),
        (ROOT / "demo_data/tender/TDR-001/manifest.json", ROOT / "demo_data/tender/TDR-001",
         "files", "file"),
    ]
    for manifest, base, key, path_key in manifests:
        if not manifest.exists():
            missing.append(str(manifest.relative_to(ROOT)))
            continue
        for entry in json.loads(manifest.read_text(encoding="utf-8")).get(key, []):
            f = base / entry[path_key]
            if not f.exists():
                missing.append(str(f.relative_to(ROOT)))
                continue
            checked += 1
            if entry.get("sha256") and hashlib.sha256(f.read_bytes()).hexdigest() != entry["sha256"]:
                mismatched.append(str(f.relative_to(ROOT)))
    if missing:
        bad(f"{len(missing)} demo data files missing (e.g. {missing[0]})", "git pull / re-clone the repo")
    elif mismatched:
        bad(f"{len(mismatched)} demo files changed since generation (e.g. {mismatched[0]})",
            "git checkout -- demo_data (check that .gitattributes is present)")
    else:
        ok(f"demo data intact ({checked} files match their manifest SHA-256)")

    if (ROOT / ".env").exists():
        ok(".env present")
    else:
        warn(".env missing: defaults apply (SQLite, fake LLMs). Create it with `uv run python dev.py env`")

    url = _env_value("DATABASE_URL", "sqlite (default)") or ""
    if url.startswith("postgresql"):
        if shutil.which("docker") is None:
            bad("DATABASE_URL is Postgres but Docker is not installed",
                "install Docker Desktop, or switch .env back to the SQLite DATABASE_URL")
        elif subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            bad("DATABASE_URL is Postgres but Docker is not running", "start Docker Desktop")
    try:
        from backend.app.db.engine import check_db
        info = check_db()
        if info.get("ok"):
            extra = " + pgvector" if info.get("pgvector") else ""
            ok(f"database reachable ({info['dialect']}{extra})")
        else:
            bad(f"database not reachable: {info.get('error', '')[:120]}",
                "`uv run python dev.py db-up` for Postgres, or use the SQLite DATABASE_URL")
    except Exception as exc:  # broken config should be reported, not crash the doctor
        bad(f"database check failed: {exc}", "check DATABASE_URL in .env")

    if not url.startswith("postgresql"):
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", int(_pg_port()))) == 0:
                warn(f"port {_pg_port()} is in use: fine if it is our Docker Postgres, otherwise set "
                     "POSTGRES_PORT in .env and use the same port in DATABASE_URL")

    print("\nall good" if not problems else f"\n{len(problems)} problem(s) found")
    sys.exit(1 if problems else 0)


COMMANDS: dict[str, Callable[[], None]] = {
    "setup": cmd_setup, "env": cmd_env, "doctor": cmd_doctor,
    "init-db": cmd_init_db, "migrate": cmd_migrate, "seed": cmd_seed, "reset-db": cmd_reset_db,
    "test": cmd_test, "test-pg": cmd_test_pg, "lint": cmd_lint, "typecheck": cmd_typecheck,
    "db-up": cmd_db_up, "db-down": cmd_db_down, "db-psql": cmd_db_psql,
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "help"
    if name not in COMMANDS:
        print(__doc__)
        for cmd, fn in COMMANDS.items():
            print(f"  {cmd:<10} {(fn.__doc__ or '').strip()}")
        sys.exit(0 if name in ("help", "-h", "--help") else 2)
    start = time.time()
    COMMANDS[name]()
    if name not in ("doctor", "db-psql"):
        print(f"done: {name} ({time.time() - start:.1f}s)")


if __name__ == "__main__":
    main()
