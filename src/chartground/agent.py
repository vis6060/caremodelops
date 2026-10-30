"""Tool-using agent layer for ChartGround."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chartground.clinical_tools import ClinicalTools
from chartground.evidence_store import DEFAULT_CASES_ROOT, EvidenceStore
from chartground.local_llm import LocalLLMClient
from chartground.rag import RagBaseline
from chartground.response_schema import AgentResponse
from chartground.verification import ClaimVerifier, choose_verified_action, safety_findings, unsupported_claim_dicts


MAX_TOOL_CALLS = 5


@dataclass(frozen=True)
class PlannedToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Plan:
    intent: str
    tool_calls: list[PlannedToolCall]
    missing_information: list[str]


class QuestionPlanner:
    """Small deterministic planner for first-pass tool selection."""

    def plan(self, question: str) -> Plan:
        lowered = question.lower()
        tokens = set(re.findall(r"[a-z0-9]+", lowered))
        calls: list[PlannedToolCall] = []
        missing: list[str] = []
        if (
            any(term in lowered for term in ("creatinine", "hemoglobin", "sodium", "potassium", "platelet", "glucose", "troponin", "procalcitonin"))
            or bool(tokens & {"lab", "labs", "laboratory", "worsen", "worsened"})
        ):
            lab_name = detect_lab_name(lowered)
            calls.append(PlannedToolCall("get_lab_trend", {"lab_name": lab_name}))
            calls.append(PlannedToolCall("search_clinical_notes", {"query": question, "top_k": 5}))
            return Plan("lab_trend", calls, [] if lab_name else ["No specific lab name detected; defaulted to lab."])
        if any(term in lowered for term in ("medication", "medications", "med", "started", "stopped")):
            return Plan(
                "medication_changes",
                [
                    PlannedToolCall("get_medication_changes", {}),
                    PlannedToolCall("search_clinical_notes", {"query": question, "top_k": 5}),
                ],
                [],
            )
        if any(term in lowered for term in ("conflict", "conflicting", "missing", "insufficient")):
            return Plan(
                "conflict_review",
                [
                    PlannedToolCall("detect_record_conflicts", {}),
                    PlannedToolCall("search_clinical_notes", {"query": question, "top_k": 5}),
                ],
                [],
            )
        if is_radiology_question(lowered):
            if "compare" not in lowered and any(term in lowered for term in ("exists", "exist", "available")):
                return Plan("diagnostic_evidence_check", [PlannedToolCall("compare_radiology_reports", {})], [])
            return Plan("radiology_comparison", [PlannedToolCall("compare_radiology_reports", {})], [])
        if any(term in lowered for term in ("changed", "timeline", "during this encounter", "what happened")):
            return Plan(
                "timeline_summary",
                [
                    PlannedToolCall("build_patient_timeline", {}),
                    PlannedToolCall("search_clinical_notes", {"query": question, "top_k": 5}),
                    PlannedToolCall("detect_record_conflicts", {}),
                ],
                [],
            )
        return Plan("general_grounded_qa", [PlannedToolCall("search_clinical_notes", {"query": question, "top_k": 5})], [])


class ToolAgentService:
    """Runs planned deterministic tools and synthesizes a structured answer."""

    def __init__(
        self,
        cases_root: Path | str = DEFAULT_CASES_ROOT,
        evidence_store: EvidenceStore | None = None,
        llm_client: LocalLLMClient | None = None,
    ) -> None:
        self.store = evidence_store or EvidenceStore(cases_root)
        self.cases_root = Path(cases_root)
        self.tools = ClinicalTools(self.store, self.cases_root)
        self.planner = QuestionPlanner()
        self.llm_client = llm_client or LocalLLMClient()
        self.verifier = ClaimVerifier(self.store, self.llm_client)

    def answer_question(self, case_id: str, question: str, architecture: str = "tool_agent") -> AgentResponse:
        started = time.perf_counter()
        case = self.store.get_case(case_id)
        patient_id = case["patient_id"]
        if architecture == "rag":
            rag_response = RagBaseline(self.store).answer(patient_id, question)
            return AgentResponse(
                answer=rag_response.answer,
                patient_id=patient_id,
                case_id=case_id,
                question=question,
                architecture="rag",
                action=rag_response.action,
                action_reason=rag_response.action_reason,
                cited_evidence_ids=rag_response.cited_evidence_ids,
                retrieved_evidence=rag_response.retrieved_evidence,
                limitations=["RAG baseline does not use deterministic clinical tools."],
                latency_ms=elapsed_ms(started),
            )
        if architecture == "verified_agent":
            return self._answer_verified(case_id, patient_id, question, started)
        if architecture != "tool_agent":
            raise ValueError(f"Unsupported architecture: {architecture}")
        return self._answer_with_tools(case_id, patient_id, question, started)

    def _answer_with_tools(self, case_id: str, patient_id: str, question: str, started: float) -> AgentResponse:
        plan = self.planner.plan(question)
        tool_calls = []
        tool_outputs: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        retrieved_evidence: list[dict[str, Any]] = []
        missing_information = list(plan.missing_information)

        for planned in plan.tool_calls[:MAX_TOOL_CALLS]:
            args = {"patient_id": patient_id, **planned.arguments}
            try:
                output = getattr(self.tools, planned.name)(**args)
                status = "ok"
            except (KeyError, ValueError, TypeError) as exc:
                output = {"error": str(exc)}
                status = "error"
            tool_calls.append({"tool_name": planned.name, "arguments": args, "status": status, "output": output})
            tool_outputs[planned.name] = output
            if planned.name == "detect_record_conflicts" and isinstance(output, dict):
                conflicts = output.get("conflicts", [])
            if planned.name == "search_clinical_notes" and isinstance(output, list):
                retrieved_evidence = output

        cited_ids = cited_evidence_ids(tool_outputs, retrieved_evidence)
        cited_ids = [evidence_id for evidence_id in cited_ids if citation_belongs_to_patient(self.store, patient_id, evidence_id)]
        missing_information.extend(infer_missing_information(tool_outputs, plan.intent))
        fallback_answer = synthesize_fallback_answer(plan.intent, tool_outputs, missing_information, conflicts)
        llm_result = self.llm_client.generate(build_agent_prompt(question, tool_outputs, cited_ids), fallback_answer)
        answer = llm_result.text or fallback_answer
        if llm_result.used_provider == "ollama":
            answer = strip_untrusted_citations(answer, cited_ids)
        action, reason = choose_action(missing_information, conflicts, llm_result)
        limitations = [
            "Full claim verification is not implemented.",
            "Synthetic public demo only.",
        ]
        if llm_result.used_provider != "ollama":
            limitations.append("Deterministic fallback synthesis used because no local LLM was configured.")
        elif llm_result.error:
            limitations.append(llm_result.error)
        return AgentResponse(
            answer=answer,
            patient_id=patient_id,
            case_id=case_id,
            question=question,
            architecture="tool_agent",
            action=action,
            action_reason=reason,
            cited_evidence_ids=cited_ids,
            retrieved_evidence=retrieved_evidence,
            tool_calls=tool_calls,
            missing_information=unique(missing_information),
            conflicts=conflicts,
            limitations=limitations,
            latency_ms=elapsed_ms(started),
        )

    def _answer_verified(self, case_id: str, patient_id: str, question: str, started: float) -> AgentResponse:
        draft = self._answer_with_tools(case_id, patient_id, question, started)
        safety = safety_findings(question, draft.retrieved_evidence)
        claims = self.verifier.verify_claims(patient_id, draft.answer, draft.cited_evidence_ids)
        unsupported = unsupported_claim_dicts(claims)
        action, reason = choose_verified_action(claims, draft.conflicts, draft.missing_information, safety)
        limitations = [
            *draft.limitations,
            "Deterministic claim verification is conservative.",
            "Retrieved note text is treated as evidence, never instruction.",
        ]
        if safety:
            limitations.extend(safety)
        answer = constrain_answer(draft.answer, unsupported, safety)
        return AgentResponse(
            answer=answer,
            patient_id=patient_id,
            case_id=case_id,
            question=question,
            architecture="verified_agent",
            action=action,
            action_reason=reason,
            claims=[claim.to_dict() for claim in claims],
            cited_evidence_ids=draft.cited_evidence_ids,
            unsupported_claims=unsupported,
            retrieved_evidence=draft.retrieved_evidence,
            tool_calls=draft.tool_calls,
            missing_information=draft.missing_information,
            conflicts=draft.conflicts,
            limitations=unique(limitations),
            latency_ms=elapsed_ms(started),
        )

    def select_auto_rich_case(self) -> str:
        scored = []
        for case_id in self.store.list_cases():
            patient_id = self.store.get_case(case_id)["patient_id"]
            timeline = self.tools.build_patient_timeline(patient_id)
            meds = self.tools.get_medication_changes(patient_id)
            radiology = self.tools.compare_radiology_reports(patient_id)
            labs = [row for row in timeline if row.get("event_type") == "observation"]
            score = len(timeline) + len(labs) * 3 + radiology["report_count"] * 2
            score += sum(len(meds[key]) for key in ("medications_started", "medications_stopped", "medications_continued", "medications_uncertain"))
            scored.append((score, case_id))
        return sorted(scored, key=lambda item: (-item[0], item[1]))[0][1]


def answer_question(case_id: str, question: str, architecture: str = "rag", cases_root: Path | str = DEFAULT_CASES_ROOT) -> AgentResponse:
    return ToolAgentService(cases_root=cases_root).answer_question(case_id, question, architecture=architecture)


def constrain_answer(answer: str, unsupported: list[dict[str, Any]], safety: list[str]) -> str:
    if safety:
        return "I cannot answer this request as written because it attempts to bypass citation or safety rules."
    if unsupported:
        return answer + " Verification note: some extracted claims are not fully supported by the cited patient-scoped evidence."
    return answer


def detect_lab_name(question: str) -> str:
    for lab_name in ("creatinine", "hemoglobin", "sodium", "potassium", "platelet", "glucose", "troponin", "procalcitonin"):
        if lab_name in question:
            return lab_name
    return "lab"


def is_radiology_question(question: str) -> bool:
    if any(term in question for term in ("radiology", "x-ray", "xray", "imaging")):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", question))
    return bool(tokens & {"ct", "mri"})


def cited_evidence_ids(tool_outputs: dict[str, Any], retrieved_evidence: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    structured_ids: list[str] = []
    timeline = tool_outputs.get("build_patient_timeline")
    if isinstance(timeline, list):
        structured_ids.extend(str(row.get("evidence_id")) for row in timeline[:5] if row.get("evidence_id"))
    radiology = tool_outputs.get("compare_radiology_reports")
    if isinstance(radiology, dict):
        structured_ids.extend(radiology.get("supporting_evidence_ids", []))
    medication = tool_outputs.get("get_medication_changes")
    if isinstance(medication, dict):
        for key in ("medications_started", "medications_stopped", "medications_continued", "medications_uncertain"):
            for item in medication.get(key, []):
                structured_ids.extend(item.get("evidence_ids", []))
    lab = tool_outputs.get("get_lab_trend")
    if isinstance(lab, dict):
        if lab.get("first") and lab.get("last"):
            structured_ids.extend(lab["first"].get("evidence_ids", []))
            structured_ids.extend(lab["last"].get("evidence_ids", []))
        else:
            for item in lab.get("observations", [])[:2]:
                structured_ids.extend(item.get("evidence_ids", []))
    conflicts = tool_outputs.get("detect_record_conflicts")
    if isinstance(conflicts, dict):
        for conflict in conflicts.get("conflicts", []):
            structured_ids.extend(conflict.get("supporting_evidence_ids", []))
    ids.extend(structured_ids)
    if not structured_ids:
        for item in retrieved_evidence:
            ids.append(str(item.get("evidence_id")))
    return unique([item for item in ids if item and item != "None"])


def citation_belongs_to_patient(store: EvidenceStore, patient_id: str, evidence_id: str) -> bool:
    try:
        return store.get_evidence_by_id(evidence_id).patient_id == patient_id
    except KeyError:
        return False


def infer_missing_information(tool_outputs: dict[str, Any], intent: str = "") -> list[str]:
    missing = []
    lab = tool_outputs.get("get_lab_trend")
    if isinstance(lab, dict) and lab.get("direction") == "insufficient_data":
        missing.append(f"Insufficient numeric lab data for {lab.get('lab_name')}.")
    radiology = tool_outputs.get("compare_radiology_reports")
    if isinstance(radiology, dict) and radiology.get("insufficient_data") and intent != "diagnostic_evidence_check":
        missing.append("Fewer than two radiology reports are available for comparison.")
    medication = tool_outputs.get("get_medication_changes")
    if isinstance(medication, dict) and medication.get("medications_uncertain") and not any(
        medication.get(key) for key in ("medications_started", "medications_stopped", "medications_continued")
    ):
        missing.append("Medication changes are uncertain from available evidence.")
    return missing


def synthesize_fallback_answer(intent: str, tool_outputs: dict[str, Any], missing: list[str], conflicts: list[dict[str, Any]]) -> str:
    parts = [f"Evidence summary for {intent}."]
    timeline = tool_outputs.get("build_patient_timeline")
    if isinstance(timeline, list):
        if timeline:
            first_item = timeline[0]
            latest_item = timeline[-1]
            parts.append(f"Earliest timeline evidence: {first_item.get('display')} on {first_item.get('event_time') or 'an unknown date'}.")
            parts.append(f"Latest timeline evidence: {latest_item.get('display')} on {latest_item.get('event_time') or 'an unknown date'}.")
    lab = tool_outputs.get("get_lab_trend")
    if isinstance(lab, dict):
        if lab.get("first") and lab.get("last"):
            first_obs = lab["first"]
            last_obs = lab["last"]
            unit = first_obs.get("unit") or last_obs.get("unit") or ""
            parts.append(
                f"Numeric laboratory evidence for {first_obs.get('display') or lab.get('lab_name')} changed from "
                f"{first_obs.get('value')} {unit} on {first_obs.get('date')} to {last_obs.get('value')} {unit} on {last_obs.get('date')}; "
                f"the deterministic direction is {lab.get('direction')}."
            )
        else:
            parts.append(f"Numeric laboratory evidence for {lab.get('lab_name')} is incomplete.")
    medication = tool_outputs.get("get_medication_changes")
    if isinstance(medication, dict):
        named = first_named_medication(medication)
        if named:
            parts.append(f"Medication evidence includes {named}.")
        elif medication.get("medications_uncertain"):
            parts.append("Medication changes are uncertain from available evidence.")
        else:
            parts.append("Medication changes were classified deterministically from available evidence.")
    radiology = tool_outputs.get("compare_radiology_reports")
    if isinstance(radiology, dict):
        reports = radiology.get("reports") or []
        if radiology.get("insufficient_data") and intent == "diagnostic_evidence_check":
            report = first_report_snippet(reports)
            parts.append(f"Diagnostic or imaging evidence is available: {report}.")
        elif radiology.get("insufficient_data"):
            parts.append("Radiology comparison is limited because fewer than two reports are available.")
        else:
            earliest = first_report_snippet([radiology.get("earliest_report")] if radiology.get("earliest_report") else reports)
            latest = first_report_snippet([radiology.get("latest_report")] if radiology.get("latest_report") else reports[-1:])
            parts.append(f"Radiology comparison uses earlier report evidence: {earliest}.")
            parts.append(f"Radiology comparison uses later report evidence: {latest}.")
            if radiology.get("new_or_changed_findings"):
                parts.append("Deterministic comparison found changed radiology language.")
    notes = tool_outputs.get("search_clinical_notes")
    if isinstance(notes, list) and notes and len(parts) == 1:
        parts.append(f"Top note evidence: {notes[0].get('snippet')}")
    if conflicts:
        parts.append("A clinically important chart conflict was detected and should be escalated.")
    if missing:
        parts.append("Missing/limited information: " + " ".join(unique(missing)))
    return " ".join(parts)


def first_named_medication(medication: dict[str, Any]) -> str | None:
    for key in ("medications_started", "medications_stopped", "medications_continued", "medications_uncertain"):
        for item in medication.get(key, []):
            name = str(item.get("name") or "").strip()
            if name and name != "No medication evidence found":
                return name
    return None


def first_report_snippet(reports: list[dict[str, Any]]) -> str:
    for report in reports:
        snippet = str((report or {}).get("snippet") or "").strip()
        if snippet:
            words = snippet.split()
            return " ".join(words[:18])
    return "radiology report evidence"


def build_agent_prompt(question: str, tool_outputs: dict[str, Any], cited_ids: list[str]) -> str:
    return (
        "Use only the provided ChartGround tool outputs. Do not invent citations.\n"
        f"Question: {question}\n"
        f"Allowed evidence ids: {', '.join(cited_ids)}\n"
        f"Tool outputs: {tool_outputs}\n"
    )


def strip_untrusted_citations(answer: str, allowed_ids: list[str]) -> str:
    # Full citation verification is a later milestone; keep the text but citations are controlled separately.
    return answer


def choose_action(missing: list[str], conflicts: list[dict[str, Any]], llm_result: Any) -> tuple[str, str]:
    if any(conflict.get("severity") == "high" for conflict in conflicts):
        return "escalate", "High-severity deterministic conflict detected."
    if missing or conflicts:
        return "uncertain", "Evidence is incomplete or conflicts require caution."
    return "answer", "Patient-scoped deterministic tools returned usable evidence."


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def unique(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
