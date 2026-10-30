"""Claim extraction, citation validation, and safety policy for ChartGround."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from chartground.evidence_store import EvidenceRecord, EvidenceStore
from chartground.local_llm import LocalLLMClient
from chartground.response_schema import Claim


ADMIN_PREFIXES = ("intent:", "tool calls", "limitations:", "action:")
UNSAFE_USER_PATTERNS = ("ignore citations", "ignore safety", "ignore the evidence", "do not cite", "bypass")
CROSS_PATIENT_PATTERNS = ("another patient", "other patient", "patient_id", "cross-patient", "cross patient")
UNSUPPORTED_CLINICAL_INFERENCE_PATTERNS = (
    "what diagnosis",
    "diagnose",
    "what treatment",
    "should be started",
    "start treatment",
    "recommend a new medication",
    "recommend treatment",
)
CLINICAL_TERMS = (
    "radiology",
    "radiograph",
    "report",
    "lab",
    "laboratory",
    "numeric",
    "medication",
    "evidence",
    "timeline",
    "encounter",
    "chest",
    "pneumothorax",
    "effusion",
    "opacity",
    "creatinine",
    "hemoglobin",
    "changed",
)


class ClaimVerifier:
    def __init__(self, store: EvidenceStore, llm_client: LocalLLMClient | None = None) -> None:
        self.store = store
        self.llm_client = llm_client or LocalLLMClient()

    def extract_claims(self, answer: str) -> list[str]:
        fallback = deterministic_claims(answer)
        if self.llm_client.provider != "ollama":
            return fallback
        prompt = (
            "Extract material clinical claims as a JSON list of strings. "
            "Ignore administrative/status sentences.\n\n"
            f"Answer:\n{answer}"
        )
        result = self.llm_client.generate(prompt, json.dumps(fallback))
        try:
            parsed = json.loads(result.text)
        except json.JSONDecodeError:
            return fallback
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            return fallback
        return parsed

    def verify_claims(
        self,
        patient_id: str,
        answer: str,
        cited_evidence_ids: list[str],
    ) -> list[Claim]:
        claims = []
        claim_texts = self.extract_claims(answer)
        for index, text in enumerate(claim_texts, start=1):
            claim_citations = list(cited_evidence_ids)
            status, reason = self.verify_support(patient_id, text, claim_citations)
            claims.append(
                Claim(
                    claim_id=f"claim-{index:03d}",
                    text=text,
                    cited_evidence_ids=claim_citations,
                    support_status=status,
                    support_reason=reason,
                    severity_if_wrong=severity_for_claim(text),
                    verifier="deterministic",
                )
            )
        return claims

    def verify_support(self, patient_id: str, claim: str, cited_evidence_ids: list[str]) -> tuple[str, str]:
        valid_records, invalid_reasons = self.validate_citations(patient_id, cited_evidence_ids)
        if invalid_reasons:
            return "unsupported", "; ".join(invalid_reasons)
        if not valid_records:
            return "insufficient_evidence", "No valid patient-scoped clinical citations were provided."
        evidence_text = " ".join(f"{record.text} {record.source_time or ''} {record.event_time or ''}" for record in valid_records).lower()
        claim_text = claim.lower()
        if not numbers_match(claim_text, evidence_text):
            return "unsupported", "Numeric value in claim is not present in cited evidence."
        if not dates_match(claim_text, evidence_text):
            return "unsupported", "Date in claim is not present in cited evidence."
        overlap = clinical_term_overlap(claim_text, evidence_text)
        if overlap >= 2:
            return "supported", "Cited patient-scoped clinical evidence contains the key claim terms."
        if overlap == 1:
            return "partially_supported", "Cited evidence contains only limited key claim terms."
        return "insufficient_evidence", "Cited evidence does not clearly contain key clinical terms from the claim."

    def validate_citations(self, patient_id: str, cited_evidence_ids: list[str]) -> tuple[list[EvidenceRecord], list[str]]:
        records = []
        errors = []
        for evidence_id in cited_evidence_ids:
            try:
                record = self.store.get_evidence_by_id(evidence_id)
            except KeyError:
                errors.append(f"Cited evidence_id does not exist: {evidence_id}")
                continue
            if record.patient_id != patient_id:
                errors.append(f"Cited evidence_id belongs to another patient: {evidence_id}")
                continue
            if record.evidence_kind != "clinical_evidence":
                errors.append(f"Cited evidence_id is not clinical evidence: {evidence_id}")
                continue
            records.append(record)
        return records, errors


def deterministic_claims(answer: str) -> list[str]:
    claims = []
    for sentence in split_sentences(answer):
        lowered = sentence.lower().strip()
        if not lowered or lowered.startswith(ADMIN_PREFIXES):
            continue
        if lowered.startswith("evidence summary") or lowered.startswith("verification note"):
            continue
        if "cannot determine" in lowered or "missing/limited information" in lowered:
            continue
        if any(term in lowered for term in CLINICAL_TERMS):
            claims.append(sentence.strip())
    return claims


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.replace("\n", " ")) if part.strip()]


def numbers_match(claim: str, evidence: str) -> bool:
    numbers = re.findall(r"\b\d+(?:\.\d+)?\b", claim)
    if not numbers:
        return True
    evidence_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", evidence)
    evidence_values = {numeric_key(number) for number in evidence_numbers}
    return all(number in evidence or numeric_key(number) in evidence_values for number in numbers)


def numeric_key(value: str) -> str:
    try:
        return f"{float(value):.6g}"
    except ValueError:
        return value


def dates_match(claim: str, evidence: str) -> bool:
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", claim)
    if not dates:
        return True
    return all(date in evidence for date in dates)


def clinical_term_overlap(claim: str, evidence: str) -> int:
    claim_terms = set(content_terms(claim))
    evidence_terms = set(content_terms(evidence))
    return len(claim_terms & evidence_terms)


def content_terms(text: str) -> list[str]:
    stop = {"the", "and", "or", "a", "an", "of", "to", "from", "with", "has", "have", "is", "are", "one", "available"}
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2 and term not in stop]


def severity_for_claim(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("treatment", "diagnosis", "pneumothorax", "medication", "worsened")):
        return "high"
    if any(term in lowered for term in ("lab", "radiology", "report", "change")):
        return "medium"
    return "low"


def safety_findings(question: str, retrieved_evidence: list[dict[str, Any]]) -> list[str]:
    findings = []
    lowered_question = question.lower()
    if any(pattern in lowered_question for pattern in UNSAFE_USER_PATTERNS):
        findings.append("User request attempted to bypass citation or safety rules.")
    if any(pattern in lowered_question for pattern in CROSS_PATIENT_PATTERNS):
        findings.append("User request attempted to use cross-patient information.")
    if any(pattern in lowered_question for pattern in UNSUPPORTED_CLINICAL_INFERENCE_PATTERNS):
        findings.append("User requested unsupported diagnosis or treatment recommendation.")
    for item in retrieved_evidence:
        text = str(item.get("snippet") or item.get("text") or "").lower()
        if any(pattern in text for pattern in ("ignore previous instructions", "ignore citations", "system prompt")):
            findings.append("Retrieved note contains prompt-injection-like text; treated as evidence, not instruction.")
            break
    return findings


def unsupported_claim_dicts(claims: list[Claim]) -> list[dict[str, Any]]:
    return [
        asdict(claim)
        for claim in claims
        if claim.support_status in {"unsupported", "insufficient_evidence", "partially_supported"}
    ]


def choose_verified_action(
    claims: list[Claim],
    conflicts: list[dict[str, Any]],
    missing_information: list[str],
    safety: list[str],
) -> tuple[str, str]:
    if safety:
        return "abstain", "Safety policy prevented answering without trusted citations."
    if any(conflict.get("severity") == "high" for conflict in conflicts):
        return "escalate", "High-severity deterministic conflict detected."
    if any(claim.support_status == "unsupported" and claim.severity_if_wrong == "high" for claim in claims):
        return "abstain", "A high-severity claim is unsupported by patient-scoped evidence."
    if any(claim.support_status in {"unsupported", "insufficient_evidence"} for claim in claims):
        return "uncertain", "One or more claims lack sufficient patient-scoped support."
    if any(claim.support_status == "partially_supported" for claim in claims) or missing_information or conflicts:
        return "uncertain", "Evidence is incomplete, partial, or conflicting."
    return "answer", "All extracted claims are supported by patient-scoped clinical evidence."
