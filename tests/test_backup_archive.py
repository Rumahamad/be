"""Offline recovery integrity checks; no provider, database or real member data."""

from datetime import UTC, datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

from app.engines.backup.archive import (
    artifact_path, finish_manifest, verify_archive, write_dataset,
)
from app.engines.backup.canonical import canonical_bytes, money_minor
from app.engines.backup.layout import month_folder, weekly_folder


class BackupArchiveTests(unittest.TestCase):
    def test_exact_money(self):
        self.assertEqual(money_minor(Decimal("1500.00")), 150000)
        for amount in (Decimal("0.001"), Decimal("NaN"), 1.5):
            with self.assertRaises(ValueError):
                money_minor(amount)

    def test_canonical_order_and_precision(self):
        self.assertEqual(canonical_bytes({"b": 2, "a": Decimal("0.10")}),
                         canonical_bytes({"a": Decimal("0.10"), "b": 2}))
        with self.assertRaises(ValueError):
            canonical_bytes({"amount": 0.1})

    def test_paths(self):
        with TemporaryDirectory() as directory:
            for path in ("../secret", "C:/secret", "/etc/passwd", "a\\b", "a/../b"):
                with self.assertRaises(ValueError):
                    artifact_path(Path(directory), path)
        self.assertEqual(str(month_folder(2026, 9)), "BNC_BACKUP/02_ARCHIVE/2026/09_September")
        self.assertIn("2020-W53", str(weekly_folder(datetime(2021, 1, 1, tzinfo=UTC), "run")))

    def test_corruption_detected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = write_dataset(root, "payments", [{"id": "fixture", "amount": "500.00"}])
            finish_manifest(root, {"errors": []}, [artifact])
            self.assertEqual(verify_archive(root)["integrity"], "PASSED")
            self.assertFalse(verify_archive(root)["restore_tested"])
            with (root / artifact["path"]).open("ab") as stream:
                stream.write(b"corrupt")
            with self.assertRaises(ValueError):
                verify_archive(root)

    def test_partial_archive_cannot_pass(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            finish_manifest(root, {"errors": [{"file_id": "missing"}]}, [])
            with self.assertRaises(ValueError):
                verify_archive(root)


if __name__ == "__main__":
    unittest.main()
