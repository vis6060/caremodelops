"""Bounded public-case workflow reusing ChartGround retrieval, tools and policy."""

import json
import re
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from chartground.agent import QuestionPlanner, PlannedToolCall, cited_evidence_ids, infer_missing_information
from chartground.clinical_tools import ClinicalTools
from chartground.evidence_store import EvidenceStore, read_jsonl
from chartground.local_llm import LocalLLMClient
from chartground.response_schema import Claim
from chartground.verification import ClaimVerifier, choose_verified_action, safety_findings, severity_for_claim
from .client import generate
from .config import load_configuration

ROOT = Path(__file__).resolve().parents[3]
PUBLIC_ROOT = ROOT / "data/public_synthetic/cases"
LOG_ROOT = ROOT / "results/claude_runs"
FILES = ("patients.jsonl", "encounters.jsonl", "events.jsonl", "notes.jsonl",
         "evidence.jsonl", "provenance.jsonl")


def safe_path(path, boundary):
    if not path.resolve().is_relative_to(boundary.resolve()):
        raise ValueError("Source must stay inside the public synthetic allowlist.")
    for part in (path, *path.parents):
        try:
            tag = getattr(part.lstat(), "st_reparse_tag", None)
        except FileNotFoundError:
            tag = None
        is_junction = tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
        if part.is_symlink() or is_junction:
            raise ValueError("Linked source paths are not permitted.")


def snapshot(case_id, destination):
    if not re.fullmatch(r"cg-syn-\d{3}", case_id):
        raise ValueError("Only public cg-syn-NNN case IDs are permitted.")
    source = PUBLIC_ROOT / case_id
    safe_path(source, PUBLIC_ROOT)
    contents = {}
    for name in FILES:
        path = source / name
        safe_path(path, PUBLIC_ROOT)
        contents[name] = read_jsonl(path)
    patients = contents["patients.jsonl"]
    if len(patients) != 1 or not patients[0].get("patient_id"):
        raise ValueError("Expected one public synthetic patient.")
    patient = patients[0]["patient_id"]
    if (patients[0].get("source_id") != f"fhir:Patient/{patient}"
            or patients[0].get("metadata", {}).get("synthea_patient_id", patient) != patient):
        raise ValueError("Public Synthea source identity is required.")
    for rows in contents.values():
        for row in rows:
            if row.get("patient_id") != patient or row.get("case_id") != case_id:
                raise ValueError("Case/patient isolation violation.")
            if "mimic" in json.dumps(row).lower():
                raise ValueError("Restricted source content is not permitted.")
    target = destination / case_id
    target.mkdir()
    for name, rows in contents.items():
        (target / name).write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return patient


def bounded(value):
    if isinstance(value, dict):
        return {k: bounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bounded(v) for v in value[:6]]
    if isinstance(value, str):
        return value[:800]
    return value


def valid_answer(value):
    if not isinstance(value, dict) or not isinstance(value.get("answer"), str) or not value["answer"].strip():
        return False
    for key in ("cited_evidence_ids", "missing_information"):
        if not isinstance(value.get(key), list) or not all(isinstance(v, str) for v in value[key]):
            return False
    claims = value.get("claims")
    return (isinstance(claims, list) and len(claims) <= 3 and all(
        isinstance(c, dict) and isinstance(c.get("text"), str) and c["text"].strip()
        and isinstance(c.get("cited_evidence_ids"), list)
        and all(isinstance(v, str) for v in c["cited_evidence_ids"]) for c in claims)
        and value.get("suggested_action") in {"answer", "uncertain", "escalate", "abstain"})


