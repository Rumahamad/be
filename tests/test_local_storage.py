from types import SimpleNamespace

import pytest

from app.services.storage_service import LocalStorageService, StorageError


@pytest.fixture
def storage(tmp_path):
    return LocalStorageService(SimpleNamespace(local_storage_root=str(tmp_path), storage_max_file_bytes=50))


@pytest.mark.parametrize("bucket,key", [("../outside", "file"), ("bnc", "../file"),
    ("bnc", "C:/secret"), ("bnc", "a\\secret"), ("bnc", "/secret"),
    ("bnc", "CON.txt"), ("bnc", "a/./b"), ("bnc", "a//b"), ("bnc", "a. /b")])
def test_rejects_unsafe_paths(storage, bucket, key):
    with pytest.raises(StorageError):
        storage.upload(bucket, key, b"private", "image/png")


def test_private_roundtrip_and_no_overwrite(storage):
    storage.upload("bnc", "payments/a.png", b"original", "image/png")
    assert storage.download("bnc", "payments/a.png") == (b"original", "image/png")
    with pytest.raises(StorageError):
        storage.upload("bnc", "payments/a.png", b"replacement", "image/png")
    assert storage.download("bnc", "payments/a.png")[0] == b"original"
    storage.delete("bnc", "payments/a.png")
    with pytest.raises(StorageError):
        storage.download("bnc", "payments/a.png")


def test_size_limit(storage):
    with pytest.raises(StorageError):
        storage.upload("bnc", "a.png", b"x" * 51, "image/png")
