from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.agent import QuestionPlanner, ToolAgentService
from chartground.local_llm import LocalLLMClient


CASES_ROOT = ROOT / "data/public_synthetic/cases"


def test_tool_agent_returns_shared_structured_response_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    service = ToolAgentService(cases_root=CASES_ROOT)
    response = service.answer_question("cg-syn-001", "What changed during this encounter?", architecture="tool_agent")
    data = response.to_dict()
    expected = {
        "answer",
        "patient_id",
        "case_id",
        "question",
        "architecture",
        "action",
        "action_reason",
        "cited_evidence_ids",
        "retrieved_evidence",
        "tool_calls",
        "missing_information",
        "conflicts",
        "limitations",
        "latency_ms",
    }
    assert expected <= set(data)
    assert data["architecture"] == "tool_agent"
    json.dumps(data)


@pytest.mark.parametrize(
    ("question", "expected_tools"),
    [
        ("What changed during this encounter?", {"build_patient_timeline", "search_clinical_notes", "detect_record_conflicts"}),
        ("Did creatinine worsen?", {"get_lab_trend", "search_clinical_notes"}),
        ("What medication changes occurred?", {"get_medication_changes", "search_clinical_notes"}),
        ("Compare radiology reports", {"compare_radiology_reports"}),
        ("What information is conflicting or missing?", {"detect_record_conflicts", "search_clinical_notes"}),
    ],
)
def test_planner_selects_expected_tools(question: str, expected_tools: set[str]) -> None:
    plan = QuestionPlanner().plan(question)
    assert {call.name for call in plan.tool_calls} == expected_tools


def test_patient_id_is_resolved_from_case_not_question_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    service = ToolAgentService(cases_root=CASES_ROOT)
    other_patient = service.store.get_case("cg-syn-006")["patient_id"]
    response = service.answer_question(
        "cg-syn-001",
        f"What changed for patient_id {other_patient}?",
        architecture="tool_agent",
    )
    assert response.patient_id == service.store.get_case("cg-syn-001")["patient_id"]
    assert response.patient_id != other_patient


def test_tool_agent_never_returns_cross_patient_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    service = ToolAgentService(cases_root=CASES_ROOT)
    response = service.answer_question("cg-syn-001", "What changed during this encounter?", architecture="tool_agent")
    assert all(item.get("patient_id") == response.patient_id for item in response.retrieved_evidence)
    for call in response.tool_calls:
        assert call["arguments"]["patient_id"] == response.patient_id


def test_cited_evidence_ids_exist_and_belong_to_requested_patient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    service = ToolAgentService(cases_root=CASES_ROOT)
    response = service.answer_question("cg-syn-001", "What changed during this encounter?", architecture="tool_agent")
    assert response.cited_evidence_ids
    for evidence_id in response.cited_evidence_ids:
        assert service.store.get_evidence_by_id(evidence_id).patient_id == response.patient_id


def test_fallback_answer_synthesis_works_without_local_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    service = ToolAgentService(cases_root=CASES_ROOT)
    response = service.answer_question("cg-syn-001", "What changed during this encounter?", architecture="tool_agent")
    assert response.answer
    assert any("Deterministic fallback" in limitation for limitation in response.limitations)


def test_ollama_configuration_is_optional_and_absence_does_not_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    result = LocalLLMClient().generate("prompt", "fallback")
    assert result.text == "fallback"
    assert result.used_provider == "deterministic_fallback"
    assert result.error


def test_existing_rag_architecture_still_returns_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")
    response = ToolAgentService(cases_root=CASES_ROOT).answer_question("cg-syn-001", "What changed?", architecture="rag")
    assert response.architecture == "rag"
    assert response.retrieved_evidence


def test_agent_demo_runs_on_one_case() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/agent_demo.py",
            "--case-id",
            "cg-syn-001",
            "--architecture",
            "tool_agent",
            "--question",
            "What changed during this encounter?",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "CHARTGROUND_LLM_PROVIDER": "none"},
    )
    assert "Architecture: tool_agent" in result.stdout
    assert "Tool calls used:" in result.stdout


def test_agent_demo_auto_rich_case_selects_valid_case() -> None:
    service = ToolAgentService(cases_root=CASES_ROOT)
    assert service.select_auto_rich_case() in service.store.list_cases()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/agent_demo.py",
            "--auto-rich-case",
            "--architecture",
            "tool_agent",
            "--question",
            "What changed during this encounter?",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "CHARTGROUND_LLM_PROVIDER": "none"},
    )
    assert "Case: cg-syn-" in result.stdout
