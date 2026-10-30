"""Validate the persisted M2 ledger through a read-only SQLite connection."""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCAL = ROOT / "results" / "m2_local"


def validate(database_path, credentials_path):
    database_path = Path(database_path).resolve()
    credentials_path = Path(credentials_path).resolve()
    keys = json.loads(credentials_path.read_text(encoding="utf-8"))
    if not isinstance(keys, dict) or not keys:
        raise ValueError("Local credentials file is invalid.")
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        required = {"m2_organizations", "m2_developers", "m2_runs", "m2_attempts"}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required.issubset(tables):
            raise ValueError("M2 schema is incomplete.")
        organizations = {}
        all_visible = set()
        for organization_id, key in sorted(keys.items()):
            if not isinstance(key, str):
                raise ValueError("Local credentials file is invalid.")
            digest = hashlib.sha256(key.encode()).hexdigest()
            identity = connection.execute(
                "SELECT organization_id FROM m2_developers WHERE key_hash = ?", (digest,)
            ).fetchone()
            if identity is None or identity["organization_id"] != organization_id:
                raise ValueError(f"Credential mapping failed for {organization_id}.")
            runs = connection.execute(
                "SELECT id, partner_id FROM m2_runs WHERE organization_id = ? ORDER BY created_at, id",
                (organization_id,),
            ).fetchall()
            run_ids = [row["id"] for row in runs]
            overlap = all_visible.intersection(run_ids)
            if overlap:
                raise ValueError("Cross-tenant run visibility detected.")
            all_visible.update(run_ids)
            attempt_count = connection.execute(
                "SELECT COUNT(*) FROM m2_attempts a JOIN m2_runs r ON r.id = a.run_id WHERE r.organization_id = ?",
                (organization_id,),
            ).fetchone()[0]
            organizations[organization_id] = {"run_count": len(run_ids), "attempt_count": attempt_count, "run_ids": run_ids}
        total_runs = connection.execute("SELECT COUNT(*) FROM m2_runs").fetchone()[0]
        if total_runs != len(all_visible):
            raise ValueError("A persisted run is not visible to exactly one configured organization.")
        orphan_attempts = connection.execute(
            "SELECT COUNT(*) FROM m2_attempts a LEFT JOIN m2_runs r ON r.id = a.run_id WHERE r.id IS NULL"
        ).fetchone()[0]
        if orphan_attempts:
            raise ValueError("Orphan usage attempts detected.")
        return {"status": "ok", "read_only": True, "run_count": total_runs,
                "attempt_count": connection.execute("SELECT COUNT(*) FROM m2_attempts").fetchone()[0],
                "organizations": organizations}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_LOCAL / "platform.sqlite3")
    parser.add_argument("--credentials", type=Path, default=DEFAULT_LOCAL / "credentials.json")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.database, args.credentials), indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"M2 read-only validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
