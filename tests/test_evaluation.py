from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.evaluation import (  # noqa: E402
    EvaluationTask,
    EvaluationValidationError,
    PublicEvaluationRunner,
    citation_precision,
    citation_recall,
    compute_metrics,
    load_public_evaluation_tasks,
    validate_task,
    write_evaluation_outputs,
)
from chartground.evidence_store import EvidenceStore  # noqa: E402


CASES_ROOT = ROOT / "data/public_synthetic/cases"


@pytest.fixture(autouse=True)
def no_cloud_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHARTGROUND_LLM_PROVIDER", "none")


def test_public_evaluation_tasks_load_with_adversarial_registry() -> None:
    tasks = load_public_evaluation_tasks(CASES_ROOT)
    assert len(tasks) >= 31
    assert len({task.task_id for task in tasks}) == len(tasks)
    adversarial_types = {task.adversarial_type for task in tasks if task.adversarial_type}
    assert {
        "prompt_injection",
        "cross_patient_contamination",
        "missing_evidence",
        "conflict_escalation",
        "unsupported_clinical_inference",
    } <= adversarial_types


def test_invalid_gold_evidence_is_caught() -> None:
    store = EvidenceStore(CASES_ROOT)
    case = store.get_case("cg-syn-001")
    task = EvaluationTask(
        task_id="bad-gold",
        case_id="cg-syn-001",
        patient_id=case["patient_id"],
        question="What changed?",
        task_type="fixture",
        gold_evidence_ids=["missing-evidence-id"],
    )
    with pytest.raises(EvaluationValidationError, match="unknown gold evidence_id"):
        validate_task(task, store)


def test_all_architectures_can_run_one_task() -> None:
    task = load_public_evaluation_tasks(CASES_ROOT, include_adversarial=False)[0]
    rows, failures = PublicEvaluationRunner(CASES_ROOT).run([task], ["rag", "tool_agent", "verified_agent"])
    assert not failures
    assert {row["architecture"] for row in rows} == {"rag", "tool_agent", "verified_agent"}
    assert all("actual_action" in row for row in rows)


def test_runner_records_errors_without_crashing() -> None:
    task = EvaluationTask(
        task_id="bad-case",
        case_id="missing-case",
        patient_id="missing-patient",
        question="What changed?",
        task_type="fixture",
    )
    rows, failures = PublicEvaluationRunner(CASES_ROOT).run([task], ["rag"])
    assert len(rows) == 1
    assert len(failures) == 1
    assert rows[0]["error"]["error_type"] == "KeyError"


def test_metrics_handle_gold_and_empty_gold_cases() -> None:
    rows = [
        {
            "architecture": "verified_agent",
            "expected_action": "answer",
            "actual_action": "answer",
            "action_correct": True,
            "gold_evidence_ids": ["a", "b"],
            "cited_evidence_ids": ["a", "c"],
            "claims": [{"claim_id": "c1"}],
            "unsupported_claims": [],
            "tool_calls": [{"tool_name": "search"}],
            "latency_ms": 10,
            "error": None,
            "cross_patient_violation": False,
            "prompt_injection_success": False,
        },
        {
            "architecture": "verified_agent",
            "expected_action": "abstain",
            "actual_action": "answer",
            "action_correct": False,
            "gold_evidence_ids": [],
            "cited_evidence_ids": [],
            "claims": [{"claim_id": "c2"}],
            "unsupported_claims": [{"claim_id": "c2"}],
            "tool_calls": [],
            "latency_ms": 20,
            "error": None,
            "cross_patient_violation": False,
            "prompt_injection_success": True,
        },
    ]
    metrics = compute_metrics(rows)["architectures"]["verified_agent"]
    assert citation_precision(rows[0]) == 0.5
    assert citation_recall(rows[0]) == 0.5
    assert metrics["citation_precision"] == 0.5
    assert metrics["citation_completeness"] == 0.5
    assert metrics["unsupported_claim_rate"] == 0.5
    assert metrics["prompt_injection_success_count"] == 1


def test_non_claim_architecture_claim_metrics_are_not_applicable() -> None:
    metrics = compute_metrics(
        [
            {
                "architecture": "rag",
                "expected_action": "answer",
                "actual_action": "answer",
                "action_correct": True,
                "gold_evidence_ids": [],
                "cited_evidence_ids": [],
                "claims": [],
                "unsupported_claims": [],
                "tool_calls": [],
                "latency_ms": 0,
                "error": None,
                "cross_patient_violation": False,
                "prompt_injection_success": False,
            }
        ]
    )
    assert metrics["architectures"]["rag"]["unsupported_claim_rate"] == "not_applicable"
    assert metrics["architectures"]["rag"]["citation_precision"] == "not_applicable"


def test_evaluation_outputs_are_created(tmp_path: Path) -> None:
    rows, failures = PublicEvaluationRunner(CASES_ROOT).run(load_public_evaluation_tasks(CASES_ROOT)[:1], ["rag"])
    metrics = compute_metrics(rows)
    write_evaluation_outputs(rows, failures, metrics, tmp_path)
    expected = {
        "run_results.jsonl",
        "aggregate_metrics.json",
        "architecture_scorecard.csv",
        "task_failures.jsonl",
        "safety_summary.json",
        "evaluation_summary.md",
    }
    assert expected == {path.name for path in tmp_path.iterdir()}
    assert json.loads((tmp_path / "aggregate_metrics.json").read_text(encoding="utf-8"))


def test_evaluation_scripts_run(tmp_path: Path) -> None:
    output = tmp_path / "eval"
    env = {**os.environ, "CHARTGROUND_LLM_PROVIDER": "none"}
    subprocess.run(
        [
            sys.executable,
            "scripts/run_public_evaluation.py",
            "--architectures",
            "rag",
            "verified_agent",
            "--limit",
            "2",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    scorecard = subprocess.run(
        [sys.executable, "scripts/print_scorecard.py", "--results", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "architecture" in scorecard.stdout
    memo_path = tmp_path / "launch-memo.md"
    subprocess.run(
        [
            sys.executable,
            "scripts/generate_launch_memo.py",
            "--results",
            str(output),
            "--output",
            str(memo_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Launch Decision Memo" in memo_path.read_text(encoding="utf-8")
