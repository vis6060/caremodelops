import csv
import json
from pathlib import Path
from collections import Counter


RAW_DIR = Path("data/public_synthetic/raw_fhir")
CASES_DIR = Path("data/public_synthetic/cases")
OUT_CSV = Path("results/public_eval/synthea_case_candidate_ranking.csv")


RESOURCE_TYPES_WITH_TIME = {
    "Encounter": ["period"],
    "Observation": ["effectiveDateTime", "issued"],
    "Procedure": ["performedDateTime"],
    "DiagnosticReport": ["effectiveDateTime", "issued"],
    "MedicationRequest": ["authoredOn"],
    "MedicationAdministration": ["effectiveDateTime"],
    "CarePlan": ["period"],
    "Condition": ["recordedDate", "onsetDateTime"],
}


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def iter_resources(bundle: dict):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if isinstance(resource, dict):
            yield resource


def get_patient_id(bundle: dict) -> str:
    for r in iter_resources(bundle):
        if r.get("resourceType") == "Patient":
            return r.get("id", "")
    return ""


def extract_times(resource: dict) -> list[str]:
    times = []
    resource_type = resource.get("resourceType")

    for field in RESOURCE_TYPES_WITH_TIME.get(resource_type, []):
        value = resource.get(field)

        if isinstance(value, str):
            times.append(value)

        if isinstance(value, dict):
            for key in ("start", "end"):
                if value.get(key):
                    times.append(value[key])

    return times


def existing_patient_ids() -> set[str]:
    used = set()

    if not CASES_DIR.exists():
        return used

    for case_dir in CASES_DIR.iterdir():
        patients_file = case_dir / "patients.jsonl"
        if not patients_file.exists():
            continue

        with patients_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                patient_id = row.get("patient_id")
                if patient_id:
                    used.add(patient_id)

                metadata = row.get("metadata") or {}
                for key in ("synthea_patient_id", "source_patient_id", "raw_patient_id"):
                    if metadata.get(key):
                        used.add(metadata[key])

    return used


def score_bundle(path: Path, used_ids: set[str]) -> dict:
    try:
        bundle = read_json(path)
    except Exception as exc:
        return {
            "filename": path.name,
            "file_size_mb": round(path.stat().st_size / 1_000_000, 2),
            "patient_id": "",
            "resource_type": "",
            "parse_ok": False,
            "already_used": False,
            "complexity_score": 0,
            "skip_reason": f"parse_error: {exc}",
        }

    resource_type = bundle.get("resourceType", "")
    resources = list(iter_resources(bundle))
    counts = Counter(r.get("resourceType", "Unknown") for r in resources)
    patient_id = get_patient_id(bundle)

    distinct_times = set()
    for r in resources:
        distinct_times.update(extract_times(r))

    already_used = patient_id in used_ids

    score = (
        counts["Encounter"] * 8
        + counts["Condition"] * 5
        + counts["Observation"] * 1
        + counts["MedicationRequest"] * 6
        + counts["MedicationAdministration"] * 6
        + counts["Procedure"] * 5
        + counts["DiagnosticReport"] * 7
        + counts["CarePlan"] * 3
        + len(distinct_times) * 0.2
        + min(path.stat().st_size / 1_000_000, 100) * 0.05
    )

    skip_reasons = []
    if resource_type != "Bundle":
        skip_reasons.append("not_fhir_bundle")
    if not patient_id:
        skip_reasons.append("missing_patient")
    if counts["Encounter"] == 0:
        skip_reasons.append("no_encounters")
    if already_used:
        skip_reasons.append("already_used")

    return {
        "filename": path.name,
        "file_size_mb": round(path.stat().st_size / 1_000_000, 2),
        "patient_id": patient_id,
        "resource_type": resource_type,
        "parse_ok": True,
        "already_used": already_used,
        "total_resources": len(resources),
        "Patient": counts["Patient"],
        "Encounter": counts["Encounter"],
        "Condition": counts["Condition"],
        "Observation": counts["Observation"],
        "MedicationRequest": counts["MedicationRequest"],
        "MedicationAdministration": counts["MedicationAdministration"],
        "Procedure": counts["Procedure"],
        "DiagnosticReport": counts["DiagnosticReport"],
        "CarePlan": counts["CarePlan"],
        "distinct_event_timestamps": len(distinct_times),
        "complexity_score": round(score, 2),
        "skip_reason": ";".join(skip_reasons),
    }


def main() -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    used_ids = existing_patient_ids()
    files = sorted(RAW_DIR.glob("*.json"))

    rows = [score_bundle(path, used_ids) for path in files]
    rows.sort(key=lambda r: r.get("complexity_score", 0), reverse=True)

    fieldnames = [
        "filename",
        "file_size_mb",
        "patient_id",
        "resource_type",
        "parse_ok",
        "already_used",
        "total_resources",
        "Patient",
        "Encounter",
        "Condition",
        "Observation",
        "MedicationRequest",
        "MedicationAdministration",
        "Procedure",
        "DiagnosticReport",
        "CarePlan",
        "distinct_event_timestamps",
        "complexity_score",
        "skip_reason",
    ]

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})

    unused = [
        r for r in rows
        if r.get("parse_ok")
        and not r.get("already_used")
        and r.get("resource_type") == "Bundle"
        and r.get("Patient", 0) >= 1
        and r.get("Encounter", 0) >= 1
    ]

    print(f"Scanned files: {len(files)}")
    print(f"Existing used patient IDs detected: {len(used_ids)}")
    print(f"Unused eligible bundles: {len(unused)}")
    print(f"Saved ranking CSV: {OUT_CSV}")
    print()
    print("Top 20 unused candidates:")
    for i, row in enumerate(unused[:20], start=1):
        print(
            f"{i:02d}. score={row['complexity_score']} "
            f"file={row['filename']} "
            f"patient={row['patient_id']} "
            f"resources={row.get('total_resources', '')} "
            f"enc={row.get('Encounter', 0)} "
            f"cond={row.get('Condition', 0)} "
            f"obs={row.get('Observation', 0)} "
            f"medreq={row.get('MedicationRequest', 0)} "
            f"medadmin={row.get('MedicationAdministration', 0)} "
            f"proc={row.get('Procedure', 0)} "
            f"dx={row.get('DiagnosticReport', 0)}"
        )


if __name__ == "__main__":
    main()