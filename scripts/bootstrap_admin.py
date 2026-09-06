import argparse
import getpass

from app.db.session import SessionLocal
from app.services.admin_bootstrap_service import (
    AdminBootstrapError,
    AdminBootstrapInput,
    AdminBootstrapService,
)
from app.services.supabase_admin_service import SupabaseAdminError


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first approved BNC administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--member-code", default="BNC-001")
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name")
    parser.add_argument("--mobile")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    password = getpass.getpass("Initial password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match")
        return 1
    if len(password) < 8:
        print("Password must contain at least 8 characters")
        return 1

    payload = AdminBootstrapInput(
        email=args.email,
        password=password,
        member_code=args.member_code,
        first_name=args.first_name,
        last_name=args.last_name,
        mobile=args.mobile,
    )
    try:
        with SessionLocal() as db:
            user = AdminBootstrapService().create_first_admin(db, payload)
    except (AdminBootstrapError, SupabaseAdminError) as exc:
        print(f"Bootstrap failed: {exc}")
        return 1
    print(f"Created BNC administrator {user.display_name} ({user.member_code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
