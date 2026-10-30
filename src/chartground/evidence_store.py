"""Patient-scoped evidence loading and keyword retrieval for ChartGround."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_CASES_ROOT = Path("data/public_synthetic/cases")
MAX_CHUNK_WORDS = 90
CHUNK_OVERLAP_WORDS = 15


class EvidenceStoreValidationError(ValueError):
    """Raised when public synthetic evidence cannot be loaded safely."""


@dataclass(frozen=True)
class EvidenceRecord:
    case_id: str
    patient_id: str
    encounter_id: str | None
    evidence_id: str
    source_type: str
    source_time: str | None
    event_time: str | None
    text: str
    source_ids: tuple[str, ...]
    evidence_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvenanceRecord:
    case_id: str
    patient_id: str
    provenance_id: str
    note_id: str
    sentence_id: str
    evidence_id: str
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceChunk:
    chunk_id: str
    evidence_id: str
    patient_id: str
    case_id: str
    source_type: str
    source_time: str | None
    text: str
    source_ids: tuple[str, ...]
    evidence_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    evidence_id: str
    patient_id: str
    source_type: str
    source_time: str | None
    text: str
    score: float
    source_ids: tuple[str, ...]
    evidence_kind: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_ids"] = list(self.source_ids)
        return value


class EvidenceStore:
    """In-memory evidence store with patient filtering before ranking."""

    def __init__(self, cases_root: Path | str = DEFAULT_CASES_ROOT) -> None:
        self.cases_root = Path(cases_root)
        self._cases: dict[str, dict[str, Any]] = {}
        self._patients: dict[str, dict[str, Any]] = {}
        self._records: list[EvidenceRecord] = []
        self._provenance: list[ProvenanceRecord] = []
        self._chunks: list[EvidenceChunk] = []
        self._evidence_by_id: dict[str, EvidenceRecord] = {}
        self._chunks_by_patient: dict[str, list[EvidenceChunk]] = {}
        self._load()

    def list_cases(self) -> list[str]:
        return sorted(self._cases)

    def list_patients(self) -> list[str]:
        return sorted(self._patients)

    def get_case(self, case_id: str) -> dict[str, Any]:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise KeyError(f"Unknown case_id: {case_id}") from exc

    def get_patient_evidence(self, patient_id: str) -> list[EvidenceRecord]:
        return [record for record in self._records if record.patient_id == patient_id]

    def get_patient_provenance(self, patient_id: str) -> list[ProvenanceRecord]:
        return [record for record in self._provenance if record.patient_id == patient_id]

    def get_evidence_by_id(self, evidence_id: str) -> EvidenceRecord:
        try:
            return self._evidence_by_id[evidence_id]
        except KeyError as exc:
            raise KeyError(f"Unknown evidence_id: {evidence_id}") from exc

    def search_patient_evidence(
        self,
        patient_id: str,
        query: str,
        top_k: int = 5,
        evidence_kinds: tuple[str, ...] = ("clinical_evidence",),
    ) -> list[RetrievalResult]:
        if top_k < 1:
            return []
        patient_chunks = [
            chunk
            for chunk in self._chunks_by_patient.get(patient_id, [])
            if not evidence_kinds or chunk.evidence_kind in evidence_kinds
        ]
        if not patient_chunks:
            return []

        query_terms = tokenize(query)
        if not query_terms:
            scored = [(0.0, chunk) for chunk in patient_chunks]
        else:
            scored = score_chunks(patient_chunks, query_terms)

        results = []
        for score, chunk in sorted(scored, key=lambda item: (-item[0], item[1].source_time or "", item[1].chunk_id))[:top_k]:
            if chunk.patient_id != patient_id:
                raise AssertionError("patient-scoped retrieval attempted to return cross-patient evidence")
            results.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    evidence_id=chunk.evidence_id,
                    patient_id=chunk.patient_id,
                    source_type=chunk.source_type,
                    source_time=chunk.source_time,
                    text=chunk.text,
                    score=round(score, 6),
                    source_ids=chunk.source_ids,
                    evidence_kind=chunk.evidence_kind,
                    metadata=chunk.metadata,
                )
            )
        return results

    def _load(self) -> None:
        if not self.cases_root.exists():
            raise EvidenceStoreValidationError(f"Cases root does not exist: {self.cases_root}")
        case_dirs = sorted(path for path in self.cases_root.iterdir() if path.is_dir())
        if not case_dirs:
            raise EvidenceStoreValidationError(f"No case directories found in {self.cases_root}")
        for case_dir in case_dirs:
            self._load_case(case_dir)
        self._chunks_by_patient = {}
        for record in self._records:
            if record.evidence_id in self._evidence_by_id:
                raise EvidenceStoreValidationError(f"Duplicate evidence_id: {record.evidence_id}")
            self._evidence_by_id[record.evidence_id] = record
            for chunk in chunk_record(record):
                self._chunks.append(chunk)
                self._chunks_by_patient.setdefault(chunk.patient_id, []).append(chunk)

    def _load_case(self, case_dir: Path) -> None:
        case_id = case_dir.name
        patients = read_jsonl(case_dir / "patients.jsonl")
        if len(patients) != 1:
            raise EvidenceStoreValidationError(f"{case_id}: patients.jsonl must contain exactly one row")
        patient = patients[0]
        patient_id = require_str(patient, "patient_id", case_id)
        if require_str(patient, "case_id", case_id) != case_id:
            raise EvidenceStoreValidationError(f"{case_id}: patient row case_id does not match directory name")
        self._cases[case_id] = {"case_id": case_id, "patient_id": patient_id, "case_dir": str(case_dir)}
        self._patients[patient_id] = patient

        structured = read_jsonl(case_dir / "evidence.jsonl")
        structured_by_id: dict[str, dict[str, Any]] = {}
        for row in structured:
            record = structured_evidence_record(case_id, patient_id, row)
            structured_by_id[record.evidence_id] = row
            self._records.append(record)

        notes = read_jsonl(case_dir / "notes.jsonl")
        provenance = read_jsonl(case_dir / "provenance.jsonl")
        provenance_by_sentence = {}
        for row in provenance:
            provenance_record = load_provenance_record(case_id, patient_id, row)
            self._provenance.append(provenance_record)
            provenance_by_sentence[(row.get("note_id"), row.get("sentence_id"))] = row
        for note in notes:
            if note.get("case_id") != case_id or note.get("patient_id") != patient_id:
                raise EvidenceStoreValidationError(f"{case_id}: note patient/case isolation violation")
            for sentence in note.get("sentences", []):
                key = (note.get("note_id"), sentence.get("sentence_id"))
                if key not in provenance_by_sentence:
                    raise EvidenceStoreValidationError(f"{case_id}: sentence missing provenance: {key}")
                prov = provenance_by_sentence[key]
                parent_id = require_str(prov, "evidence_id", case_id)
                if parent_id not in structured_by_id:
                    raise EvidenceStoreValidationError(f"{case_id}: note provenance references missing evidence_id {parent_id}")
                self._records.append(note_sentence_record(case_id, patient_id, note, sentence, prov, structured_by_id[parent_id]))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise EvidenceStoreValidationError(f"Required file is missing: {path}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceStoreValidationError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise EvidenceStoreValidationError(f"{path}:{line_number}: expected JSON object")
        rows.append(row)
    return rows


def structured_evidence_record(case_id: str, patient_id: str, row: dict[str, Any]) -> EvidenceRecord:
    if row.get("case_id") != case_id or row.get("patient_id") != patient_id:
        raise EvidenceStoreValidationError(f"{case_id}: evidence patient/case isolation violation")
    evidence_id = require_str(row, "evidence_id", case_id)
    label = str(row.get("label") or "")
    value = str(row.get("value") or "")
    code = str(row.get("code") or "")
    text = ". ".join(part for part in (label, value, code) if part).strip()
    if not text:
        raise EvidenceStoreValidationError(f"{case_id}: evidence {evidence_id} has no searchable text")
    source_id = require_str(row, "source_id", case_id)
    source_type = str(row.get("resource_type") or row.get("source_kind") or "structured_evidence")
    source_time = row.get("date")
    evidence_kind = structured_evidence_kind(row)
    return EvidenceRecord(
        case_id=case_id,
        patient_id=patient_id,
        encounter_id=row.get("encounter_id"),
        evidence_id=evidence_id,
        source_type=source_type,
        source_time=source_time,
        event_time=source_time,
        text=text,
        source_ids=(source_id,),
        evidence_kind=evidence_kind,
        metadata={"source_kind": row.get("source_kind"), "resource_type": row.get("resource_type"), "code": row.get("code")},
    )


def note_sentence_record(
    case_id: str,
    patient_id: str,
    note: dict[str, Any],
    sentence: dict[str, Any],
    provenance: dict[str, Any],
    parent: dict[str, Any],
) -> EvidenceRecord:
    if provenance.get("case_id") != case_id or provenance.get("patient_id") != patient_id:
        raise EvidenceStoreValidationError(f"{case_id}: provenance patient/case isolation violation")
    sentence_id = require_str(sentence, "sentence_id", case_id)
    text = require_str(sentence, "text", case_id)
    parent_id = require_str(provenance, "evidence_id", case_id)
    note_id = require_str(note, "note_id", case_id)
    source_id = require_str(provenance, "source_id", case_id)
    if parent.get("source_id") != source_id:
        raise EvidenceStoreValidationError(f"{case_id}: provenance source_id does not match parent evidence")
    evidence_kind = note_sentence_evidence_kind(text)
    return EvidenceRecord(
        case_id=case_id,
        patient_id=patient_id,
        encounter_id=parent.get("encounter_id"),
        evidence_id=f"{parent_id}#sentence:{sentence_id}",
        source_type=f"note:{note.get('note_type') or 'unknown'}",
        source_time=note.get("created_at") or parent.get("date"),
        event_time=parent.get("date"),
        text=text,
        source_ids=(source_id,),
        evidence_kind=evidence_kind,
        metadata={
            "parent_evidence_id": parent_id,
            "note_id": note_id,
            "sentence_id": sentence_id,
            "claim_type": provenance.get("claim_type"),
        },
    )


def load_provenance_record(case_id: str, patient_id: str, row: dict[str, Any]) -> ProvenanceRecord:
    if row.get("case_id") != case_id or row.get("patient_id") != patient_id:
        raise EvidenceStoreValidationError(f"{case_id}: provenance patient/case isolation violation")
    return ProvenanceRecord(
        case_id=case_id,
        patient_id=patient_id,
        provenance_id=require_str(row, "provenance_id", case_id),
        note_id=require_str(row, "note_id", case_id),
        sentence_id=require_str(row, "sentence_id", case_id),
        evidence_id=require_str(row, "evidence_id", case_id),
        source_id=require_str(row, "source_id", case_id),
        metadata={"claim_type": row.get("claim_type"), "generated_at": row.get("generated_at")},
    )


def structured_evidence_kind(row: dict[str, Any]) -> str:
    resource_type = row.get("resource_type")
    if resource_type == "Patient":
        return "case_documentation"
    return "clinical_evidence"


def note_sentence_evidence_kind(text: str) -> str:
    lowered = text.lower()
    if "cross-patient" in lowered or "used for this note" in lowered:
        return "validation_safety_metadata"
    if "provenance" in lowered or "source id" in lowered:
        return "provenance_metadata"
    return "clinical_evidence"


def chunk_record(record: EvidenceRecord) -> list[EvidenceChunk]:
    words = record.text.split()
    if len(words) <= MAX_CHUNK_WORDS:
        return [make_chunk(record, 1, record.text)]
    chunks = []
    step = MAX_CHUNK_WORDS - CHUNK_OVERLAP_WORDS
    start = 0
    index = 1
    while start < len(words):
        end = min(start + MAX_CHUNK_WORDS, len(words))
        chunks.append(make_chunk(record, index, " ".join(words[start:end])))
        if end == len(words):
            break
        start += step
        index += 1
    return chunks


def make_chunk(record: EvidenceRecord, index: int, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"{record.evidence_id}::chunk-{index:03d}",
        evidence_id=record.evidence_id,
        patient_id=record.patient_id,
        case_id=record.case_id,
        source_type=record.source_type,
        source_time=record.source_time,
        text=text,
        source_ids=record.source_ids,
        evidence_kind=record.evidence_kind,
        metadata=record.metadata,
    )


def score_chunks(chunks: list[EvidenceChunk], query_terms: list[str]) -> list[tuple[float, EvidenceChunk]]:
    tokenized = [tokenize(chunk.text) for chunk in chunks]
    doc_count = len(tokenized)
    document_frequency: dict[str, int] = {}
    for terms in tokenized:
        for term in set(terms):
            document_frequency[term] = document_frequency.get(term, 0) + 1
    avg_len = sum(len(terms) for terms in tokenized) / max(doc_count, 1)
    query_set = set(query_terms)
    scored = []
    for chunk, terms in zip(chunks, tokenized):
        term_counts = {term: terms.count(term) for term in set(terms)}
        score = 0.0
        for term in query_set:
            frequency = term_counts.get(term, 0)
            if frequency == 0:
                continue
            idf = math.log(1 + (doc_count - document_frequency.get(term, 0) + 0.5) / (document_frequency.get(term, 0) + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * len(terms) / max(avg_len, 1))
            score += idf * (frequency * 2.2 / denominator)
        scored.append((score, chunk))
    return scored


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def require_str(row: dict[str, Any], field_name: str, context: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value:
        raise EvidenceStoreValidationError(f"{context}: missing required string field {field_name}")
    return value
