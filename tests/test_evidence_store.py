from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chartground.evidence_store import EvidenceStore
from chartground.rag import RagBaseline


CASES_ROOT = ROOT / "data/public_synthetic/cases"


def test_all_thirty_seven_cases_load_into_evidence_store() -> None:
    store = EvidenceStore(CASES_ROOT)
    assert store.list_cases() == [f"cg-syn-{index:03d}" for index in range(1, 38)]
    assert len(store.list_patients()) == 37


def test_every_evidence_record_has_patient_and_evidence_id() -> None:
    store = EvidenceStore(CASES_ROOT)
    for patient_id in store.list_patients():
        records = store.get_patient_evidence(patient_id)
        assert records
        for record in records:
            assert record.patient_id == patient_id
            assert record.evidence_id
            assert record.text
            assert record.evidence_kind in {
                "clinical_evidence",
                "provenance_metadata",
                "validation_safety_metadata",
                "case_documentation",
            }


def test_search_patient_evidence_excludes_non_clinical_metadata_by_default() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    all_records = store.get_patient_evidence(patient_id)
    assert any(record.evidence_kind == "validation_safety_metadata" for record in all_records)

    results = store.search_patient_evidence(patient_id, "cross-patient information used for this note", top_k=10)
    assert results
    assert all(result.evidence_kind == "clinical_evidence" for result in results)
    assert all("cross-patient" not in result.text.lower() for result in results)


def test_provenance_is_loaded_and_usable_for_validation() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    provenance = store.get_patient_provenance(patient_id)
    assert provenance
    evidence_ids = {record.evidence_id for record in store.get_patient_evidence(patient_id)}
    for record in provenance:
        assert record.patient_id == patient_id
        assert record.evidence_id in evidence_ids
        assert record.source_id


def test_search_patient_evidence_never_returns_other_patients() -> None:
    store = EvidenceStore(CASES_ROOT)
    patients = store.list_patients()
    for patient_id in patients:
        results = store.search_patient_evidence(patient_id, "Chest radiograph longitudinal evidence", top_k=10)
        assert results
        assert {result.patient_id for result in results} == {patient_id}
        assert {result.evidence_kind for result in results} == {"clinical_evidence"}


def test_changed_encounter_query_returns_clinical_evidence() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    results = store.search_patient_evidence(patient_id, "What changed during this encounter?", top_k=5)
    assert results
    clinical_source_markers = ("Encounter", "Observation", "Medication", "DiagnosticReport", "OverlayDiagnosticReport", "note:")
    assert all(result.evidence_kind == "clinical_evidence" for result in results)
    assert any(result.source_type.startswith(clinical_source_markers) for result in results)
    assert all("cross-patient" not in result.text.lower() for result in results)


def test_get_evidence_by_id_returns_expected_record() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    record = store.get_patient_evidence(patient_id)[0]
    assert store.get_evidence_by_id(record.evidence_id) == record


def test_rag_baseline_returns_structured_response_with_valid_citations() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_id = store.get_case("cg-syn-001")["patient_id"]
    response = RagBaseline(store).answer(patient_id, "What changed during this encounter?")
    response_dict = response.to_dict()

    assert response_dict["answer"]
    assert response_dict["action"] in {"answer", "uncertain", "escalate", "abstain"}
    assert response_dict["action_reason"]
    assert response_dict["retrieved_evidence"]
    assert response_dict["cited_evidence_ids"]
    for evidence_id in response.cited_evidence_ids:
        assert store.get_evidence_by_id(evidence_id).patient_id == patient_id


def test_querying_one_patient_for_another_patient_unique_evidence_stays_scoped() -> None:
    store = EvidenceStore(CASES_ROOT)
    patient_one = store.get_case("cg-syn-001")["patient_id"]
    patient_two = store.get_case("cg-syn-006")["patient_id"]
    other_patient_name = next(
        record.text
        for record in store.get_patient_evidence(patient_two)
        if record.source_type == "Patient"
    )

    results = store.search_patient_evidence(patient_one, other_patient_name, top_k=5)
    assert results
    assert {result.patient_id for result in results} == {patient_one}
    assert all(other_patient_name not in result.text for result in results)


def test_cli_demo_runs_successfully() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/rag_demo.py",
            "--case-id",
            "cg-syn-001",
            "--question",
            "What changed during this encounter?",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Case: cg-syn-001" in result.stdout
    assert "Answer:" in result.stdout
    assert "Cited evidence IDs:" in result.stdout
    assert "Retrieved evidence snippets:" in result.stdout
