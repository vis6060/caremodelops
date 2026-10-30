"""Read-only ChartGround developer analytics and monetization dashboard."""

import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.platform_m2.database import LOCAL
from chartground.platform_m5.analytics import (developer_adoption, filter_by_time,
                                               monetization_summary,
                                               spending_summary, summarize_usage)
from chartground.platform_m5.client import PlatformAPI

PAGES = (
    "Executive Overview",
    "Developer Adoption",
    "API Usage",
    "Monetization / Partner Economics",
    "Enterprise Spending Controls",
)


def money(value):
    return "Unknown" if value is None else f"${value:,.6f}"


def integer(value):
    return f"{int(value or 0):,}"


def metric_row(items):
    columns = st.columns(len(items))
    for column, (label, value, help_text) in zip(columns, items):
        column.metric(label, value, help=help_text)


def empty(message):
    st.info(message)


def daily_request_frame(runs):
    if not runs:
        return pd.DataFrame(columns=["date", "requests"])
    frame = pd.DataFrame(runs)
    frame["date"] = pd.to_datetime(frame["created_at"], utc=True).dt.date
    return frame.groupby("date", as_index=False).size().rename(columns={"size": "requests"})


def executive(data, usage_summary, monetization, spending):
    st.header("Executive Overview")
    metric_row((
        ("Measured requests", integer(usage_summary["measured_request_count"]), usage_summary["labeling"]["requests_and_tokens"]),
        ("Measured attempts", integer(usage_summary["measured_attempt_count"]), "Recorded M2 per-attempt usage rows."),
        ("Estimated upstream cost", money(monetization["estimated_upstream_cost"]), monetization["labels"]["estimated_upstream_cost"]),
        ("Simulated gross margin", money(monetization["simulated_gross_margin"]), monetization["labels"]["simulated_gross_margin"]),
    ))
    chart = daily_request_frame(data["runs"])
    left, right = st.columns((2, 1))
    with left:
        st.subheader("Request activity")
        if chart.empty:
            empty("No requests were recorded in this time range.")
        else:
            st.line_chart(chart.set_index("date"), color="#147d78", height=280)
    with right:
        st.subheader("Run outcomes")
        statuses = pd.DataFrame(list(usage_summary["run_statuses"].items()), columns=["status", "requests"])
        if statuses.empty:
            empty("No run outcomes are available.")
        else:
            st.bar_chart(statuses.set_index("status"), color="#b7791f", height=280)
    st.subheader("Current spending posture")
    metric_row((
        ("Held spend", money(spending["held_spend"]), spending["labels"]["held_spend"]),
        ("Unreconciled requests", integer(spending["unreconciled_requests"]), spending["labels"]["unknown_cost"]),
        ("Budget denials", integer(spending["denial_count"]), "M4 preflight denials recorded in the tenant audit log."),
        ("Local alerts", integer(spending["alert_count"]), "Stored M4 threshold alerts; no email was sent."),
    ))


def adoption_page(adoption):
    st.header("Developer Adoption")
    metric_row((
        ("Observed developers", integer(len(adoption["developers"])), "Developers with measured API run records."),
        ("Recorded onboardings", integer(adoption["onboarded_developers"]), "Forward-looking lifecycle events only; historical events are not fabricated."),
        ("Recorded activations", integer(adoption["activated_developers"]), "Activation is defined as the first successful API call."),
        ("Retention", "Insufficient data" if adoption["retention_rate"] is None else f"{adoption['retention_rate']:.1%}", adoption["retention_note"]),
    ))
    st.caption(adoption["activation_note"] + " " + adoption["retention_note"])
    if not adoption["developers"]:
        empty("No developer activity is available in this time range.")
        return
    frame = pd.DataFrame(adoption["developers"])
    st.dataframe(frame, width="stretch", hide_index=True,
                 column_config={"requests": st.column_config.NumberColumn(format="%d"),
                                "successful_runs": st.column_config.NumberColumn(format="%d")})
    chart = frame[["developer_id", "requests", "successful_runs"]].set_index("developer_id")
    st.bar_chart(chart, color=["#147d78", "#b7791f"], height=300)


