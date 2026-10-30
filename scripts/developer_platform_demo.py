"""Explicitly opt-in Claude demo over public synthetic cases."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from chartground.developer_platform.workflow import run
from chartground.developer_platform.config import load_configuration


def main():
    config = load_configuration()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--provider", choices=["mock", "claude"], default="mock")
    parser.add_argument("--model", default=config.model)
    args = parser.parse_args()
    if args.provider == "claude" and not args.model:
        parser.error("Claude execution requires --model or ANTHROPIC_MODEL")
    try:
        result = run(args.case_id, args.question, args.provider, args.model)
    except (ValueError, OSError, KeyError):
        parser.exit(2, "Public case validation failed; no model request was made.\n")
    displayed = {key: result[key] for key in (
        "case_id", "provider", "status", "answer_source", "answer", "action", "action_reason",
        "cited_evidence_ids", "claims", "missing_information", "plan", "usage", "error", "verification")}
    print(json.dumps(displayed, indent=2))


if __name__ == "__main__":
    main()
