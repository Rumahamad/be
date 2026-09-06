from app.config.settings import get_settings
from app.services.payment_file_service import ALLOWED_MIME_TYPES
from app.services.storage_service import SupabaseStorageService


def main() -> None:
    settings = get_settings()
    created = SupabaseStorageService(settings).ensure_private_bucket(
        settings.supabase_storage_bucket,
        max_file_bytes=settings.storage_max_file_bytes,
        allowed_mime_types=sorted(ALLOWED_MIME_TYPES),
    )
    state = "created" if created else "already configured"
    print(f"Supabase Storage bucket '{settings.supabase_storage_bucket}' is {state}.")


if __name__ == "__main__":
    main()
