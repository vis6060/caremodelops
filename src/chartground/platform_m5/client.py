"""Server-side, read-only client for the Streamlit dashboard."""

import httpx


class PlatformAPI:
    def __init__(self, base_url, api_key, timeout=20):
        self.base_url = base_url.rstrip("/")
        self.__api_key = api_key
        self.timeout = timeout

    def __repr__(self):
        return f"PlatformAPI(base_url={self.base_url!r}, api_key='[REDACTED]')"

    def get(self, path, params=None):
        with httpx.Client(base_url=self.base_url, timeout=self.timeout, trust_env=False) as client:
            response = client.get(path, params=params,
                                  headers={"Authorization": "Bearer " + self.__api_key})
            response.raise_for_status()
            return response.json()

    def attempts(self):
        offset, rows, summary = 0, [], None
        while True:
            page = self.get("/v1/usage", {"limit": 100, "offset": offset})
            summary = summary or page
            batch = page.get("attempts") or []
            rows.extend(batch)
            if len(batch) < 100:
                break
            offset += len(batch)
        summary = dict(summary or {})
        summary["attempts"] = rows
        return summary

    def dashboard_data(self, start, end):
        period = {"reporting_period_start": start, "reporting_period_end": end}
        return {
            "runs": self.get("/v1/analytics/runs", {"start": start, "end": end, "limit": 2000}).get("runs", []),
            "lifecycle": self.get("/v1/analytics/lifecycle-events", {"limit": 2000}).get("events", []),
            "usage": self.attempts(),
            "invoices": self.get("/v1/invoices").get("invoices", []),
            "unit_economics": self.get("/v1/unit-economics", period),
            "partner_attribution": self.get("/v1/partner-attribution", period),
            "policies": self.get("/v1/spending-controls/policies").get("policies", []),
            "organization_status": self.get("/v1/spending-controls/status"),
            "reservations": self.get("/v1/spending-controls/reservations").get("reservations", []),
            "alerts": self.get("/v1/spending-controls/alerts").get("alerts", []),
            "audit": self.get("/v1/spending-controls/audit", {"limit": 500}).get("audit", []),
        }
