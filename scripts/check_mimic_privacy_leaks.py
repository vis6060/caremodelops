"""Scan public-safe MIMIC summaries for restricted content patterns."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


PATTERNS = [
    ("subject_id label", re.compile(r"\bsubject_id\b", re.IGNORECASE)),
    ("hadm_id label", re.compile(r"\bhadm_id\b", re.IGNORECASE)),
    ("stay_id label", re.compile(r"\bstay_id\b", re.IGNORECASE)),
    ("note_id label", re.compile(r"\bnote_id\b", re.IGNORECASE)),
    ("raw mimic data path", re.compile(r"MIMICdata", re.IGNORECASE)),
    ("local user path", re.compile(r"C:\\Users\\", re.IGNORECASE)),
    ("long numeric identifier", re.compile(r"\b\d{7,}\b")),
    ("note-like long text", re.compile(r"(history of present illness|discharge diagnosis|brief hospital course|findings:|impression:).{120,}", re.IGNORECASE | re.DOTALL)),
    ("table row dump", re.compile(r"\b(subject_id|hadm_id|note_id)\s*,\s*(hadm_id|charttime|text)\b", re.IGNORECASE)),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Check public-safe outputs for MIMIC privacy leaks.")
    parser.add_argument("--paths", nargs="+", required=True)
    args = parser.parse_args()

    findings = []
    for root in [Path(path) for path in args.paths]:
        for file_path in iter_files(root):
            findings.extend(scan_file(file_path))
    if findings:
        print(f"Privacy leak scan failed with {len(findings)} finding(s).")
        for finding in findings[:50]:
            print(f"{finding['path']}: {finding['pattern']}")
        sys.exit(1)
    print("Privacy leak scan passed.")


def iter_files(root: Path):
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path):
            continue
        if path.suffix.lower() in {".md", ".json", ".csv", ".txt"}:
            yield path


def should_skip(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    if "results/mimic_private/" in normalized and "public_safe_summary" not in normalized:
        return True
    return False


def scan_file(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    for label, pattern in PATTERNS:
        if pattern.search(text):
            findings.append({"path": str(path), "pattern": label})
    return findings


if __name__ == "__main__":
    main()
