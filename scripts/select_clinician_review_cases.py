import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


TARGET_BUCKETS = {
    "longitudinal_rich": 6,
    "lab_trend_candidate": 5,
    "medication_candidate": 5,
    "radiology_candidate": 4,
    "procedure_or_care_plan_candidate": 3,
    "missing_information_candidate": 3,
    "conflict_overlay_candidate": 2,
    "adversarial_candidate": 2,
}


TIME_FIELDS = {
    "Encounter": ["period"],
    "Observation": ["effectiveDateTime", "issued"],
    "Procedure": ["performedDateTime"],
    "DiagnosticReport": ["effectiveDateTime", "issued"],
    "MedicationRequest": ["authoredOn"],
    "MedicationAdministration": ["effectiveDateTime"],
    "CarePlan": ["period"],
    "Condition": ["recordedDate", "onsetDateTime"],
}


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def iter_resources(bundle: dict[str, Any]):
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if isinstance(resource, dict):
            yield resource


def get_patient_id(bundle: dict[str, Any]) -> str:
    for resource in iter_resources(bundle):
        if resource.get("resourceType") == "Patient":
            return resource.get("id", "")
    return ""


def get_reference_id(reference: str | None) -> str:
    if not reference:
        return ""
    return reference.split("/")[-1]


def extract_time_values(resource: dict[str, Any]) -> list[str]:
    resource_type = resource.get("resourceType")
    values: list[str] = []

    for field in TIME_FIELDS.get(resource_type, []):
        value = resource.get(field)

        if isinstance(value, str):
            values.append(value)

        if isinstance(value, dict):
            for key in ("start", "end"):
                if value.get(key):
                    values.append(value[key])

    return values


def is_numeric_observation(resource: dict[str, Any]) -> bool:
    if resource.get("resourceType") != "Observation":
        return False

    quantity = resource.get("valueQuantity")
    if not isinstance(quantity, dict):
        return False

    return isinstance(quantity.get("value"), (int, float))


def observation_code(resource: dict[str, Any]) -> str:
    code = resource.get("code", {})
    text = code.get("text")
    if text:
        return text.lower()

    codings = code.get("coding", [])
    if codings and isinstance(codings, list):
        display = codings[0].get("display")
        code_value = codings[0].get("code")
        return str(display or code_value or "").lower()

    return ""


def used_patient_ids_from_cases(cases_dir: Path) -> set[str]:
    used: set[str] = set()

    if not cases_dir.exists():
        return used

    for case_dir in cases_dir.iterdir():
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
                    used.add(str(patient_id))

                metadata = row.get("metadata") or {}
                for key in ("synthea_patient_id", "source_patient_id", "raw_patient_id"):
                    if metadata.get(key):
                        used.add(str(metadata[key]))

    return used


def used_patient_ids_from_raw(raw_dir: Path) -> set[str]:
    used: set[str] = set()

    if not raw_dir or not raw_dir.exists():
        return used

    for path in raw_dir.glob("*.json"):
        bundle = load_json(path)
        if not bundle:
            continue

        patient_id = get_patient_id(bundle)
        if patient_id:
            used.add(patient_id)

    return used


