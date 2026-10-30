"""Deterministic patient-scoped RAG baseline for ChartGround."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from chartground.evidence_store import EvidenceStore, RetrievalResult


Action = Literal["answer", "uncertain", "escalate", "abstain"]


@dataclass(frozen=True)
class RagResponse:
    answer: str
    cited_evidence_ids: list[str]
    retrieved_evidence: list[dict]
    action: Action
    action_reason: str
    prompt: str

    def to_dict(self) -> dict:
        return asdict(self)


class RagBaseline:
    """Retrieval-augmented baseline with deterministic placeholder generation."""

    def __init__(self, evidence_store: EvidenceStore, top_k: int = 5) -> None:
        self.evidence_store = evidence_store
        self.top_k = top_k

    def answer(self, patient_id: str, question: str) -> RagResponse:
        retrieved = self.evidence_store.search_patient_evidence(patient_id, question, top_k=self.top_k)
        if not retrieved:
            return RagResponse(
                answer="No patient-scoped evidence was retrieved. Generation is not configured.",
                cited_evidence_ids=[],
                retrieved_evidence=[],
                action="abstain",
                action_reason="No retrievable evidence for the requested patient.",
                prompt=build_prompt(question, []),
            )

        cited_ids = unique_parent_evidence_ids(retrieved)
        verify_citations(self.evidence_store, patient_id, cited_ids)
        snippets = "\n".join(f"- {item.evidence_id}: {item.text}" for item in retrieved)
        answer = (
            "Local generation is not configured. Retrieved patient-scoped evidence for review:\n"
            f"{snippets}"
        )
        return RagResponse(
            answer=answer,
            cited_evidence_ids=cited_ids,
            retrieved_evidence=[item.to_dict() for item in retrieved],
            action="uncertain",
            action_reason="Deterministic placeholder used because no local LLM client is configured.",
            prompt=build_prompt(question, retrieved),
        )


def build_prompt(question: str, retrieved: list[RetrievalResult]) -> str:
    evidence_block = "\n".join(
        f"[{index}] evidence_id={item.evidence_id} source_type={item.source_type} text={item.text}"
        for index, item in enumerate(retrieved, start=1)
    )
    return (
        "Answer using only the patient-scoped evidence below. Cite evidence_ids for material claims.\n\n"
        f"Question: {question}\n\n"
        f"Evidence:\n{evidence_block}"
    )


def unique_parent_evidence_ids(retrieved: list[RetrievalResult]) -> list[str]:
    seen = set()
    ids = []
    for item in retrieved:
        parent_id = item.metadata.get("parent_evidence_id") or item.evidence_id
        if parent_id not in seen:
            seen.add(parent_id)
            ids.append(parent_id)
    return ids


def verify_citations(store: EvidenceStore, patient_id: str, evidence_ids: list[str]) -> None:
    for evidence_id in evidence_ids:
        record = store.get_evidence_by_id(evidence_id)
        if record.patient_id != patient_id:
            raise AssertionError(f"Citation crosses patient boundary: {evidence_id}")