def run(case_id, question, provider="mock", model=None):
    config = load_configuration()
    model = model if model is not None else config.model
    if provider not in {"mock", "claude"}:
        raise ValueError("Unsupported provider")
    if not question.strip() or len(question) > 2000:
        raise ValueError("Question must contain 1-2000 characters.")
    key = config.api_key
    if key and key in question:
        raise ValueError("Credentials must not appear in the question.")
    with tempfile.TemporaryDirectory(prefix="chartground-public-") as temp:
        patient = snapshot(case_id, Path(temp))
        store = EvidenceStore(temp)
        tools = ClinicalTools(store, temp)
        plan = QuestionPlanner().plan(question)
        calls = list(plan.tool_calls)
        if not any(call.name == "detect_record_conflicts" for call in calls):
            calls.insert(0, PlannedToolCall("detect_record_conflicts", {}))
        outputs = {call.name: tools.call_tool(call.name, patient_id=patient, **call.arguments) for call in calls}
        conflicts = outputs["detect_record_conflicts"]["conflicts"]
        retrieval = [r.to_dict() for r in store.search_patient_evidence(patient, question, 5)]
        # Conflicting sources take priority over general retrieval and medication history.
        important = [c for c in conflicts if c.get("severity") == "high"]
        # Relevant contradictions are indivisible: keep all sources and full text.
        medication_question = any(term in question.lower() for term in ("medication", "lisinopril", "medicine"))
        relevant_conflicts = [c for c in conflicts if c in important or (
            medication_question and "medication" in str(c.get("conflict_type", ""))) or (
            not medication_question and "conflict" in question.lower())]
        conflict_ids = {e for c in relevant_conflicts for e in c.get("supporting_evidence_ids", [])}
        ids = [eid for c in important for eid in c.get("supporting_evidence_ids", [])]
        if conflict_ids:
            ids = sorted(conflict_ids)
        else:
            ids += cited_evidence_ids(outputs, retrieval)
            ids += [r["evidence_id"] for r in retrieval]
        evidence = []
        for eid in dict.fromkeys(ids):
            record = store.get_evidence_by_id(eid)
            if record.patient_id != patient or record.case_id != case_id:
                raise ValueError("Cross-patient evidence blocked.")
            if record.evidence_kind == "clinical_evidence":
                evidence.append(dict(evidence_id=eid, patient_id=patient, case_id=case_id,
                                     text=record.text if eid in conflict_ids else record.text[:800], source_ids=list(record.source_ids)))
            elif eid in conflict_ids:
                raise ValueError("Conflict source is not clinical evidence.")
            if not conflict_ids and len(evidence) == 12:
                break
        missing = infer_missing_information(outputs, plan.intent)
        payload = dict(question=question, evidence=evidence, tool_outputs=bounded(outputs))
        if conflict_ids:
            payload["required_evidence_ids"] = sorted(conflict_ids)
            payload["tool_outputs"] = {"detect_record_conflicts": {"conflicts": relevant_conflicts}}
        if len(json.dumps(payload)) > 32000:
            if conflict_ids:
                raise ValueError("Complete conflict evidence exceeds prompt budget; generation blocked.")
            payload["tool_outputs"] = {"detect_record_conflicts": bounded(outputs["detect_record_conflicts"])}
            missing.append("Tool context was reduced to fit the prompt budget.")
        if len(json.dumps(payload)) > 32000:
            raise ValueError("Selected evidence exceeds prompt budget.")
        safety = safety_findings(question, evidence)
        if "ignore previous instructions" in question.lower():
            safety.append("Instruction override detected.")
        selected = [r for r in evidence if r["evidence_id"] in conflict_ids] if important else evidence[:4]
        fallback = dict(answer="Selected chart evidence:\n" + "\n".join(r["text"] for r in selected),
                        claims=[dict(text=r["text"], cited_evidence_ids=[r["evidence_id"]]) for r in selected[:3]],
                        cited_evidence_ids=[r["evidence_id"] for r in selected],
                        missing_information=missing, suggested_action="uncertain")
        if safety:
            draft, usage, error = generate("mock", None, payload, fallback)
            usage.update(provider=provider, status="blocked", model_id=None)
        else:
            draft, usage, error = generate(provider, model, payload, fallback)
        if not valid_answer(draft):
            draft = dict(answer="Generation unavailable; review the selected evidence.", claims=[],
                         cited_evidence_ids=[], missing_information=["No valid model answer."], suggested_action="uncertain")
            error = error or "Invalid structured model response."
        allowed = {r["evidence_id"] for r in evidence}
        proposed = draft["cited_evidence_ids"] + [eid for c in draft["claims"] for eid in c["cited_evidence_ids"]]
        invalid = sorted(set(proposed) - allowed)
        citations = list(dict.fromkeys(eid for eid in proposed if eid in allowed))
        if provider == "claude" and not error and conflict_ids - set(citations):
            error = "Claude omitted required contradictory evidence citations."
        verifier = ClaimVerifier(store, LocalLLMClient(provider="none"))
        checked = []
        for i, c in enumerate(draft["claims"]):
            status, reason = verifier.verify_support(patient, c["text"], c["cited_evidence_ids"])
            if any(eid not in allowed for eid in c["cited_evidence_ids"]):
                status, reason = "unsupported", "Citation was not supplied to the model."
            checked.append(Claim(str(i), c["text"], [e for e in c["cited_evidence_ids"] if e in allowed], status, reason, severity_for_claim(c["text"]), "deterministic"))
        missing += draft["missing_information"]
        if error or not checked or not citations:
            missing.append("Generation or cited claim support is incomplete.")
        if invalid:
            safety.append("Model returned citations outside the provided evidence.")
        action, reason = choose_verified_action(checked, conflicts, missing, safety)
        if action == "answer":
            action, reason = "uncertain", "Lexical support checks do not establish clinical claim correctness."
        answer = draft["answer"]
        answer_source = "claude" if provider == "claude" and not error and not invalid and checked and citations else "deterministic_fallback"
        if action == "abstain":
            answer = "Request or generated citations failed safety checks. Review the selected chart evidence."
            answer_source = "deterministic_fallback"
        elif action == "escalate" and answer_source != "claude":
            answer = "Escalation required: " + " ".join(c["description"] for c in conflicts if c.get("severity") == "high")
            answer += "\nConflicting source evidence:\n" + "\n".join(r["text"] for r in selected)
            citations = [r["evidence_id"] for r in selected]
        elif answer_source != "claude" and provider == "claude" and error:
            answer = "Generation unavailable; review the selected evidence."
        if provider == "claude" and answer_source != "claude":
            error = error or "Claude generation did not pass application validation."
        result = dict(case_id=case_id, patient_id=patient, provider=provider, answer=answer,
                      answer_source=answer_source, status="success" if answer_source == "claude" else "fallback",
                      action=action, action_reason=reason, cited_evidence_ids=citations,
                      invalid_citation_ids=invalid, claims=[asdict(c) for c in checked],
                      missing_information=list(dict.fromkeys(missing)), suggested_action=draft["suggested_action"],
                      plan=[asdict(c) for c in calls], tool_calls=payload["tool_outputs"],
                      evidence=evidence, usage=usage, error=error,
                      verification="Deterministic lexical checks only; not clinical verification.")
        safe_path(LOG_ROOT, ROOT)
        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(result, indent=2)
        if key:
            serialized = serialized.replace(key, "[REDACTED]")
        (LOG_ROOT / (uuid4().hex + ".json")).write_text(serialized, encoding="utf-8")
        return json.loads(serialized)
