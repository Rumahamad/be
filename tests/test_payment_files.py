from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies import current_user
from app.api.v1 import payments as payments_api
from app.db.session import get_db
from app.main import app
from app.models.enums import FileStatus
from app.schemas.payments import PaymentFileOutput
from app.services.payment_file_service import PaymentFileService
from app.services.storage_service import SupabaseStorageService


def test_payment_file_upload_route_forwards_raw_file(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid4())
    payment_id = uuid4()
    captured: dict[str, object] = {}

    class StubFileService:
        def upload(self, db, actor, requested_payment_id, **kwargs):
            captured.update(kwargs)
            captured["db"] = db
            captured["actor"] = actor
            captured["payment_id"] = requested_payment_id
            return PaymentFileOutput(
                id=uuid4(),
                original_name=kwargs["filename"],
                mime_type=kwargs["mime_type"],
                size_bytes=len(kwargs["content"]),
                revision_no=1,
            )

    monkeypatch.setattr(payments_api, "file_service", StubFileService())
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[current_user] = lambda: user
    try:
        response = TestClient(app).post(
            f"/api/v1/payments/{payment_id}/files?filename=receipt.png",
            content=b"png-bytes",
            headers={"Content-Type": "image/png"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert captured["payment_id"] == payment_id
    assert captured["actor"] is user
    assert captured["filename"] == "receipt.png"
    assert captured["mime_type"] == "image/png"
    assert captured["content"] == b"png-bytes"


def test_payment_file_download_route_returns_file(monkeypatch) -> None:
    payment_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    class StubFileService:
        def download(self, db, actor, requested_payment_id, requested_file_id):
            assert actor is user
            assert requested_payment_id == payment_id
            assert requested_file_id == file_id
            return b"jpeg-bytes", "image/jpeg", "receipt.jpg"

    monkeypatch.setattr(payments_api, "file_service", StubFileService())
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[current_user] = lambda: user
    try:
        response = TestClient(app).get(f"/api/v1/payments/{payment_id}/files/{file_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["content-disposition"] == 'inline; filename="receipt.jpg"'


def test_payment_file_download_unpacks_database_row(monkeypatch) -> None:
    payment_id = uuid4()
    file_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    payment = SimpleNamespace(id=payment_id, submitted_by=user.id)
    file_record = SimpleNamespace(
        id=file_id,
        status=FileStatus.ACTIVE,
        bucket_name="bnc-payment-files",
        object_key="payments/receipt.jpg",
        mime_type="image/jpeg",
        original_name="receipt.jpg",
    )
    payment_file = SimpleNamespace(file_id=file_id)

    class Result:
        def one_or_none(self):
            return payment_file, file_record, payment

    class Database:
        def execute(self, statement):
            return Result()

    class Storage:
        def download(self, bucket, object_key):
            assert bucket == "bnc-payment-files"
            assert object_key == "payments/receipt.jpg"
            return b"jpeg-bytes", "image/jpeg"

    content, media_type, filename = PaymentFileService(storage=Storage()).download(
        Database(), user, payment_id, file_id
    )

    assert content == b"jpeg-bytes"
    assert media_type == "image/jpeg"
    assert filename == "receipt.jpg"


def test_storage_delete_uses_bucket_remove_endpoint(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )
    calls: dict[str, object] = {}

    class Response:
        is_success = True

    def fake_request(method, url, **kwargs):
        calls.update(method=method, url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr("httpx.request", fake_request)
    SupabaseStorageService(settings=settings).delete("bnc-payment-files", "payments/receipt.jpg")

    assert calls["method"] == "DELETE"
    assert calls["url"] == "https://example.supabase.co/storage/v1/object/bnc-payment-files"
    assert calls["kwargs"]["json"] == {"prefixes": ["payments/receipt.jpg"]}


def test_storage_bootstrap_creates_missing_private_bucket(monkeypatch) -> None:
    settings = SimpleNamespace(
        supabase_url="https://example.supabase.co",
        supabase_admin_api_key="sb_secret_service-key",
    )
    calls: list[tuple[str, str, dict]] = []

    class Response:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self.is_success = 200 <= status_code < 300
            self._payload = payload

        def json(self):
            return self._payload

    responses = [
        Response(400, {"statusCode": "404", "code": "NoSuchBucket"}),
        Response(200, {}),
    ]

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return responses.pop(0)

    service = SupabaseStorageService(settings=settings)
    monkeypatch.setattr(service, "_request", fake_request)

    assert service.ensure_private_bucket(
        "bnc-payment-files",
        max_file_bytes=5 * 1024 * 1024,
        allowed_mime_types=["image/jpeg", "image/png", "image/webp"],
    )
    assert calls[1] == (
        "POST",
        "/storage/v1/bucket",
        {
            "json": {
                "id": "bnc-payment-files",
                "name": "bnc-payment-files",
                "public": False,
                "file_size_limit": 5 * 1024 * 1024,
                "allowed_mime_types": ["image/jpeg", "image/png", "image/webp"],
            }
        },
    )


def test_storage_bootstrap_leaves_existing_bucket_unchanged(monkeypatch) -> None:
    service = SupabaseStorageService(
        settings=SimpleNamespace(
            supabase_url="https://example.supabase.co",
            supabase_admin_api_key="sb_secret_service-key",
        )
    )

    class Response:
        status_code = 200
        is_success = True

    monkeypatch.setattr(service, "_request", lambda *args, **kwargs: Response())
    assert not service.ensure_private_bucket(
        "bnc-payment-files",
        max_file_bytes=1024,
        allowed_mime_types=["image/png"],
    )
