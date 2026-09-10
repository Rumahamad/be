"""Explicit snapshot and offline integrity commands. No scheduled execution."""

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="BNC local recovery archive")
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Read business DB and download evidence")
    snapshot.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify an existing local archive offline")
    verify.add_argument("--archive", type=Path, required=True)
    process = commands.add_parser("process-next", help="Process one queued Drive backup")
    process.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args()
    from app.engines.backup.archive import verify_archive

    try:
        if args.command == "process-next":
            from app.services.backup_worker_service import BackupWorkerService
            result = BackupWorkerService().process_next(args.staging)
            if not result:
                print("No pending backup run.")
                return 0
            run_id, status = result
            print(f"Processed backup run: {run_id} ({status})")
            return 0 if status == "SUCCEEDED" else 1
        if args.command == "snapshot":
            from app.services.backup_snapshot_service import create_local_snapshot
            root = create_local_snapshot(args.output)
            print(f"Archive: {root}")
        else:
            root = args.archive
        print(json.dumps(verify_archive(root)))
        return 0
    except Exception as exc:
        # Never print SQLAlchemy/provider exception text: it may include credentials.
        print(f"Backup did not complete verification ({type(exc).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
