"""Private MIMIC-IV to ChartGround canonical mapping helpers."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import date, datetime
from decimal import Decimal

PRIVATE_SOURCE = "mimic_iv_private"
PUBLIC_SAFE = False
NOTE_CHUNK_CHARS = 1300
NOTE_CHUNK_OVERLAP = 150


@dataclass(frozen=True)
class CaseContext:
    case_id: str
    patient_id: str
    encounter_id: str


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def text_value(value: Any) -> str:
    value = clean_value(value)
    return "" if value is None else str(value)


def stable_id(prefix: str, *parts: Any) -> str:
    raw = ":".join(text_value(part) for part in parts if text_value(part))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").lower()
    return f"{prefix}-{slug[:120]}"


def metadata(**values: Any) -> dict[str, Any]:
    result = {"source": PRIVATE_SOURCE, "public_safe": PUBLIC_SAFE}
    for key, value in values.items():
        value = clean_value(value)
        if value is not None and value != "":
            result[key] = value
    return result


def patient_row(case_id: str, patient: dict[str, Any]) -> dict[str, Any]:
    subject_id = text_value(patient.get("subject_id"))
    return {
        "case_id": case_id,
        "patient_id": subject_id,
        "age": clean_value(patient.get("anchor_age")),
        "sex": clean_value(patient.get("gender")),
        "anchor_year_group": clean_value(patient.get("anchor_year_group")),
        "source_id": f"mimic:patients/{subject_id}",
        "metadata": metadata(source_table="patients"),
    }


def encounter_row(ctx: CaseContext, admission: dict[str, Any], icu_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_id": ctx.case_id,
        "patient_id": ctx.patient_id,
        "encounter_id": ctx.encounter_id,
        "source_id": f"mimic:admissions/{ctx.hadm_id if hasattr(ctx, 'hadm_id') else ctx.encounter_id}",
        "admit_time": clean_value(admission.get("admittime")),
        "discharge_time": clean_value(admission.get("dischtime")),
        "admission_type": clean_value(admission.get("admission_type")),
        "admission_location": clean_value(admission.get("admission_location")),
        "discharge_location": clean_value(admission.get("discharge_location")),
        "insurance": clean_value(admission.get("insurance")),
        "language": clean_value(admission.get("language")),
        "marital_status": clean_value(admission.get("marital_status")),
        "race": clean_value(admission.get("race")),
        "edregtime": clean_value(admission.get("edregtime")),
        "edouttime": clean_value(admission.get("edouttime")),
        "icu_stays": [
            {
                "stay_id": clean_value(row.get("stay_id")),
                "first_careunit": clean_value(row.get("first_careunit")),
                "last_careunit": clean_value(row.get("last_careunit")),
                "intime": clean_value(row.get("intime")),
                "outtime": clean_value(row.get("outtime")),
                "los": clean_value(row.get("los")),
            }
            for row in icu_rows
        ],
        "metadata": metadata(source_table="admissions"),
    }


def diagnosis_event(ctx: CaseContext, row: dict[str, Any], admit_time: Any) -> dict[str, Any]:
    source_id = f"mimic:diagnoses_icd/{ctx.encounter_id}/{text_value(row.get('seq_num'))}/{text_value(row.get('icd_code'))}"
    return base_event(
        ctx,
        source_id,
        "condition",
        clean_value(row.get("long_title")) or f"ICD diagnosis {row.get('icd_code')}",
        admit_time,
        code=clean_value(row.get("icd_code")),
        code_system=clean_value(row.get("icd_version")),
        source_table="diagnoses_icd",
    )


def lab_event(ctx: CaseContext, row: dict[str, Any]) -> dict[str, Any]:
    source_id = f"mimic:labevents/{text_value(row.get('labevent_id'))}"
    return base_event(
        ctx,
        source_id,
        "laboratory",
        clean_value(row.get("label")) or f"Lab item {row.get('itemid')}",
        clean_value(row.get("charttime")),
        value=clean_value(row.get("valuenum")) if clean_value(row.get("valuenum")) is not None else clean_value(row.get("value")),
        unit=clean_value(row.get("valueuom")),
        code=clean_value(row.get("itemid")),
        status=clean_value(row.get("flag")),
        source_table="labevents",
        extra_metadata={"flag": clean_value(row.get("flag")), "priority": clean_value(row.get("priority")), "fluid": clean_value(row.get("fluid"))},
    )


def prescription_event(ctx: CaseContext, row: dict[str, Any]) -> dict[str, Any]:
    source_id = (
        f"mimic:prescriptions/{ctx.encounter_id}/{text_value(row.get('cg_row_id'))}/"
        f"{text_value(row.get('pharmacy_id'))}/{text_value(row.get('poe_id'))}"
    )
    value = " ".join(
        part
        for part in (
            text_value(row.get("dose_val_rx")),
            text_value(row.get("dose_unit_rx")),
            text_value(row.get("route")),
            text_value(row.get("doses_per_24_hrs")),
        )
        if part
    )
    return base_event(
        ctx,
        source_id,
        "medication_order",
        clean_value(row.get("drug")) or "Medication order",
        clean_value(row.get("starttime")) or clean_value(row.get("stoptime")),
        value=value or None,
        code=clean_value(row.get("formulary_drug_cd")),
        source_table="prescriptions",
        extra_metadata={
            "starttime": clean_value(row.get("starttime")),
            "stoptime": clean_value(row.get("stoptime")),
            "drug_type": clean_value(row.get("drug_type")),
            "frequency": clean_value(row.get("doses_per_24_hrs")),
            "route": clean_value(row.get("route")),
        },
    )


def procedure_event(ctx: CaseContext, row: dict[str, Any], admit_time: Any) -> dict[str, Any]:
    source_id = f"mimic:procedures_icd/{ctx.encounter_id}/{text_value(row.get('seq_num'))}/{text_value(row.get('icd_code'))}"
    return base_event(
        ctx,
        source_id,
        "procedure",
        clean_value(row.get("long_title")) or f"ICD procedure {row.get('icd_code')}",
        clean_value(row.get("chartdate")) or admit_time,
        code=clean_value(row.get("icd_code")),
        code_system=clean_value(row.get("icd_version")),
        source_table="procedures_icd",
    )


def icu_event(ctx: CaseContext, row: dict[str, Any]) -> dict[str, Any]:
    source_id = f"mimic:icustays/{text_value(row.get('stay_id'))}"
    return base_event(
        ctx,
        source_id,
        "icu_stay",
        "ICU stay",
        clean_value(row.get("intime")),
        value=clean_value(row.get("los")),
        unit="days" if clean_value(row.get("los")) is not None else None,
        source_table="icustays",
        extra_metadata={
            "stay_id": clean_value(row.get("stay_id")),
            "first_careunit": clean_value(row.get("first_careunit")),
            "last_careunit": clean_value(row.get("last_careunit")),
            "outtime": clean_value(row.get("outtime")),
        },
    )


def base_event(
    ctx: CaseContext,
    source_id: str,
    event_type: str,
    display: Any,
    event_time: Any,
    value: Any = None,
    unit: Any = None,
    code: Any = None,
    code_system: Any = None,
    status: Any = None,
    source_table: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_id = stable_id("ev", source_id)
    return {
        "case_id": ctx.case_id,
        "patient_id": ctx.patient_id,
        "encounter_id": ctx.encounter_id,
        "event_id": stable_id("evt", source_id),
        "event_type": event_type,
        "event_time": clean_value(event_time),
        "date": clean_value(event_time),
        "display": clean_value(display),
        "label": clean_value(display),
        "value": clean_value(value),
        "unit": clean_value(unit),
        "code": clean_value(code),
        "code_system": clean_value(code_system),
        "status": clean_value(status),
        "source_resource_id": source_id,
        "source_table": source_table,
        "evidence_ids": [evidence_id],
        "source_ids": [source_id],
        "metadata": metadata(source_table=source_table, **(extra_metadata or {})),
    }


def evidence_from_event(event: dict[str, Any]) -> dict[str, Any]:
    text = ". ".join(
        part
        for part in (
            text_value(event.get("display")),
            text_value(event.get("value")),
            text_value(event.get("unit")),
            text_value(event.get("code")),
        )
        if part
    )
    return {
        "case_id": event["case_id"],
        "patient_id": event["patient_id"],
        "encounter_id": event.get("encounter_id"),
        "evidence_id": event["evidence_ids"][0],
        "source_id": event["source_ids"][0],
        "source_ids": event.get("source_ids", []),
        "source_kind": PRIVATE_SOURCE,
        "resource_type": event.get("event_type"),
        "source_type": event.get("event_type"),
        "source_table": event.get("source_table"),
        "date": event.get("event_time"),
        "source_time": event.get("event_time"),
        "title": event.get("display"),
        "label": event.get("display"),
        "value": text,
        "text": text,
        "code": event.get("code"),
        "metadata": event.get("metadata", {}),
    }


def note_row(ctx: CaseContext, row: dict[str, Any], note_type: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    note_id = text_value(row.get("note_id"))
    return {
        "case_id": ctx.case_id,
        "patient_id": ctx.patient_id,
        "encounter_id": ctx.encounter_id,
        "note_id": note_id,
        "note_type": note_type,
        "created_at": clean_value(row.get("charttime")) or clean_value(row.get("storetime")),
        "charttime": clean_value(row.get("charttime")),
        "storetime": clean_value(row.get("storetime")),
        "text": f"{note_type} note with {len(chunks)} private evidence chunk(s).",
        "sentences": [
            {
                "sentence_id": chunk["chunk_id"],
                "text": f"{note_type} private note chunk {index}.",
            }
            for index, chunk in enumerate(chunks, start=1)
        ],
        "metadata": metadata(source_table=f"note_{note_type}", note_id=note_id),
    }


def note_evidence_and_provenance(
    ctx: CaseContext,
    row: dict[str, Any],
    note_type: str,
    max_chunk_chars: int = NOTE_CHUNK_CHARS,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    note_id = text_value(row.get("note_id"))
    source_table = "discharge" if note_type == "discharge" else "radiology"
    source_id = f"mimic:{source_table}/{note_id}"
    chunks = chunk_text(text_value(row.get("text")), max_chunk_chars=max_chunk_chars)
    evidence_rows: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    chunk_refs: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_id = f"{note_id}-chunk-{index:03d}"
        evidence_id = stable_id("ev", source_id, chunk_id)
        chunk_refs.append({"chunk_id": chunk_id, "evidence_id": evidence_id})
        evidence_rows.append(
            {
                "case_id": ctx.case_id,
                "patient_id": ctx.patient_id,
                "encounter_id": ctx.encounter_id,
                "evidence_id": evidence_id,
                "source_id": f"{source_id}/{chunk_id}",
                "source_ids": [f"{source_id}/{chunk_id}"],
                "source_kind": PRIVATE_SOURCE,
                "resource_type": f"note_{note_type}",
                "source_type": f"note:{note_type}",
                "source_table": source_table,
                "date": clean_value(row.get("charttime")) or clean_value(row.get("storetime")),
                "source_time": clean_value(row.get("charttime")) or clean_value(row.get("storetime")),
                "title": f"{note_type} note chunk {index}",
                "label": f"{note_type} note chunk {index}",
                "value": chunk,
                "text": chunk,
                "code": None,
                "metadata": metadata(source_table=source_table, note_id=note_id, chunk_id=chunk_id),
            }
        )
        provenance_rows.append(
            {
                "case_id": ctx.case_id,
                "patient_id": ctx.patient_id,
                "provenance_id": stable_id("prov", source_id, chunk_id),
                "note_id": note_id,
                "sentence_id": chunk_id,
                "chunk_id": chunk_id,
                "evidence_id": evidence_id,
                "source_id": f"{source_id}/{chunk_id}",
                "source_table": source_table,
                "supporting_source_ids": [f"{source_id}/{chunk_id}"],
                "public_safe": PUBLIC_SAFE,
                "metadata": metadata(source_table=source_table, note_id=note_id),
            }
        )
    note = note_row(ctx, row, note_type, chunk_refs)
    return note, evidence_rows, provenance_rows


def chunk_text(text: str, max_chunk_chars: int = NOTE_CHUNK_CHARS, overlap: int = NOTE_CHUNK_OVERLAP) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chunk_chars)
        if end < len(text):
            boundary = text.rfind(". ", start, end)
            if boundary > start + max_chunk_chars // 2:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


#def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
#    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8") 
try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


def to_json_safe(value: Any) -> Any:
    """Convert Pandas/Numpy/Python objects into JSON-serializable values."""

    if value is None:
        return None

    # Pandas missing values: NaN, NaT, pd.NA
    if pd is not None:
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                return None
            return value.isoformat()

    # Python datetime/date
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    # Decimal
    if isinstance(value, Decimal):
        return float(value)

    # Numpy scalars
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)

        if isinstance(value, np.floating):
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                return None
            return number

        if isinstance(value, np.bool_):
            return bool(value)

        if isinstance(value, np.ndarray):
            return [to_json_safe(item) for item in value.tolist()]

    # Native float NaN/Inf
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    # Lists/tuples/sets
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]

    # Dicts
    if isinstance(value, dict):
        return {
            str(key): to_json_safe(item)
            for key, item in value.items()
        }

    return value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to JSONL after converting non-JSON-safe objects."""

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            safe_row = to_json_safe(row)
            file.write(
                json.dumps(
                    safe_row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )