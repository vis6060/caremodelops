"""Atomic preflight reservations and actual-cost reconciliation."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select, text

from chartground.platform_m2.database import Agent
from chartground.platform_m3.costing import (decimal_value, estimate_attempt_cost,
                                             money, money_text, rate_card_for,
                                             timestamp)

from .models import BudgetPolicy, SpendAlert, SpendAudit, SpendReservation, utc_now

THRESHOLDS = (50, 80, 100)


def policy_payload(policy):
    if policy is None:
        return None
    return {
        "policy_id": policy.id, "organization_id": policy.organization_id,
        "scope_type": policy.scope_type, "scope_id": policy.scope_id,
        "revision": policy.revision, "monthly_spend_limit": policy.monthly_spend_limit,
        "daily_request_limit": policy.daily_request_limit,
        "monthly_request_limit": policy.monthly_request_limit,
        "assumed_input_tokens": policy.assumed_input_tokens,
        "max_output_tokens": policy.max_output_tokens, "max_attempts": policy.max_attempts,
        "model_id": policy.model_id, "created_at": policy.created_at,
    }


def reservation_payload(row):
    return {
        "reservation_id": row.id, "run_id": row.run_id, "organization_id": row.organization_id,
        "agent_id": row.agent_id, "status": row.status, "model_id": row.model_id,
        "rate_card_version": row.rate_card_version, "reserved_cost": row.reserved_cost,
        "held_cost": row.held_cost, "actual_cost": row.actual_cost,
        "day_key": row.day_key, "month_key": row.month_key,
        "preflight": row.preflight, "reconciliation": row.reconciliation,
        "created_at": row.created_at, "reconciled_at": row.reconciled_at,
    }


class SpendingController:
    def __init__(self, sessions, engine, analytics_observer=None):
        self.sessions = sessions
        self.engine = engine
        self.analytics_observer = analytics_observer

    def _lock(self, session):
        if self.engine.dialect.name == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))

    @staticmethod
    def _period(at):
        moment = timestamp(at)
        return moment.date().isoformat(), moment.strftime("%Y-%m")

    @staticmethod
    def _active_policy(session, organization_id, scope_type, scope_id, lock=False):
        query = select(BudgetPolicy).where(
            BudgetPolicy.organization_id == organization_id,
            BudgetPolicy.scope_type == scope_type,
            BudgetPolicy.scope_id == scope_id,
            BudgetPolicy.active == 1,
        )
        if lock and session.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return session.scalar(query)

    @staticmethod
    def _audit(session, organization_id, event_type, outcome, details,
               agent_id=None, run_id=None, actor_developer_id=None):
        session.add(SpendAudit(
            organization_id=organization_id, agent_id=agent_id, run_id=run_id,
            actor_developer_id=actor_developer_id, event_type=event_type,
            outcome=outcome, details=details,
        ))

    @staticmethod
    def _scope_rows(session, organization_id, month_key, agent_id=None):
        query = select(SpendReservation).where(
            SpendReservation.organization_id == organization_id,
            SpendReservation.month_key == month_key,
        )
        if agent_id is not None:
            query = query.where(SpendReservation.agent_id == agent_id)
        return list(session.scalars(query))

    @classmethod
    def _scope_usage(cls, session, organization_id, day_key, month_key, agent_id=None):
        rows = cls._scope_rows(session, organization_id, month_key, agent_id)
        spend = sum((decimal_value(row.held_cost) for row in rows), Decimal("0"))
        return {
            "spend": money(spend), "monthly_requests": len(rows),
            "daily_requests": sum(row.day_key == day_key for row in rows),
            "unreconciled_requests": sum(row.status in {"reserved", "unreconciled"} for row in rows),
        }

    @staticmethod
    def _estimate(session, organization_policy, agent_policy, requested_model, at):
        model_id = requested_model or organization_policy.model_id
        if model_id != organization_policy.model_id or model_id != agent_policy.model_id:
            return {"known": False, "reason": "Requested model is not allowed by both active policies.", "model_id": model_id}
        card = rate_card_for(session, model_id, at)
        if card is None:
            return {"known": False, "reason": "No effective M3 rate card exists for the requested model.", "model_id": model_id}
        input_tokens = max(organization_policy.assumed_input_tokens, agent_policy.assumed_input_tokens)
        initial_output = max(organization_policy.max_output_tokens, agent_policy.max_output_tokens)
        attempts = max(organization_policy.max_attempts, agent_policy.max_attempts)
        outputs = [initial_output]
        if attempts == 2:
            outputs.append(min(initial_output * 2, 8192))
        costs = []
        for number, output_tokens in enumerate(outputs, 1):
            synthetic = SimpleNamespace(
                input_tokens=input_tokens, output_tokens=output_tokens,
                cache_creation_tokens=0, cache_read_tokens=0,
                details={"model_id": model_id},
            )
            cost = estimate_attempt_cost(synthetic, card)
            if cost.total is None:
                return {"known": False, "reason": cost.unknown_reason, "model_id": model_id}
            costs.append({"attempt": number, "input_tokens": input_tokens,
                          "max_output_tokens": output_tokens, "estimated_cost": money_text(cost.total)})
        total = sum((decimal_value(item["estimated_cost"]) for item in costs), Decimal("0"))
        return {
            "known": True, "model_id": model_id, "rate_card_version": card.id,
            "estimated_max_cost": money_text(total), "attempts": costs,
            "assumptions": "No cache use; bounded input tokens and maximum output tokens for each permitted attempt.",
        }

    def set_policy(self, organization_id, scope_type, scope_id, values, developer_id):
        session = self.sessions()
        try:
            self._lock(session)
            if scope_type == "agent":
                agent = session.get(Agent, scope_id)
                if agent is None or agent.organization_id != organization_id:
                    raise LookupError("Agent not found.")
            current = self._active_policy(session, organization_id, scope_type, scope_id, lock=True)
            revision = 1 if current is None else current.revision + 1
            before = policy_payload(current)
            if current is not None:
                current.active = 0
            policy = BudgetPolicy(
                id=str(uuid4()), organization_id=organization_id, scope_type=scope_type,
                scope_id=scope_id, revision=revision, active=1,
                monthly_spend_limit=money_text(decimal_value(values["monthly_spend_limit"])),
                daily_request_limit=values["daily_request_limit"],
                monthly_request_limit=values["monthly_request_limit"],
                assumed_input_tokens=values["assumed_input_tokens"],
                max_output_tokens=values["max_output_tokens"], max_attempts=values["max_attempts"],
                model_id=values["model_id"], created_by_developer_id=developer_id,
            )
            session.add(policy)
            session.flush()
            self._audit(session, organization_id, "budget_change", "applied",
                        {"scope_type": scope_type, "scope_id": scope_id,
                         "previous_policy": before, "new_policy": policy_payload(policy)},
                        agent_id=scope_id if scope_type == "agent" else None,
                        actor_developer_id=developer_id)
            session.commit()
            return policy_payload(policy)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def policies(self, organization_id):
        with self.sessions() as session:
            rows = list(session.scalars(select(BudgetPolicy).where(
                BudgetPolicy.organization_id == organization_id,
                BudgetPolicy.active == 1,
            ).order_by(BudgetPolicy.scope_type, BudgetPolicy.scope_id)))
            return [policy_payload(row) for row in rows]

    def preflight(self, organization_id, agent_id, requested_model=None, at=None):
        at = at or datetime.now(timezone.utc)
        with self.sessions() as session:
            org_policy = self._active_policy(session, organization_id, "organization", organization_id)
            agent_policy = self._active_policy(session, organization_id, "agent", agent_id)
            if org_policy is None or agent_policy is None:
                return {"known": False, "reason": "Both organization and agent policies are required."}
            return self._estimate(session, org_policy, agent_policy, requested_model, at)

    def _alerts(self, session, organization_id, agent_id, month_key, policy, usage):
        scope_type = policy.scope_type
        scope_id = policy.scope_id
        limit = decimal_value(policy.monthly_spend_limit)
        if limit <= 0:
            return
        percentage = usage["spend"] * Decimal("100") / limit
        for threshold in THRESHOLDS:
            if percentage < threshold:
                continue
            exists = session.scalar(select(SpendAlert).where(
                SpendAlert.organization_id == organization_id,
                SpendAlert.scope_type == scope_type,
                SpendAlert.scope_id == scope_id,
                SpendAlert.month_key == month_key,
                SpendAlert.threshold_percent == threshold,
            ))
            if exists is None:
                session.add(SpendAlert(
                    organization_id=organization_id, scope_type=scope_type,
                    scope_id=scope_id, month_key=month_key,
                    threshold_percent=threshold, spend_at_trigger=money_text(usage["spend"]),
                    budget_limit=policy.monthly_spend_limit,
                ))

    def reserve(self, run, request):
        session = self.sessions()
        try:
            self._lock(session)
            existing = session.scalar(select(SpendReservation).where(SpendReservation.run_id == run.id))
            if existing is not None:
                session.commit()
                return {"approved": True, "reason": "Idempotent reservation replay.",
                        "reservation": reservation_payload(existing)}
            org_policy = self._active_policy(session, run.organization_id, "organization", run.organization_id, lock=True)
            agent_policy = self._active_policy(session, run.organization_id, "agent", run.agent_id, lock=True)
            if org_policy is None or agent_policy is None:
                decision = {"approved": False, "reason": "Both organization and agent policies are required."}
                self._audit(session, run.organization_id, "preflight_denial", "denied", decision,
                            agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
                session.commit()
                return decision
            estimate = self._estimate(session, org_policy, agent_policy, request.get("model"), run.created_at)
            if not estimate["known"]:
                decision = {"approved": False, "reason": estimate["reason"], "preflight": estimate}
                self._audit(session, run.organization_id, "preflight_denial", "denied", decision,
                            agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
                session.commit()
                return decision
            day_key, month_key = self._period(run.created_at)
            org_usage = self._scope_usage(session, run.organization_id, day_key, month_key)
            agent_usage = self._scope_usage(session, run.organization_id, day_key, month_key, run.agent_id)
            estimate_cost = decimal_value(estimate["estimated_max_cost"])
            checks = (
                (org_usage["daily_requests"] >= org_policy.daily_request_limit, "Organization daily request quota exceeded."),
                (org_usage["monthly_requests"] >= org_policy.monthly_request_limit, "Organization monthly request quota exceeded."),
                (org_usage["spend"] + estimate_cost > decimal_value(org_policy.monthly_spend_limit), "Organization monthly spend budget exceeded."),
                (agent_usage["daily_requests"] >= agent_policy.daily_request_limit, "Agent daily request quota exceeded."),
                (agent_usage["monthly_requests"] >= agent_policy.monthly_request_limit, "Agent monthly request quota exceeded."),
                (agent_usage["spend"] + estimate_cost > decimal_value(agent_policy.monthly_spend_limit), "Agent monthly spend budget exceeded."),
            )
            denial = next((reason for failed, reason in checks if failed), None)
            if denial:
                decision = {"approved": False, "reason": denial, "preflight": estimate,
                            "organization_held_spend": money_text(org_usage["spend"]),
                            "agent_held_spend": money_text(agent_usage["spend"])}
                self._audit(session, run.organization_id, "preflight_denial", "denied", decision,
                            agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
                session.commit()
                return decision
            reservation = SpendReservation(
                id=str(uuid4()), run_id=run.id, organization_id=run.organization_id,
                agent_id=run.agent_id, day_key=day_key, month_key=month_key,
                model_id=estimate["model_id"], rate_card_version=estimate["rate_card_version"],
                reserved_cost=estimate["estimated_max_cost"], held_cost=estimate["estimated_max_cost"],
                actual_cost=None, status="reserved", preflight=estimate, reconciliation=None,
            )
            session.add(reservation)
            session.flush()
            org_usage["spend"] = money(org_usage["spend"] + estimate_cost)
            org_usage["daily_requests"] += 1
            org_usage["monthly_requests"] += 1
            agent_usage["spend"] = money(agent_usage["spend"] + estimate_cost)
            agent_usage["daily_requests"] += 1
            agent_usage["monthly_requests"] += 1
            self._alerts(session, run.organization_id, run.agent_id, month_key, org_policy, org_usage)
            self._alerts(session, run.organization_id, run.agent_id, month_key, agent_policy, agent_usage)
            details = {"reservation_id": reservation.id, "reserved_cost": reservation.reserved_cost,
                       "rate_card_version": reservation.rate_card_version}
            self._audit(session, run.organization_id, "preflight_approval", "approved", details,
                        agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
            self._audit(session, run.organization_id, "reservation_created", "reserved", details,
                        agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
            if self.analytics_observer is not None:
                self.analytics_observer.on_reservation(session, run, reservation)
            session.commit()
            return {"approved": True, "reason": "Budget and quota checks passed.",
                    "reservation": reservation_payload(reservation)}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def mark_unreconciled(self, session, run, reason):
        reservation = session.scalar(select(SpendReservation).where(SpendReservation.run_id == run.id))
        if reservation is None:
            return
        reservation.status = "unreconciled"
        reservation.reconciliation = {"known": False, "reason": reason,
                                      "reserved_spend_retained": reservation.held_cost}
        reservation.reconciled_at = utc_now()
        self._audit(session, run.organization_id, "reconciliation", "unreconciled",
                    reservation.reconciliation, agent_id=run.agent_id, run_id=run.id,
                    actor_developer_id=run.developer_id)

    def reconcile(self, session, run, attempts):
        reservation = session.scalar(select(SpendReservation).where(SpendReservation.run_id == run.id))
        if reservation is None:
            return
        if run.provider == "mock" and not attempts:
            costs, unknown = [], None
        elif not attempts:
            costs, unknown = [], "No per-attempt usage was reported; reserved spend retained."
        else:
            costs, unknown = [], None
            for attempt in attempts:
                model_id = (attempt.details or {}).get("model_id")
                card = rate_card_for(session, model_id, run.created_at) if model_id else None
                result = estimate_attempt_cost(attempt, card)
                costs.append({"attempt": attempt.number, "model_id": model_id,
                              "rate_card_version": result.rate_card_version,
                              "actual_cost": money_text(result.total), "unknown_reason": result.unknown_reason})
                if result.total is None:
                    unknown = result.unknown_reason
        if unknown is None:
            actual = sum((decimal_value(item["actual_cost"]) for item in costs), Decimal("0"))
            reservation.actual_cost = money_text(actual)
            reservation.held_cost = money_text(actual)
            reservation.status = "reconciled"
            outcome = "reconciled"
            details = {"known": True, "actual_cost": reservation.actual_cost,
                       "attempts": costs, "failed_calls_preserved": run.status != "success"}
        else:
            reservation.actual_cost = None
            reservation.status = "unreconciled"
            outcome = "unreconciled"
            details = {"known": False, "reason": unknown, "attempts": costs,
                       "reserved_spend_retained": reservation.held_cost}
        reservation.reconciliation = details
        reservation.reconciled_at = utc_now()
        day_key, month_key = reservation.day_key, reservation.month_key
        org_policy = self._active_policy(session, run.organization_id, "organization", run.organization_id)
        agent_policy = self._active_policy(session, run.organization_id, "agent", run.agent_id)
        if org_policy:
            self._alerts(session, run.organization_id, run.agent_id, month_key, org_policy,
                         self._scope_usage(session, run.organization_id, day_key, month_key))
        if agent_policy:
            self._alerts(session, run.organization_id, run.agent_id, month_key, agent_policy,
                         self._scope_usage(session, run.organization_id, day_key, month_key, run.agent_id))
        self._audit(session, run.organization_id, "reconciliation", outcome, details,
                    agent_id=run.agent_id, run_id=run.id, actor_developer_id=run.developer_id)
        if self.analytics_observer is not None:
            self.analytics_observer.on_reconciliation(session, run, reservation)

    def status(self, organization_id, agent_id=None, at=None):
        at = at or datetime.now(timezone.utc)
        day_key, month_key = self._period(at)
        with self.sessions() as session:
            scope_type, scope_id = ("agent", agent_id) if agent_id else ("organization", organization_id)
            policy = self._active_policy(session, organization_id, scope_type, scope_id)
            if policy is None:
                return {"organization_id": organization_id, "agent_id": agent_id,
                        "policy": None, "status": "unconfigured"}
            usage = self._scope_usage(session, organization_id, day_key, month_key, agent_id)
            limit = decimal_value(policy.monthly_spend_limit)
            percent = Decimal("0") if not limit else usage["spend"] * Decimal("100") / limit
            return {
                "organization_id": organization_id, "agent_id": agent_id,
                "period": {"day": day_key, "month": month_key}, "policy": policy_payload(policy),
                "held_spend": money_text(usage["spend"]),
                "spend_utilization_percent": format(percent.quantize(Decimal("0.01")), "f"),
                "daily_requests": usage["daily_requests"], "monthly_requests": usage["monthly_requests"],
                "unreconciled_requests": usage["unreconciled_requests"],
            }

    def reservations(self, organization_id):
        with self.sessions() as session:
            rows = list(session.scalars(select(SpendReservation).where(
                SpendReservation.organization_id == organization_id
            ).order_by(SpendReservation.created_at, SpendReservation.id)))
            return [reservation_payload(row) for row in rows]

    def alerts(self, organization_id):
        with self.sessions() as session:
            rows = list(session.scalars(select(SpendAlert).where(
                SpendAlert.organization_id == organization_id
            ).order_by(SpendAlert.created_at, SpendAlert.id)))
            return [{"alert_id": row.id, "scope_type": row.scope_type, "scope_id": row.scope_id,
                     "month": row.month_key, "threshold_percent": row.threshold_percent,
                     "spend_at_trigger": row.spend_at_trigger, "budget_limit": row.budget_limit,
                     "created_at": row.created_at} for row in rows]

    def audit(self, organization_id, limit=100):
        with self.sessions() as session:
            rows = list(session.scalars(select(SpendAudit).where(
                SpendAudit.organization_id == organization_id
            ).order_by(SpendAudit.id.desc()).limit(limit)))
            return [{"audit_id": row.id, "agent_id": row.agent_id, "run_id": row.run_id,
                     "actor_developer_id": row.actor_developer_id, "event_type": row.event_type,
                     "outcome": row.outcome, "details": row.details,
                     "created_at": row.created_at} for row in rows]


class LifecycleProxy:
    """Allows M2 to close over the hook before the app exposes its sessions."""
    target = None

    def reserve(self, run, request):
        return self.target.reserve(run, request)

    def reconcile(self, session, run, attempts):
        return self.target.reconcile(session, run, attempts)

    def mark_unreconciled(self, session, run, reason):
        return self.target.mark_unreconciled(session, run, reason)
