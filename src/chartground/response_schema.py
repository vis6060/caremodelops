"""Shared structured response schema for ChartGround answer paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Action = Literal["answer", "uncertain", "escalate", "abstain"]
Architecture = Literal["direct_context", "rag", "tool_agent", "verified_agent"]


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    cited_evidence_ids: list[str]
    support_status: Literal["supported", "partially_supported", "unsupported", "insufficient_evidence"]
    support_reason: str
    severity_if_wrong: Literal["low", "medium", "high"]
    verifier: Literal["deterministic", "local_llm", "not_checked"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentResponse:
    answer: str
    patient_id: str
    case_id: str | None
    question: str
    architecture: Architecture
    action: Action
    action_reason: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    cited_evidence_ids: list[str] = field(default_factory=list)
    unsupported_claims: list[dict[str, Any]] = field(default_factory=list)
    retrieved_evidence: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
