"""Manage a workspace-local PostgreSQL instance, listening only on loopback."""
import argparse
import json
import secrets
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from app.engines.backup.postgres import run_pg

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
BIN = LOCAL / "postgresql" / "pgsql" / "bin"
DATA = LOCAL / "pgdata"
CREDENTIALS = LOCAL / "postgres.json"


def local_url(credentials, *, application=True, database="bnc"):
    return URL.create("postgresql+psycopg", username="bnc_app" if application else "bnc_owner",
        password=credentials["app_password" if application else "owner_password"],
        host="127.0.0.1", port=credentials["port"], database=database).render_as_string(hide_password=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "start", "stop", "status"])
    parser.add_argument("--port", type=int, default=55432)
    args = parser.parse_args()
    LOCAL.mkdir(exist_ok=True)
    if args.command == "init":
        if DATA.exists() or CREDENTIALS.exists():
            raise RuntimeError("Local instance already exists; use start")
        credentials = {"port": args.port, "owner_password": secrets.token_urlsafe(36),
                       "app_password": secrets.token_urlsafe(36)}
        password_file = LOCAL / "init-password.tmp"
        password_file.write_text(credentials["owner_password"], encoding="utf-8")
        try:
            run_pg(BIN, "initdb", ["-D", DATA, "-U", "bnc_owner", "-A", "scram-sha-256",
                "--pwfile", password_file, "--encoding=UTF8", "--locale=C"])
        finally:
            password_file.unlink(missing_ok=True)
        with (DATA / "postgresql.conf").open("a", encoding="utf-8") as stream:
            stream.write(f"\nlisten_addresses = '127.0.0.1'\nport = {args.port}\n")
        CREDENTIALS.write_text(json.dumps(credentials), encoding="utf-8")
    if args.command in {"init", "start"}:
        run_pg(BIN, "pg_ctl", ["-D", DATA, "-l", LOCAL / "postgres.log", "-w", "start"])
    elif args.command == "stop":
        run_pg(BIN, "pg_ctl", ["-D", DATA, "-m", "fast", "-w", "stop"])
    else:
        run_pg(BIN, "pg_ctl", ["-D", DATA, "status"])
    if args.command == "init":
        engine = create_engine(local_url(credentials, application=False, database="postgres"),
                               isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            # Generated URL-safe passwords contain no SQL quoting characters.
            connection.execute(text("CREATE ROLE bnc_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                "PASSWORD '" + credentials["app_password"] + "'"))
            connection.execute(text('CREATE DATABASE bnc OWNER bnc_app'))
        engine.dispose()
    print(f"Local PostgreSQL: {args.command} completed")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- CLI must not expose connection credentials.
        print(f"Local PostgreSQL operation failed ({type(exc).__name__}): {exc}" if
              isinstance(exc, RuntimeError) else f"Local PostgreSQL operation failed ({type(exc).__name__})")
        raise SystemExit(1)
