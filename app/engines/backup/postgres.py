"""Postgres tooling: credentials go through the child environment, never argv or logs."""
import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url


def pg_environment(database_url):
    url = make_url(database_url)
    return {**os.environ, "PGHOST": url.host or "127.0.0.1", "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "", "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database or "", "PGCONNECT_TIMEOUT": "10",
        "PGSSLMODE": str(url.query.get("sslmode", "prefer"))}


def run_pg(bin_dir, command, args, database_url=None):
    executable = Path(bin_dir).resolve() / (command + (".exe" if os.name == "nt" else ""))
    # pg_ctl's detached server can inherit pipe handles on Windows. Files avoid
    # waiting forever for the long-running server to close subprocess pipes.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run([str(executable), *map(str, args)],
            check=False,
            env=pg_environment(database_url) if database_url else None,
            stdout=output, stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise RuntimeError(f"{command} failed (exit {result.returncode})")
        output.seek(0)
        return output.read()


def dump_database(settings, snapshot=None):
    args = ["--format=custom", "--schema=public", "--no-owner", "--no-acl"]
    if snapshot:
        args.append(f"--snapshot={snapshot}")
    return run_pg(settings.postgres_bin, "pg_dump", args, settings.database_url)


def restore_database(bin_dir, dump_path, database_url):
    # Fresh PostgreSQL databases already contain public. Keep its safe default
    # ownership and omit only the redundant CREATE SCHEMA entry from the archive.
    listing = run_pg(bin_dir, "pg_restore", ["--list", dump_path]).decode()
    listing = "\n".join(line for line in listing.splitlines() if " SCHEMA - public " not in line)
    with tempfile.TemporaryDirectory() as directory:
        toc = Path(directory) / "restore.list"
        toc.write_text(listing, encoding="utf-8")
        run_pg(bin_dir, "pg_restore", ["--no-owner", "--no-acl", "--exit-on-error",
            "--single-transaction", "--use-list", toc,
            "--dbname=" + make_url(database_url).database, dump_path], database_url)