def usage_page(data, usage_summary):
    st.header("API Usage")
    attempts = data["usage"].get("attempts") or []
    agent_options = ["All agents"] + usage_summary["agents"]
    model_options = ["All models"] + usage_summary["models"]
    one, two = st.columns(2)
    agent = one.selectbox("Agent", agent_options)
    model = two.selectbox("Model", model_options)
    filtered = [row for row in attempts
                if (agent == "All agents" or row.get("agent_id") == agent)
                and (model == "All models" or row.get("model_id") == model)]
    totals = usage_summary["reported_token_totals"]
    metric_row((
        ("Reported input tokens", integer(totals["input_tokens"]), "Measured tokens only."),
        ("Reported output tokens", integer(totals["output_tokens"]), "Measured tokens only."),
        ("Cache-write tokens", integer(totals["cache_creation_tokens"]), "Measured cache creation tokens."),
        ("Cache-read tokens", integer(totals["cache_read_tokens"]), "Measured cache read tokens."),
    ))
    if not filtered:
        empty("No attempts match these filters.")
        return
    frame = pd.DataFrame(filtered)
    fields = [field for field in ("run_id", "agent_id", "model_id", "attempt", "api_status",
                                  "generation_status", "input_tokens", "output_tokens",
                                  "cache_creation_tokens", "cache_read_tokens", "stop_reason", "timestamp")
              if field in frame.columns]
    st.dataframe(frame[fields], width="stretch", hide_index=True)
    status_counts = frame["generation_status"].fillna(frame["api_status"]).fillna("unknown").value_counts()
    st.bar_chart(status_counts, color="#147d78", height=260)
    if any(usage_summary["unknown_token_counts"].values()):
        st.warning("Some per-attempt token fields are unknown. They are not included as zero in measured totals.")


def monetization_page(data, summary):
    st.header("Monetization / Partner Economics")
    st.caption("Commercial values are fictional M3 scenarios. Estimated upstream cost is not an Anthropic invoice.")
    metric_row((
        ("Estimated upstream cost", money(summary["estimated_upstream_cost"]), summary["labels"]["estimated_upstream_cost"]),
        ("Simulated customer charges", money(summary["simulated_customer_charges"]), summary["labels"]["simulated_customer_charges"]),
        ("Simulated partner payouts", money(summary["simulated_partner_payouts"]), summary["labels"]["simulated_partner_payouts"]),
        ("Simulated gross margin", money(summary["simulated_gross_margin"]), summary["labels"]["simulated_gross_margin"]),
    ))
    partner = data["partner_attribution"]
    st.subheader("Channel attribution")
    st.dataframe(pd.DataFrame([{
        "channel": partner.get("channel"), "partner_id": partner.get("partner_id") or "Direct",
        "pricing_terms": partner.get("partner_terms_version") or "Not applicable",
        "simulated_partner_payout": partner.get("simulated_partner_payout"),
    }]), width="stretch", hide_index=True)
    st.subheader("Simulated invoices")
    if not data["invoices"]:
        empty("No simulated invoices exist for this tenant.")
    else:
        frame = pd.DataFrame(data["invoices"])
        fields = [field for field in ("invoice_id", "invoice_type", "status", "pricing_plan_version",
                                      "estimated_upstream_cost", "illustrative_customer_charge",
                                      "simulated_partner_payout", "simulated_gross_margin", "created_at")
                  if field in frame.columns]
        st.dataframe(frame[fields], width="stretch", hide_index=True)


