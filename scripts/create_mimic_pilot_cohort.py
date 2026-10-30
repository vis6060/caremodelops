import argparse
import csv
from pathlib import Path

import duckdb


def normalize_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file: {path}")


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mimic-core",
        required=True,
        help="Path to extracted mimic-iv-3.1/mimic-iv-3.1 folder.",
    )
    parser.add_argument(
        "--mimic-note",
        required=True,
        help="Path to extracted mimic-iv-note-deidentified-free-text-clinical-notes-2.2 folder.",
    )
    parser.add_argument(
        "--out",
        default="results/mimic_private",
        help="Private output folder. Do not commit.",
    )
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    mimic_core = Path(args.mimic_core)
    mimic_note = Path(args.mimic_note)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    hosp = mimic_core / "hosp"
    icu = mimic_core / "icu"
    note = mimic_note / "note"

    required_files = {
        "patients": hosp / "patients.csv.gz",
        "admissions": hosp / "admissions.csv.gz",
        "labevents": hosp / "labevents.csv.gz",
        "d_labitems": hosp / "d_labitems.csv.gz",
        "prescriptions": hosp / "prescriptions.csv.gz",
        "procedures_icd": hosp / "procedures_icd.csv.gz",
        "diagnoses_icd": hosp / "diagnoses_icd.csv.gz",
        "d_icd_diagnoses": hosp / "d_icd_diagnoses.csv.gz",
        "icustays": icu / "icustays.csv.gz",
        "discharge": note / "discharge.csv.gz",
        "radiology": note / "radiology.csv.gz",
    }

    for file_path in required_files.values():
        require_file(file_path)

    con = duckdb.connect(database=":memory:")

    # Keep memory bounded.
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='8GB'")

    for name, path in required_files.items():
        con.execute(
            f"""
            CREATE OR REPLACE VIEW {name} AS
            SELECT *
            FROM read_csv_auto(
                '{normalize_path(path)}',
                header = true
            )
            """
        )

    print("Registered MIMIC views.")

    counts = []
    for name in required_files:
        count = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        counts.append({"table": name, "row_count": count})
        print(f"{name}: {count:,}")

    write_csv(
        out / "mimic_table_counts.csv",
        counts,
        ["table", "row_count"],
    )

    print()
    print("Selecting pilot admissions...")

    # Avoid chartevents for now. This pilot focuses on:
    # discharge notes, radiology notes, labs, prescriptions, diagnoses, procedures.
    query = f"""
    WITH adult_admissions AS (
        SELECT
            a.subject_id,
            a.hadm_id,
            a.admittime,
            a.dischtime,
            p.anchor_age,
            a.admission_type,
            a.insurance,
            a.race
        FROM admissions a
        JOIN patients p
            ON a.subject_id = p.subject_id
        WHERE p.anchor_age >= 18
          AND a.hadm_id IS NOT NULL
          AND a.dischtime IS NOT NULL
    ),
    discharge_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS discharge_note_count
        FROM discharge
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    radiology_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS radiology_note_count
        FROM radiology
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    lab_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS lab_count,
            COUNT(DISTINCT itemid) AS distinct_lab_items
        FROM labevents
        WHERE hadm_id IS NOT NULL
          AND valuenum IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    med_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS prescription_count,
            COUNT(DISTINCT drug) AS distinct_drugs
        FROM prescriptions
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    proc_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS procedure_count
        FROM procedures_icd
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    dx_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS diagnosis_count
        FROM diagnoses_icd
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    icu_counts AS (
        SELECT
            subject_id,
            hadm_id,
            COUNT(*) AS icu_stay_count
        FROM icustays
        WHERE hadm_id IS NOT NULL
        GROUP BY subject_id, hadm_id
    ),
    candidates AS (
        SELECT
            aa.subject_id,
            aa.hadm_id,
            aa.admittime,
            aa.dischtime,
            aa.anchor_age,
            aa.admission_type,
            aa.insurance,
            aa.race,
            COALESCE(dc.discharge_note_count, 0) AS discharge_note_count,
            COALESCE(rc.radiology_note_count, 0) AS radiology_note_count,
            COALESCE(lc.lab_count, 0) AS lab_count,
            COALESCE(lc.distinct_lab_items, 0) AS distinct_lab_items,
            COALESCE(mc.prescription_count, 0) AS prescription_count,
            COALESCE(mc.distinct_drugs, 0) AS distinct_drugs,
            COALESCE(pc.procedure_count, 0) AS procedure_count,
            COALESCE(dx.diagnosis_count, 0) AS diagnosis_count,
            COALESCE(ic.icu_stay_count, 0) AS icu_stay_count,
            (
                COALESCE(dc.discharge_note_count, 0) * 20
                + COALESCE(rc.radiology_note_count, 0) * 8
                + LEAST(COALESCE(lc.lab_count, 0), 200) * 0.5
                + COALESCE(lc.distinct_lab_items, 0) * 2
                + COALESCE(mc.distinct_drugs, 0) * 3
                + COALESCE(pc.procedure_count, 0) * 5
                + COALESCE(dx.diagnosis_count, 0) * 3
                + COALESCE(ic.icu_stay_count, 0) * 8
            ) AS richness_score
        FROM adult_admissions aa
        JOIN discharge_counts dc
          ON aa.subject_id = dc.subject_id
         AND aa.hadm_id = dc.hadm_id
        LEFT JOIN radiology_counts rc
          ON aa.subject_id = rc.subject_id
         AND aa.hadm_id = rc.hadm_id
        LEFT JOIN lab_counts lc
          ON aa.subject_id = lc.subject_id
         AND aa.hadm_id = lc.hadm_id
        LEFT JOIN med_counts mc
          ON aa.subject_id = mc.subject_id
         AND aa.hadm_id = mc.hadm_id
        LEFT JOIN proc_counts pc
          ON aa.subject_id = pc.subject_id
         AND aa.hadm_id = pc.hadm_id
        LEFT JOIN dx_counts dx
          ON aa.subject_id = dx.subject_id
         AND aa.hadm_id = dx.hadm_id
        LEFT JOIN icu_counts ic
          ON aa.subject_id = ic.subject_id
         AND aa.hadm_id = ic.hadm_id
        WHERE COALESCE(lc.lab_count, 0) >= 10
          AND COALESCE(mc.prescription_count, 0) >= 1
    )
    SELECT *
    FROM candidates
    ORDER BY richness_score DESC
    LIMIT {args.limit}
    """

    pilot_df = con.execute(query).fetchdf()
    pilot_path = out / "mimic_pilot_cohort_private.csv"
    pilot_df.to_csv(pilot_path, index=False)

    print(f"Pilot cohort rows: {len(pilot_df)}")
    print(f"Wrote private pilot cohort: {pilot_path}")
    print()
    print(pilot_df.head(args.limit).to_string(index=False))

    report = [
        "# MIMIC Pilot Cohort Summary",
        "",
        "This is a private local cohort file. Do not commit patient-level IDs or rows.",
        "",
        f"Pilot admissions selected: {len(pilot_df)}",
        "",
        "Selection requirements:",
        "",
        "- adult admissions",
        "- discharge note available",
        "- at least 10 numeric lab rows",
        "- at least 1 prescription row",
        "- radiology, procedures, ICU are optional but scored when present",
        "",
        "Next step:",
        "",
        "Use this pilot cohort to build the MIMIC-to-ChartGround canonical adapter.",
    ]

    (out / "mimic_pilot_cohort_summary.md").write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print(f"Wrote: {out / 'mimic_pilot_cohort_summary.md'}")


if __name__ == "__main__":
    main()