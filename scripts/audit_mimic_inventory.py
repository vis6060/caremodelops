import argparse
import csv
import gzip
import zipfile
from pathlib import Path


def safe_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def read_header_from_file(path: Path) -> list[str]:
    if path.suffix == ".gz" or path.name.endswith(".csv.gz"):
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as file:
            header = file.readline().strip()
    else:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            header = file.readline().strip()

    if not header:
        return []

    return [column.strip() for column in header.split(",")]


def read_header_from_zip_member(zip_file: zipfile.ZipFile, member_name: str) -> list[str]:
    with zip_file.open(member_name) as raw:
        if member_name.endswith(".gz"):
            with gzip.GzipFile(fileobj=raw) as gz:
                header = gz.readline().decode("utf-8", errors="replace").strip()
        else:
            header = raw.readline().decode("utf-8", errors="replace").strip()

    if not header:
        return []

    return [column.strip() for column in header.split(",")]


def inventory_zip_archives(root: Path) -> tuple[list[dict], list[dict]]:
    archive_rows = []
    header_rows = []

    for zip_path in sorted(root.rglob("*.zip")):
        archive_rows.append(
            {
                "archive_path": str(zip_path),
                "archive_name": zip_path.name,
                "size_mb": round(zip_path.stat().st_size / 1_000_000, 2),
            }
        )

        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue

                    member = info.filename
                    lower_member = member.lower()

                    if not (
                        lower_member.endswith(".csv")
                        or lower_member.endswith(".csv.gz")
                    ):
                        continue

                    columns = []
                    header_error = ""

                    try:
                        columns = read_header_from_zip_member(zf, member)
                    except Exception as exc:
                        header_error = str(exc)

                    header_rows.append(
                        {
                            "location_type": "zip_member",
                            "archive_name": zip_path.name,
                            "path": member,
                            "file_size_mb": round(info.file_size / 1_000_000, 2),
                            "compressed_size_mb": round(info.compress_size / 1_000_000, 2),
                            "column_count": len(columns),
                            "columns": "|".join(columns),
                            "header_error": header_error,
                        }
                    )
        except Exception as exc:
            header_rows.append(
                {
                    "location_type": "zip_error",
                    "archive_name": zip_path.name,
                    "path": "",
                    "file_size_mb": "",
                    "compressed_size_mb": "",
                    "column_count": "",
                    "columns": "",
                    "header_error": str(exc),
                }
            )

    return archive_rows, header_rows


def inventory_extracted_files(root: Path) -> list[dict]:
    rows = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        lower_name = path.name.lower()

        if not (lower_name.endswith(".csv") or lower_name.endswith(".csv.gz")):
            continue

        columns = []
        header_error = ""

        try:
            columns = read_header_from_file(path)
        except Exception as exc:
            header_error = str(exc)

        rows.append(
            {
                "location_type": "extracted_file",
                "archive_name": "",
                "path": safe_relpath(path, root),
                "file_size_mb": round(path.stat().st_size / 1_000_000, 2),
                "compressed_size_mb": "",
                "column_count": len(columns),
                "columns": "|".join(columns),
                "header_error": header_error,
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_tree_report(root: Path, out_path: Path, max_entries: int = 500) -> None:
    paths = []

    for path in sorted(root.rglob("*")):
        if len(paths) >= max_entries:
            break

        if path.is_file():
            size_mb = round(path.stat().st_size / 1_000_000, 2)
            paths.append(f"- FILE {safe_relpath(path, root)} ({size_mb} MB)")
        elif path.is_dir():
            paths.append(f"- DIR  {safe_relpath(path, root)}")

    text = [
        "# MIMIC Local Folder Inventory",
        "",
        f"Root: `{root}`",
        "",
        "This file lists paths only. It does not include patient-level data.",
        "",
        "## Folder tree excerpt",
        "",
        *paths,
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(text), encoding="utf-8")


def write_summary_report(root: Path, out_path: Path, archive_rows: list[dict], header_rows: list[dict]) -> None:
    table_names = []

    for row in header_rows:
        table_path = row.get("path", "")
        if table_path:
            table_names.append(table_path)

    lines = [
        "# MIMIC Inventory Summary",
        "",
        f"Root: `{root}`",
        "",
        "## Archives found",
        "",
    ]

    for archive in archive_rows:
        lines.append(
            f"- {archive['archive_name']} — {archive['size_mb']} MB"
        )

    lines.extend(
        [
            "",
            "## CSV/CSV.GZ files discovered",
            "",
            f"Total discovered: {len(header_rows)}",
            "",
            "## Important next checks",
            "",
            "- Confirm `mimic-iv-3.1/hosp` exists.",
            "- Confirm `mimic-iv-3.1/icu` exists.",
            "- Confirm MIMIC-IV-Note discharge and radiology files exist.",
            "- Do not publish raw notes, patient rows, or patient-level outputs.",
            "- Use only aggregate MIMIC metrics in the public repo.",
        ]
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Restricted MIMIC folder.")
    parser.add_argument("--out", default="results/mimic_inventory")
    args = parser.parse_args()

    root = Path(args.root)
    out = Path(args.out)

    if not root.exists():
        raise FileNotFoundError(f"MIMIC root does not exist: {root}")

    archive_rows, zip_header_rows = inventory_zip_archives(root)
    extracted_header_rows = inventory_extracted_files(root)

    all_header_rows = zip_header_rows + extracted_header_rows

    write_csv(
        out / "archives.csv",
        archive_rows,
        ["archive_path", "archive_name", "size_mb"],
    )

    write_csv(
        out / "csv_headers.csv",
        all_header_rows,
        [
            "location_type",
            "archive_name",
            "path",
            "file_size_mb",
            "compressed_size_mb",
            "column_count",
            "columns",
            "header_error",
        ],
    )

    write_tree_report(root, out / "folder_tree.md")
    write_summary_report(root, out / "inventory_summary.md", archive_rows, all_header_rows)

    print(f"Root: {root}")
    print(f"Archives found: {len(archive_rows)}")
    print(f"CSV/CSV.GZ files discovered: {len(all_header_rows)}")
    print(f"Wrote: {out / 'archives.csv'}")
    print(f"Wrote: {out / 'csv_headers.csv'}")
    print(f"Wrote: {out / 'folder_tree.md'}")
    print(f"Wrote: {out / 'inventory_summary.md'}")


if __name__ == "__main__":
    main()