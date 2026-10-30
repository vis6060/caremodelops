"""Create idempotent simulated invoices from existing M2 usage; never call Claude."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.platform_m2.database import LOCAL, Run
from chartground.platform_m3.api import create_app


def month_bounds(value):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def main():
    credentials = json.loads((LOCAL / "credentials.json").read_text(encoding="utf-8"))
    database_url = "sqlite:///" + (LOCAL / "platform.sqlite3").as_posix()
    app = create_app(database_url=database_url, allow_claude=False)
    with app.state.sessions() as session:
        first = session.scalar(select(func.min(Run.created_at)))
    if first is None:
        raise SystemExit("No recorded M2 runs are available for the M3 demo.")
    start, end = month_bounds(first)
    with TestClient(app) as client:
        for organization_id in ("oncopilot", "radpath"):
            headers = {
                "Authorization": "Bearer " + credentials[organization_id],
                "Idempotency-Key": f"m3-demo-{organization_id}-{start[:7]}",
            }
            response = client.post("/v1/invoices", headers=headers, json={
                "reporting_period_start": start, "reporting_period_end": end,
            })
            response.raise_for_status()
            invoice = response.json()
            print(json.dumps({
                "organization_id": organization_id,
                "invoice_id": invoice["invoice_id"],
                "pricing_plan_version": invoice["pricing_plan_version"],
                "estimated_upstream_cost": invoice["estimated_upstream_cost"],
                "illustrative_customer_charge": invoice["illustrative_customer_charge"],
                "partner_terms_version": invoice["partner_terms_version"],
                "simulated_partner_payout": invoice["simulated_partner_payout"],
                "simulated_gross_margin": invoice["simulated_gross_margin"],
                "idempotent": True,
            }))
    app.state.engine.dispose()


if __name__ == "__main__":
    main()
