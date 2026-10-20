import os
import secrets
from pathlib import Path

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config.settings import Settings
from app.engines.backup.archive import verify_archive
from app.services import backup_snapshot_service
from app.services.local_recovery_service import verify_local_recovery
from scripts.restore_local_backup import restore


def test_encrypted_backup_restore_roundtrip(monkeypatch, tmp_path):
    source_url = os.environ.get("BNC_TEST_DATABASE_URL")
    target_url = os.environ.get("BNC_TEST_RESTORE_URL")
    if not source_url or not target_url:
        pytest.skip("Provide disposable local source and empty restore databases")
    for url in (source_url, target_url):
        parsed = make_url(url)
        assert parsed.host in {"127.0.0.1", "localhost"} and parsed.database.startswith("bnc_test_")
    assert source_url != target_url
    engine = create_engine(source_url)
    from app.db.session import Base
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num varchar(32) PRIMARY KEY)"))
        if not connection.scalar(text("SELECT count(*) FROM alembic_version")):
            connection.execute(text("INSERT INTO alembic_version VALUES ('0022_local_auth')"))
    settings = Settings(_env_file=None, database_url=source_url,
        local_auth_secret=secrets.token_urlsafe(48), backup_encryption_key=Fernet.generate_key().decode(),
        auth_provider="local", storage_provider="LOCAL", local_storage_root=str(tmp_path / "storage"),
        postgres_bin=str(Path(".local/postgresql/pgsql/bin").resolve()))
    monkeypatch.setattr(backup_snapshot_service, "engine", engine)
    monkeypatch.setattr(backup_snapshot_service, "get_settings", lambda: settings)
    root = backup_snapshot_service.create_local_snapshot(tmp_path / "snapshot")
    assert verify_archive(root)["integrity"] == "PASSED"
    assert verify_local_recovery(root, settings)["integrity"] == "PASSED"
    bad_key = settings.model_copy(update={"backup_encryption_key": Fernet.generate_key().decode()})
    with pytest.raises(InvalidToken):
        verify_local_recovery(root, bad_key)
    target_settings = settings.model_copy(update={"database_url": target_url,
        "local_storage_root": str(tmp_path / "restored-storage")})
    result = restore(root, target_settings, tmp_path / "restored.env.local")
    assert result["sessions_revoked"] and not result["active_configuration_changed"]
    target_engine = create_engine(target_url)
    with engine.connect() as src, target_engine.connect() as dst:
        for table in ("users", "roles", "local_auth_identities", "files"):
            assert src.scalar(text(f'SELECT count(*) FROM {table}')) == dst.scalar(text(f'SELECT count(*) FROM {table}'))
        assert dst.scalar(text("SELECT count(*) FROM local_auth_sessions WHERE revoked_at IS NULL")) == 0
        assert dst.scalar(text("SELECT count(*) FROM local_auth_tokens WHERE consumed_at IS NULL")) == 0
    # Even if an attacker rewrites the plain checksum, the encrypted seal detects it.
    content = (root / "manifest.json").read_bytes()
    (root / "manifest.json").write_bytes(content + b" ")
    with pytest.raises(ValueError, match="Authenticated"):
        verify_local_recovery(root, settings)
    engine.dispose(); target_engine.dispose()
