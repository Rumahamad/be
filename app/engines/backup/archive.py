"""Local artifact integrity. VERIFIED here means bytes only, never restore readiness."""

import gzip
import json
from pathlib import Path, PurePosixPath

from app.engines.backup.canonical import SCHEMA_VERSION, canonical_bytes, digest


def artifact_path(root: Path, relative: str) -> Path:
    parts = PurePosixPath(relative)
    if (not relative or parts.is_absolute() or "\\" in relative or ":" in relative
            or any(part in (".", "..") for part in relative.split("/"))):
        raise ValueError("Unsafe artifact path")
    target = root.joinpath(*parts.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact escapes archive directory")
    return target


def write_artifact(root: Path, name: str, content: bytes) -> dict:
    target = artifact_path(root, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(content)
    return {"path": name, "sha256": digest(content), "size_bytes": len(content)}


def write_dataset(root: Path, name: str, rows: list[dict]) -> dict:
    content = gzip.compress(canonical_bytes(rows), mtime=0)
    artifact = write_artifact(root, f"data/{name}.json.gz", content)
    return {**artifact, "record_count": len(rows)}


def finish_manifest(root: Path, metadata: dict, artifacts: list[dict]) -> None:
    content = canonical_bytes({
        **metadata, "schema_version": SCHEMA_VERSION,
        "restore_tested": False, "artifacts": artifacts,
    })
    write_artifact(root, "manifest.json", content)
    write_artifact(root, "manifest.sha256", (digest(content) + "\n").encode("ascii"))


def verify_archive(root: Path) -> dict:
    manifest_content = artifact_path(root, "manifest.json").read_bytes()
    expected = artifact_path(root, "manifest.sha256").read_text(encoding="ascii").strip()
    if digest(manifest_content) != expected:
        raise ValueError("Manifest checksum mismatch")
    manifest = json.loads(manifest_content)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported backup schema")
    seen, datasets, evidence = set(), {}, set()
    for artifact in manifest["artifacts"]:
        name = artifact["path"]
        if name in seen:
            raise ValueError("Duplicate artifact path")
        seen.add(name)
        content = artifact_path(root, name).read_bytes()
        if len(content) != artifact["size_bytes"] or digest(content) != artifact["sha256"]:
            raise ValueError(f"Artifact integrity failure: {name}")
        if "record_count" in artifact:
            records = json.loads(gzip.decompress(content))
            if not isinstance(records, list) or len(records) != artifact["record_count"]:
                raise ValueError(f"Record count mismatch: {name}")
            datasets[name] = records
        if "file_id" in artifact:
            if artifact["file_id"] in evidence:
                raise ValueError("Duplicate evidence file ID")
            evidence.add(artifact["file_id"])
    if manifest.get("errors") or manifest.get("status", "EXPORTED") != "EXPORTED":
        raise ValueError("Snapshot is incomplete; inspect manifest errors")
    schemas = manifest.get("table_schemas")
    if schemas is not None:
        verify_relations(schemas, datasets, evidence)
    return {"integrity": "PASSED", "artifacts": len(seen),
            "relations": "PASSED" if schemas is not None else "NOT_CHECKED",
            "restore_tested": False}


def verify_relations(schemas: dict, datasets: dict, evidence: set) -> None:
    """Check declared relational coverage, not financial rules or restorability."""
    if not schemas or set(datasets) != {f"data/{name}.json.gz" for name in schemas}:
        raise ValueError("Dataset inventory mismatch")
    tables = {name: datasets[f"data/{name}.json.gz"] for name in schemas}
    for name, schema in schemas.items():
        keys = set()
        for row in tables[name]:
            key = tuple(row[column] for column in schema["primary_key"])
            if not key or None in key or key in keys:
                raise ValueError(f"Invalid primary key: {name}")
            keys.add(key)
        for relation in schema["foreign_keys"]:
            targets = {tuple(row[column] for column in relation["target_columns"])
                       for row in tables[relation["target_table"]]}
            for row in tables[name]:
                key = tuple(row[column] for column in relation["columns"])
                # PostgreSQL MATCH SIMPLE: nullable references need no target.
                if None not in key and key not in targets:
                    raise ValueError(f"Missing referenced record: {name}")
    if "files" in tables:
        if {row["id"] for row in tables["files"]} != evidence:
            raise ValueError("Evidence inventory mismatch")
