from app.config.settings import get_settings
from app.services.payment_file_service import ALLOWED_MIME_TYPES
from app.services.storage_service import StorageService


def main() -> None:
    settings = get_settings()
    created = StorageService(settings).ensure_private_bucket(
        settings.storage_bucket,
        max_file_bytes=settings.storage_max_file_bytes,
        allowed_mime_types=sorted(ALLOWED_MIME_TYPES),
    )
    state = "created" if created else "already configured"
    print(f"Private storage bucket '{settings.storage_bucket}' is {state}.")


if __name__ == "__main__":
    main()
