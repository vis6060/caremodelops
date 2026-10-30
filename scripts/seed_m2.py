"""Seed fictional tenants and save local credentials without printing them."""
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chartground.platform_m2.database import LOCAL, database
from chartground.platform_m2.seed import seed


def main():
    LOCAL.mkdir(parents=True, exist_ok=True)
    path = LOCAL / "credentials.json"
    if not path.exists():
        with path.open("x", encoding="utf-8") as handle:
            json.dump({org: secrets.token_urlsafe(32) for org in ("oncopilot", "radpath")}, handle)
    keys = json.loads(path.read_text(encoding="utf-8"))
    engine, sessions = database()
    try:
        seed(sessions, keys)
    finally:
        engine.dispose()
    print("Seeded OncoPilot and RadPath (MedData Partners). Credentials saved locally; no keys displayed.")


if __name__ == "__main__":
    main()