def score_bundle(path: Path, used_ids: set[str]) -> dict[str, Any]:
    bundle = load_json(path)

    if bundle is None:
        return {
            "filename": path.name,
            "path": str(path),
            "valid": False,
            "skip_reason": "invalid_json",
        }

    resource_type = bundle.get("resourceType", "")
    resources = list(iter_resources(bundle))
    counts = Counter(r.get("resourceType", "Unknown") for r in resources)
    patient_id = get_patient_id(bundle)

    timestamps: set[str] = set()
    numeric_observations = 0
    numeric_obs_timestamps: set[str] = set()
    observation_codes: set[str] = set()

    for resource in resources:
        for value in extract_time_values(resource):
            timestamps.add(value)

        if is_numeric_observation(resource):
            numeric_observations += 1
            observation_codes.add(observation_code(resource))

            for value in extract_time_values(resource):
                numeric_obs_timestamps.add(value)

    already_used = patient_id in used_ids

    medication_count = counts["MedicationRequest"] + counts["MedicationAdministration"]
    procedure_or_care_count = counts["Procedure"] + counts["CarePlan"]

    complexity_score = (
        counts["Encounter"] * 8
        + counts["Condition"] * 5
        + counts["Observation"] * 1
        + numeric_observations * 1.5
        + medication_count * 6
        + counts["Procedure"] * 5
        + counts["DiagnosticReport"] * 7
        + counts["CarePlan"] * 3
        + len(timestamps) * 0.25
        + min(path.stat().st_size / 1_000_000, 100) * 0.05
    )

    feature_tags: list[str] = []

    if counts["Encounter"] >= 2 and len(timestamps) >= 8:
        feature_tags.append("longitudinal_rich")

    if numeric_observations >= 5 and len(numeric_obs_timestamps) >= 2:
        feature_tags.append("lab_trend_candidate")

    if medication_count >= 1:
        feature_tags.append("medication_candidate")

    if counts["DiagnosticReport"] >= 1:
        feature_tags.append("radiology_candidate")

    if procedure_or_care_count >= 1:
        feature_tags.append("procedure_or_care_plan_candidate")

    if counts["Encounter"] >= 1 and (
        counts["Observation"] < 5
        or medication_count == 0
        or counts["DiagnosticReport"] == 0
    ):
        feature_tags.append("missing_information_candidate")

    if (
        "lab_trend_candidate" in feature_tags
        or "medication_candidate" in feature_tags
        or "radiology_candidate" in feature_tags
    ):
        feature_tags.append("conflict_overlay_candidate")

    if counts["Encounter"] >= 1 and len(resources) >= 20:
        feature_tags.append("adversarial_candidate")

    skip_reasons: list[str] = []
    if resource_type != "Bundle":
        skip_reasons.append("not_bundle")
    if not patient_id:
        skip_reasons.append("missing_patient")
    if counts["Encounter"] < 1:
        skip_reasons.append("no_encounter")
    if already_used:
        skip_reasons.append("already_used")

    valid = not skip_reasons

    return {
        "filename": path.name,
        "path": str(path),
        "file_size_mb": round(path.stat().st_size / 1_000_000, 2),
        "patient_id": patient_id,
        "resource_type": resource_type,
        "valid": valid,
        "already_used": already_used,
        "total_resources": len(resources),
        "Patient": counts["Patient"],
        "Encounter": counts["Encounter"],
        "Condition": counts["Condition"],
        "Observation": counts["Observation"],
        "numeric_observations": numeric_observations,
        "distinct_observation_codes": len([c for c in observation_codes if c]),
        "MedicationRequest": counts["MedicationRequest"],
        "MedicationAdministration": counts["MedicationAdministration"],
        "Procedure": counts["Procedure"],
        "DiagnosticReport": counts["DiagnosticReport"],
        "CarePlan": counts["CarePlan"],
        "distinct_event_timestamps": len(timestamps),
        "complexity_score": round(complexity_score, 2),
        "feature_tags": ";".join(feature_tags),
        "skip_reason": ";".join(skip_reasons),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "selected_rank",
        "assigned_bucket",
        "selection_reason",
        "filename",
        "path",
        "file_size_mb",
        "patient_id",
        "resource_type",
        "valid",
        "already_used",
        "total_resources",
        "Patient",
        "Encounter",
        "Condition",
        "Observation",
        "numeric_observations",
        "distinct_observation_codes",
        "MedicationRequest",
        "MedicationAdministration",
        "Procedure",
        "DiagnosticReport",
        "CarePlan",
        "distinct_event_timestamps",
        "complexity_score",
        "feature_tags",
        "skip_reason",
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def select_cases(candidates: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    valid_candidates = [
        c for c in candidates
        if c.get("valid") and not c.get("already_used")
    ]

    selected: list[dict[str, Any]] = []
    selected_patients: set[str] = set()

    def available_for_bucket(bucket: str) -> list[dict[str, Any]]:
        rows = []
        for c in valid_candidates:
            if c["patient_id"] in selected_patients:
                continue
            tags = set(str(c.get("feature_tags", "")).split(";"))
            if bucket in tags:
                rows.append(c)

        reverse = bucket != "missing_information_candidate"

        return sorted(
            rows,
            key=lambda x: float(x.get("complexity_score", 0)),
            reverse=reverse,
        )

    for bucket, target_count in TARGET_BUCKETS.items():
        bucket_rows = available_for_bucket(bucket)
        count = 0

        for row in bucket_rows:
            if len(selected) >= n or count >= target_count:
                break

            chosen = dict(row)
            chosen["assigned_bucket"] = bucket
            chosen["selection_reason"] = f"Selected for {bucket} coverage."
            selected.append(chosen)
            selected_patients.add(chosen["patient_id"])
            count += 1

    if len(selected) < n:
        remaining = [
            c for c in valid_candidates
            if c["patient_id"] not in selected_patients
        ]

        remaining = sorted(
            remaining,
            key=lambda x: float(x.get("complexity_score", 0)),
            reverse=True,
        )

        for row in remaining:
            if len(selected) >= n:
                break

            chosen = dict(row)
            chosen["assigned_bucket"] = "general_richness_fill"
            chosen["selection_reason"] = "Selected as high-complexity fill after stratified buckets."
            selected.append(chosen)
            selected_patients.add(chosen["patient_id"])

    for index, row in enumerate(selected, start=1):
        row["selected_rank"] = index

    return selected


def write_report(path: Path, selected: list[dict[str, Any]], all_candidates: list[dict[str, Any]]) -> None:
    bucket_counts = Counter(row.get("assigned_bucket", "unknown") for row in selected)

    lines = [
        "# Clinician Review Case Selection Report",
        "",
        f"Total scanned candidates: {len(all_candidates)}",
        f"Selected cases: {len(selected)}",
        "",
        "## Bucket counts",
        "",
    ]

    for bucket, count in sorted(bucket_counts.items()):
        lines.append(f"- {bucket}: {count}")

    lines.extend([
        "",
        "## Selected cases",
        "",
        "| Rank | Bucket | Filename | Patient ID | Score | Resources | Enc | Obs | MedReq | MedAdmin | Proc | DxReport | CarePlan |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for row in selected:
        lines.append(
            f"| {row.get('selected_rank')} "
            f"| {row.get('assigned_bucket')} "
            f"| {row.get('filename')} "
            f"| {row.get('patient_id')} "
            f"| {row.get('complexity_score')} "
            f"| {row.get('total_resources')} "
            f"| {row.get('Encounter')} "
            f"| {row.get('Observation')} "
            f"| {row.get('MedicationRequest')} "
            f"| {row.get('MedicationAdministration')} "
            f"| {row.get('Procedure')} "
            f"| {row.get('DiagnosticReport')} "
            f"| {row.get('CarePlan')} |"
        )

    lines.extend([
        "",
        "## Notes",
        "",
        "- Selection is stratified for coverage, not purely based on file size.",
        "- Existing generated cases and raw-FHIR cases already selected are excluded when provided.",
        "- This selection does not create ChartGround cases yet; it only selects candidate source files.",
    ])

    path.write_text("\n".join(lines), encoding="utf-8")


def copy_selected_files(selected: list[dict[str, Any]], copy_to: Path | None) -> None:
    if not copy_to:
        return

    copy_to.mkdir(parents=True, exist_ok=True)

    for row in selected:
        source = Path(row["path"])
        destination = copy_to / source.name
        shutil.copy2(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pool", required=True, help="Master Synthea FHIR output folder.")
    parser.add_argument("--existing-cases", default="data/public_synthetic/cases")
    parser.add_argument("--exclude-raw", default="data/public_synthetic/raw_fhir")
    parser.add_argument("--output", default="results/public_eval")
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--copy-to", default="")
    args = parser.parse_args()

    source_pool = Path(args.source_pool)
    existing_cases = Path(args.existing_cases)
    exclude_raw = Path(args.exclude_raw)
    output = Path(args.output)
    copy_to = Path(args.copy_to) if args.copy_to else None

    used_ids = set()
    used_ids.update(used_patient_ids_from_cases(existing_cases))
    used_ids.update(used_patient_ids_from_raw(exclude_raw))

    files = sorted(source_pool.glob("*.json"))

    candidates = [score_bundle(path, used_ids) for path in files]
    candidates = sorted(
        candidates,
        key=lambda x: float(x.get("complexity_score", 0)),
        reverse=True,
    )

    selected = select_cases(candidates, args.n)

    write_csv(output / "clinician_case_selection_candidates.csv", candidates)
    write_csv(output / "clinician_case_selection_30.csv", selected)
    write_report(output / "clinician_case_selection_report.md", selected, candidates)
    copy_selected_files(selected, copy_to)

    print(f"Scanned files: {len(files)}")
    print(f"Used/excluded patient IDs: {len(used_ids)}")
    print(f"Selected cases: {len(selected)}")
    print()
    print("Bucket counts:")
    for bucket, count in sorted(Counter(row["assigned_bucket"] for row in selected).items()):
        print(f"  {bucket}: {count}")

    print()
    print("Selected files:")
    for row in selected:
        print(
            f"{row['selected_rank']:02d}. {row['assigned_bucket']} | "
            f"score={row['complexity_score']} | "
            f"patient={row['patient_id']} | "
            f"{row['filename']}"
        )

    print()
    print(f"Wrote: {output / 'clinician_case_selection_candidates.csv'}")
    print(f"Wrote: {output / 'clinician_case_selection_30.csv'}")
    print(f"Wrote: {output / 'clinician_case_selection_report.md'}")

    if copy_to:
        print(f"Copied selected raw FHIR files to: {copy_to}")


if __name__ == "__main__":
    main()