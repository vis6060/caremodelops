"""Deterministic clinical tools over the ChartGround canonical schema."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from chartground.evidence_store import DEFAULT_CASES_ROOT, EvidenceStore, read_jsonl


class ClinicalTools:
    """Source-neutral deterministic tools with internal patient isolation."""

    def __init__(self, evidence_store: EvidenceStore | None = None, cases_root: Path | str = DEFAULT_CASES_ROOT) -> None:
        self.store = evidence_store or EvidenceStore(cases_root)
        self.cases_root = Path(cases_root)
        self._case_rows: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._load_case_rows()

    def build_patient_timeline(self, patient_id: str) -> list[dict[str, Any]]:
        rows = []
        for event in self._patient_rows(patient_id, "events"):
            rows.append(
                {
                    "event_id": event.get("event_id"),
                    "evidence_id": first(event.get("evidence_ids") or []),
                    "patient_id": patient_id,
                    "encounter_id": event.get("encounter_id"),
                    "event_time": event.get("event_time") or event.get("date"),
                    "event_type": event.get("event_type"),
                    "display": event.get("display") or event.get("label"),
                    "value": event.get("value"),
                    "unit": event.get("unit") or parse_unit(event.get("value")),
                    "source_ids": event.get("source_ids") or [],
                }
            )
        for encounter in self._patient_rows(patient_id, "encounters"):
            rows.append(
                {
                    "event_id": encounter.get("encounter_id"),
                    "evidence_id": None,
                    "patient_id": patient_id,
                    "encounter_id": encounter.get("encounter_id"),
                    "event_time": encounter.get("start") or encounter.get("end"),
                    "event_type": "encounter",
                    "display": encounter.get("type") or encounter.get("class") or "Encounter",
                    "value": encounter.get("status"),
                    "unit": None,
                    "source_ids": [encounter.get("source_id")] if encounter.get("source_id") else [],
                }
            )
        for record in self.store.get_patient_evidence(patient_id):
            if record.evidence_kind != "clinical_evidence" or record.source_type.startswith("note:"):
                continue
            rows.append(
                {
                    "event_id": None,
                    "evidence_id": record.evidence_id,
                    "patient_id": patient_id,
                    "encounter_id": record.encounter_id,
                    "event_time": record.event_time or record.source_time,
                    "event_type": record.source_type,
                    "display": record.text,
                    "value": None,
                    "unit": None,
                    "source_ids": list(record.source_ids),
                }
            )
        return sorted(rows, key=timeline_sort_key)

    def get_lab_trend(self, patient_id: str, lab_name: str) -> dict[str, Any]:
        observations = []
        errors = []
        for row in self._patient_rows(patient_id, "events"):
            if row.get("event_type") not in {"laboratory", "observation", "vital_sign"}:
                continue
            display = str(row.get("display") or row.get("label") or "")
            if lab_name.lower() not in {"lab", "laboratory"} and lab_name.lower() not in display.lower():
                continue
            numeric = parse_numeric(row.get("value"))
            observation = {
                "date": row.get("event_time") or row.get("date"),
                "display": display,
                "value": row.get("value"),
                "unit": row.get("unit") or parse_unit(row.get("value")),
                "numeric_value": numeric,
                "evidence_ids": row.get("evidence_ids") or [],
                "source_ids": row.get("source_ids") or [],
            }
            if numeric is None:
                errors.append({"display": row.get("label"), "value": row.get("value"), "error": "non_numeric_value"})
            observations.append(observation)

        numeric_observations = [item for item in observations if item["numeric_value"] is not None]
        if lab_name.lower() in {"lab", "laboratory"} and numeric_observations:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in observations:
                grouped.setdefault(str(item.get("display") or "").lower(), []).append(item)
            observations = next(
                (rows for rows in grouped.values() if sum(1 for item in rows if item["numeric_value"] is not None) >= 2),
                list(grouped.values())[0],
            )
            numeric_observations = [item for item in observations if item["numeric_value"] is not None]
        base = {
            "patient_id": patient_id,
            "lab_name": lab_name,
            "found": bool(observations),
            "matching_lab_display_names": sorted({str(item["display"]) for item in observations if item.get("display")}),
            "observations": observations,
            "errors": errors,
        }
        if len(numeric_observations) < 2:
            return {**base, "direction": "insufficient_data", "first": None, "last": None, "min": None, "max": None}
        ordered = sorted(numeric_observations, key=lambda item: (item.get("date") is None, item.get("date") or ""))
        first_obs = ordered[0]
        last_obs = ordered[-1]
        min_obs = min(ordered, key=lambda item: item["numeric_value"])
        max_obs = max(ordered, key=lambda item: item["numeric_value"])
        if last_obs["numeric_value"] > first_obs["numeric_value"]:
            direction = "increased"
        elif last_obs["numeric_value"] < first_obs["numeric_value"]:
            direction = "decreased"
        else:
            direction = "unchanged"
        return {**base, "direction": direction, "first": summarize_lab_obs(first_obs), "last": summarize_lab_obs(last_obs), "min": summarize_lab_obs(min_obs), "max": summarize_lab_obs(max_obs)}

    def get_medication_changes(self, patient_id: str) -> dict[str, Any]:
        result = {
            "patient_id": patient_id,
            "medications_started": [],
            "medications_stopped": [],
            "medications_continued": [],
            "medications_uncertain": [],
            "potential_conflicts": [],
        }
        medication_items = []
        for row in self._patient_rows(patient_id, "events"):
            if not str(row.get("event_type") or "").startswith("medication"):
                continue
            medication_items.append({"name": row.get("display") or row.get("label") or "Unknown medication", "value": row.get("value"), "evidence_ids": row.get("evidence_ids") or [], "source_ids": row.get("source_ids") or []})
        for record in self.store.get_patient_evidence(patient_id):
            if record.evidence_kind == "clinical_evidence" and "medication" in record.source_type.lower():
                if record.source_type.startswith("note:"):
                    parent_id = record.metadata.get("parent_evidence_id")
                    if not parent_id or "medication" not in self.store.get_evidence_by_id(parent_id).source_type.lower():
                        continue
                medication_items.append({"name": record.text, "value": None, "evidence_ids": [record.metadata.get("parent_evidence_id") or record.evidence_id], "source_ids": list(record.source_ids)})
        for item in medication_items:
            status = medication_status(item["value"] or item["name"])
            bucket = {
                "started": "medications_started",
                "stopped": "medications_stopped",
                "continued": "medications_continued",
                "uncertain": "medications_uncertain",
            }[status]
            result[bucket].append(item)
        seen_statuses: dict[str, set[str]] = {}
        for bucket, status in (("medications_started", "started"), ("medications_stopped", "stopped"), ("medications_continued", "continued")):
            for item in result[bucket]:
                seen_statuses.setdefault(str(item["name"]).lower(), set()).add(status)
        for name, statuses in seen_statuses.items():
            if "stopped" in statuses and ("started" in statuses or "continued" in statuses):
                result["potential_conflicts"].append({"medication": name, "statuses": sorted(statuses), "severity": "medium"})
        if not medication_items:
            result["medications_uncertain"].append({"name": "No medication evidence found", "evidence_ids": [], "source_ids": []})
        return result

    def compare_radiology_reports(self, patient_id: str) -> dict[str, Any]:
        reports = []
        for record in self.store.get_patient_evidence(patient_id):
            if record.evidence_kind == "clinical_evidence" and is_radiology_record(record.source_type, record.text):
                evidence_id = record.metadata.get("parent_evidence_id") or record.evidence_id
                reports.append(
                    {
                        "evidence_id": evidence_id,
                        "source_time": record.source_time,
                        "source_type": record.source_type,
                        "snippet": record.text,
                        "source_ids": list(record.source_ids),
                    }
                )
        reports = merge_radiology_reports(reports)
        result = {"patient_id": patient_id, "report_count": len(reports), "reports": reports, "supporting_evidence_ids": unique([item["evidence_id"] for item in reports])}
        if len(reports) < 2:
            return {**result, "earliest_report": first(reports), "latest_report": first(reports), "new_or_changed_findings": [], "insufficient_data": True}
        changes = deterministic_radiology_changes(reports[0]["snippet"], reports[-1]["snippet"])
        return {**result, "earliest_report": reports[0], "latest_report": reports[-1], "new_or_changed_findings": changes, "insufficient_data": False}

    def search_clinical_notes(self, patient_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        results = self.store.search_patient_evidence(patient_id, query, top_k=max(top_k * 3, top_k), evidence_kinds=("clinical_evidence",))
        note_results = [item for item in results if item.source_type.startswith("note:")]
        selected = (note_results or results)[:top_k]
        return [
            {
                "evidence_id": item.evidence_id,
                "patient_id": item.patient_id,
                "source_type": item.source_type,
                "source_time": item.source_time,
                "snippet": item.text,
                "score": item.score,
                "source_ids": list(item.source_ids),
            }
            for item in selected
        ]

    def detect_record_conflicts(self, patient_id: str) -> dict[str, Any]:
        conflicts = []
        conflicts.extend(self._detect_cross_patient_conflicts(patient_id))
        conflicts.extend(self._detect_explicit_conflicts(patient_id))
        medication_changes = self.get_medication_changes(patient_id)
        for item in medication_changes["potential_conflicts"]:
            conflicts.append(
                {
                    "conflict_type": "medication_status_conflict",
                    "description": f"Medication {item['medication']} has conflicting deterministic statuses.",
                    "severity": item["severity"],
                    "supporting_evidence_ids": [],
                    "source_ids": [],
                    "recommended_action": "uncertain",
                }
            )
        conflicts.extend(self._detect_duplicate_lab_conflicts(patient_id))
        conflicts.extend(self._detect_radiology_language_conflicts(patient_id))
        conflicts.extend(self._detect_timestamp_conflicts(patient_id))
        return {"patient_id": patient_id, "conflicts": conflicts}

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        return ClinicalToolRegistry(self).call(name, **kwargs)

    def _load_case_rows(self) -> None:
        for case_id in self.store.list_cases():
            case_dir = Path(self.store.get_case(case_id)["case_dir"])
            self._case_rows[case_id] = {
                "events": read_jsonl(case_dir / "events.jsonl"),
                "encounters": read_jsonl(case_dir / "encounters.jsonl"),
                "notes": read_jsonl(case_dir / "notes.jsonl"),
                "evidence": read_jsonl(case_dir / "evidence.jsonl"),
            }

    def _patient_rows(self, patient_id: str, row_type: str) -> list[dict[str, Any]]:
        rows = []
        for case_id in self.store.list_cases():
            for row in self._case_rows[case_id][row_type]:
                if row.get("patient_id") == patient_id:
                    rows.append(row)
        return rows

    def _detect_cross_patient_conflicts(self, patient_id: str) -> list[dict[str, Any]]:
        conflicts = []
        for record in self.store.get_patient_evidence(patient_id):
            if record.patient_id != patient_id:
                conflicts.append(
                    {
                        "conflict_type": "cross_patient_evidence",
                        "description": f"Evidence {record.evidence_id} is attached to the wrong patient.",
                        "severity": "high",
                        "supporting_evidence_ids": [record.evidence_id],
                        "source_ids": list(record.source_ids),
                        "recommended_action": "escalate",
                    }
                )
        return conflicts

    def _detect_duplicate_lab_conflicts(self, patient_id: str) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
        for row in self._patient_rows(patient_id, "events"):
            if row.get("event_type") in {"laboratory", "observation", "vital_sign"}:
                grouped.setdefault((str(row.get("display") or row.get("label") or "").lower(), row.get("event_time") or row.get("date")), []).append(row)
        conflicts = []
        for (label, date), rows in grouped.items():
            values = {str(row.get("value")) for row in rows}
            if len(rows) > 1 and len(values) > 1:
                conflicts.append(
                    {
                        "conflict_type": "duplicate_lab_value_conflict",
                        "description": f"Duplicate same-time lab records for {label} on {date} have different values.",
                        "severity": "medium",
                        "supporting_evidence_ids": unique([eid for row in rows for eid in row.get("evidence_ids", [])]),
                        "source_ids": unique([sid for row in rows for sid in row.get("source_ids", [])]),
                        "recommended_action": "uncertain",
                    }
                )
        return conflicts

    def _detect_explicit_conflicts(self, patient_id: str) -> list[dict[str, Any]]:
        conflicts = []
        for row in self._patient_rows(patient_id, "events"):
            if "conflict" not in str(row.get("event_type") or "").lower():
                continue
            conflicts.append(
                {
                    "conflict_type": row.get("event_type"),
                    "description": str(row.get("value") or row.get("display") or row.get("label") or "Explicit chart conflict."),
                    "severity": "high",
                    "supporting_evidence_ids": row.get("evidence_ids") or [],
                    "source_ids": row.get("source_ids") or [],
                    "recommended_action": "escalate",
                }
            )
        return conflicts

    def _detect_radiology_language_conflicts(self, patient_id: str) -> list[dict[str, Any]]:
        comparison = self.compare_radiology_reports(patient_id)
        reports = comparison["reports"]
        if len(reports) < 2:
            return []
        earliest = reports[0]["snippet"].lower()
        latest = reports[-1]["snippet"].lower()
        if no_acute_language(earliest) and positive_radiology_language(latest):
            return [
                {
                    "conflict_type": "radiology_impression_language_change",
                    "description": "Earlier radiology language is negative while later language suggests a positive finding.",
                    "severity": "medium",
                    "supporting_evidence_ids": comparison["supporting_evidence_ids"],
                    "source_ids": unique([sid for report in reports for sid in report.get("source_ids", [])]),
                    "recommended_action": "uncertain",
                }
            ]
        return []

    def _detect_timestamp_conflicts(self, patient_id: str) -> list[dict[str, Any]]:
        encounter_end = {row.get("encounter_id"): row.get("end") for row in self._patient_rows(patient_id, "encounters") if row.get("end")}
        conflicts = []
        for row in self._patient_rows(patient_id, "events"):
            encounter_id = row.get("encounter_id")
            if encounter_id in encounter_end and row.get("date") and row["date"] > encounter_end[encounter_id]:
                conflicts.append(
                    {
                        "conflict_type": "event_after_discharge",
                        "description": f"Event {row.get('event_id')} is timestamped after encounter discharge.",
                        "severity": "medium",
                        "supporting_evidence_ids": row.get("evidence_ids") or [],
                        "source_ids": row.get("source_ids") or [],
                        "recommended_action": "escalate",
                    }
                )
        return conflicts


class ClinicalToolRegistry:
    """Simple JSON-serializable tool registry for later agents."""

    def __init__(self, tools: ClinicalTools) -> None:
        self.tools = tools
        self._registry: dict[str, Callable[..., Any]] = {
            "build_patient_timeline": tools.build_patient_timeline,
            "get_lab_trend": tools.get_lab_trend,
            "get_medication_changes": tools.get_medication_changes,
            "compare_radiology_reports": tools.compare_radiology_reports,
            "search_clinical_notes": tools.search_clinical_notes,
            "detect_record_conflicts": tools.detect_record_conflicts,
        }

    def list_tools(self) -> list[str]:
        return sorted(self._registry)

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in self._registry:
            raise KeyError(f"Unknown clinical tool: {name}")
        result = self._registry[name](**kwargs)
        json.dumps(result)
        return result


def timeline_sort_key(row: dict[str, Any]) -> tuple[bool, str, str]:
    timestamp = row.get("event_time")
    return (timestamp is None, timestamp or "", str(row.get("event_id") or row.get("evidence_id") or ""))


def parse_numeric(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def parse_unit(value: Any) -> str | None:
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?\s*(.*)", str(value))
    unit = match.group(1).strip() if match else ""
    return unit or None


def summarize_lab_obs(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": observation.get("date"),
        "value": observation.get("numeric_value"),
        "unit": observation.get("unit"),
        "display": observation.get("display"),
        "evidence_ids": observation.get("evidence_ids") or [],
    }


def medication_status(text: Any) -> str:
    lowered = str(text or "").lower()
    if any(term in lowered for term in ("stop", "stopped", "discontinue", "discontinued")):
        return "stopped"
    if any(term in lowered for term in ("continue", "continued", "active", "current")):
        return "continued"
    if any(term in lowered for term in ("start", "started", "new")):
        return "started"
    return "uncertain"


def deterministic_radiology_changes(earliest: str, latest: str) -> list[str]:
    if earliest == latest:
        return []
    if no_acute_language(earliest) and positive_radiology_language(latest):
        return ["negative_to_positive_language"]
    return []


def no_acute_language(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ("no acute", "no focal", "no evidence of", "negative"))


def positive_radiology_language(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in ("opacity", "infiltrate", "effusion", "fracture", "mass", "pneumothorax")) and not no_acute_language(lowered)


def is_radiology_record(source_type: str, text: str) -> bool:
    source_lower = source_type.lower()
    if "diagnosticreport" in source_lower or "overlaydiagnosticreport" in source_lower or source_lower.startswith("note:radiology"):
        return True
    if source_lower in {"procedure", "condition"}:
        return False
    haystack = f"{source_type} {text}".lower()
    if any(term in haystack for term in ("radiology", "radiograph", "imaging", "x-ray", "xray", "ultrasound", "mammography")):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return bool(tokens & {"ct", "mri"})


def dedupe_dicts(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for row in rows:
        marker = tuple(row.get(key) for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(row)
    return result


def merge_radiology_reports(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        evidence_id = row["evidence_id"]
        if evidence_id not in by_evidence:
            by_evidence[evidence_id] = {**row, "snippets": [row["snippet"]]}
            continue
        existing = by_evidence[evidence_id]
        if row["snippet"] not in existing["snippets"]:
            existing["snippets"].append(row["snippet"])
        existing["source_ids"] = unique([*existing.get("source_ids", []), *row.get("source_ids", [])])
        if existing.get("source_time") is None and row.get("source_time"):
            existing["source_time"] = row["source_time"]
    merged = []
    for row in by_evidence.values():
        snippets = row.pop("snippets")
        row["snippet"] = " ".join(snippets)
        merged.append(row)
    return sorted(merged, key=lambda item: (item.get("source_time") is None, item.get("source_time") or "", item.get("evidence_id") or ""))


def unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def first(values: list[Any]) -> Any:
    return values[0] if values else None