def controls_page(data, summary, api):
    st.header("Enterprise Spending Controls")
    st.caption("Read-only view. Budget policies and billing records cannot be changed from this dashboard.")
    status = data["organization_status"]
    metric_row((
        ("Held spend", money(summary["held_spend"]), summary["labels"]["held_spend"]),
        ("Reconciled", integer(summary["reconciled_count"]), summary["labels"]["actual_cost"]),
        ("Unknown / unreconciled", integer(summary["unknown_cost_count"]), summary["labels"]["unknown_cost"]),
        ("Monthly requests", integer(status.get("monthly_requests")), "Requests with M4 spend reservations this month."),
    ))
    st.subheader("Active policies")
    if data["policies"]:
        st.dataframe(pd.DataFrame(data["policies"]), width="stretch", hide_index=True)
    else:
        empty("No active spending policies are configured.")
    agent_policies = [row for row in data["policies"] if row.get("scope_type") == "agent"]
    if agent_policies:
        st.subheader("Agent status")
        agent_rows = []
        for policy in agent_policies:
            try:
                agent_rows.append(api.get(f"/v1/spending-controls/agents/{policy['scope_id']}/status"))
            except Exception:
                continue
        if agent_rows:
            st.dataframe(pd.DataFrame(agent_rows), width="stretch", hide_index=True)
    st.subheader("Reservations and reconciliation")
    if data["reservations"]:
        frame = pd.DataFrame(data["reservations"])
        fields = [field for field in ("run_id", "agent_id", "status", "reserved_cost", "held_cost",
                                      "actual_cost", "model_id", "rate_card_version", "created_at")
                  if field in frame.columns]
        st.dataframe(frame[fields], width="stretch", hide_index=True)
    else:
        empty("No M4 spend reservations exist for this tenant.")
    one, two = st.columns(2)
    with one:
        st.subheader("Threshold alerts")
        if data["alerts"]:
            st.dataframe(pd.DataFrame(data["alerts"]), width="stretch", hide_index=True)
        else:
            empty("No spending thresholds have been crossed.")
    with two:
        st.subheader("Budget denials")
        denials = [row for row in data["audit"] if row.get("event_type") == "preflight_denial"]
        if denials:
            st.dataframe(pd.DataFrame(denials), width="stretch", hide_index=True)
        else:
            empty("No budget or quota denials are recorded.")


def load_demo_key(organization_id):
    import json

    path = LOCAL / "credentials.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    return values[organization_id]


def main():
    st.set_page_config(page_title="ChartGround Analytics", page_icon=None, layout="wide")
    st.markdown("""
        <style>
        :root { --cg-teal: #147d78; --cg-gold: #b7791f; --cg-ink: #1f2933; }
        .stApp { color: var(--cg-ink); }
        [data-testid="stMetric"] { border-left: 3px solid var(--cg-teal); padding-left: 12px; }
        [data-testid="stSidebar"] { border-right: 1px solid #d8dee4; }
        h1, h2, h3 { letter-spacing: 0; }
        </style>
    """, unsafe_allow_html=True)
    st.title("ChartGround Developer Analytics")
    st.caption("Tenant-scoped operational analytics with measured usage, estimated cost, and fictional commercial scenarios.")

    demo = os.getenv("CHARTGROUND_M5_DEMO") == "1"
    with st.sidebar:
        st.subheader("Workspace")
        base_url = st.text_input("Platform API", os.getenv("CHARTGROUND_API_URL", "http://127.0.0.1:8000"))
        if demo:
            organization = st.selectbox("Organization", ("OncoPilot", "RadPath"))
            organization_id = "oncopilot" if organization == "OncoPilot" else "radpath"
            try:
                api_key = load_demo_key(organization_id)
            except (OSError, KeyError, ValueError):
                api_key = ""
                st.error("Local demo credentials are unavailable.")
        else:
            api_key = st.text_input("API key", type="password")
        today = date.today()
        default_start = today.replace(day=1)
        start_date = st.date_input("From", default_start)
        end_date = st.date_input("Through", today)
        page = st.radio("View", PAGES)

    if not api_key:
        empty("Authenticate to load tenant analytics.")
        return
    start = datetime.combine(start_date, time.min, timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, timezone.utc)
    api = PlatformAPI(base_url, api_key)
    try:
        data = api.dashboard_data(start.isoformat(), end.isoformat())
    except Exception:
        st.error("The tenant analytics API is unavailable or authentication failed.")
        return
    data["usage"]["attempts"] = filter_by_time(data["usage"].get("attempts") or [], start, end, "timestamp")
    data["invoices"] = filter_by_time(data["invoices"], start, end, "created_at")
    usage_summary = summarize_usage(data["usage"], data["runs"])
    adoption = developer_adoption(data["runs"], data["lifecycle"])
    monetization = monetization_summary(data["invoices"], data["unit_economics"])
    spending = spending_summary(data["organization_status"], data["reservations"], data["alerts"], data["audit"])

    if page == "Executive Overview":
        executive(data, usage_summary, monetization, spending)
    elif page == "Developer Adoption":
        adoption_page(adoption)
    elif page == "API Usage":
        usage_page(data, usage_summary)
    elif page == "Monetization / Partner Economics":
        monetization_page(data, monetization)
    else:
        controls_page(data, spending, api)


if __name__ == "__main__":
    main()
