"""Record future lifecycle events without inventing history for existing runs."""

from sqlalchemy import select

from .models import DeveloperLifecycleEvent


class DeveloperLifecycleService:
    def _record(self, session, event_key, organization_id, developer_id, event_type,
                occurred_at, agent_id=None, run_id=None, properties=None):
        if session.scalar(select(DeveloperLifecycleEvent.id).where(
                DeveloperLifecycleEvent.event_key == event_key)) is not None:
            return
        session.add(DeveloperLifecycleEvent(
            event_key=event_key, organization_id=organization_id,
            developer_id=developer_id, agent_id=agent_id, run_id=run_id,
            event_type=event_type, occurred_at=occurred_at,
            properties=properties or {},
        ))

    def record_onboarding(self, session, organization_id, developer_id, occurred_at, source):
        """Provisioning code may call this for future developers; M5 never backfills it."""
        self._record(session, f"onboarding:{developer_id}", organization_id, developer_id,
                     "developer_onboarded", occurred_at, properties={"source": source})

    def on_reservation(self, session, run, reservation):
        self._record(session, f"approved:{run.id}", run.organization_id, run.developer_id,
                     "api_request_approved", run.created_at, agent_id=run.agent_id,
                     run_id=run.id, properties={
                         "model_id": reservation.model_id,
                         "rate_card_version": reservation.rate_card_version,
                     })

    def on_reconciliation(self, session, run, reservation):
        if run.status != "success":
            return
        properties = {"provider": run.provider, "usage_status": reservation.status,
                      "model_id": reservation.model_id}
        self._record(session, f"success:{run.id}", run.organization_id, run.developer_id,
                     "api_call_succeeded", reservation.reconciled_at or run.created_at,
                     agent_id=run.agent_id, run_id=run.id, properties=properties)
        first = session.scalar(select(DeveloperLifecycleEvent.id).where(
            DeveloperLifecycleEvent.organization_id == run.organization_id,
            DeveloperLifecycleEvent.developer_id == run.developer_id,
            DeveloperLifecycleEvent.event_type == "first_successful_api_call",
        ))
        if first is None:
            self._record(session, f"first-success:{run.developer_id}", run.organization_id,
                         run.developer_id, "first_successful_api_call",
                         reservation.reconciled_at or run.created_at, agent_id=run.agent_id,
                         run_id=run.id, properties=properties)
            self._record(session, f"activated:{run.developer_id}", run.organization_id,
                         run.developer_id, "developer_activated",
                         reservation.reconciled_at or run.created_at, agent_id=run.agent_id,
                         run_id=run.id, properties={"definition": "first successful API call"})

    def events(self, session, organization_id):
        return list(session.scalars(select(DeveloperLifecycleEvent).where(
            DeveloperLifecycleEvent.organization_id == organization_id
        ).order_by(DeveloperLifecycleEvent.occurred_at, DeveloperLifecycleEvent.id)))


class LifecycleObserverProxy:
    target = None

    def on_reservation(self, session, run, reservation):
        return self.target.on_reservation(session, run, reservation)

    def on_reconciliation(self, session, run, reservation):
        return self.target.on_reconciliation(session, run, reservation)
