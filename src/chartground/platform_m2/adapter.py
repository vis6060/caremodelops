"""Subprocess boundary. Never import or reimplement the Claude workflow."""

import json
import re
import subprocess
import sys

from .database import ROOT

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens")
ATTEMPT_FIELDS = (*TOKEN_FIELDS, "attempt", "timestamp", "max_tokens", "api_status",
                  "generation_status", "model_id", "request_id", "stop_reason", "latency_ms")
RESULT_FIELDS = ("case_id", "provider", "status", "answer_source", "answer", "action",
                 "action_reason", "cited_evidence_ids", "claims", "missing_information", "plan", "error", "verification")


class AdapterError(RuntimeError):
    pass


def validate_result(value, body):
    if not isinstance(value, dict) or value.get("case_id") != body["case_id"] or value.get("provider") != body["provider"]:
        raise AdapterError("Subprocess result failed validation.")
    if value.get("status") not in {"success", "fallback"} or value.get("action") not in {"answer", "uncertain", "escalate", "abstain"}:
        raise AdapterError("Subprocess result failed validation.")
    usage = value.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("attempts"), list) or len(usage["attempts"]) > 2:
        raise AdapterError("Subprocess usage failed validation.")
    attempts = []
    for number, row in enumerate(usage["attempts"], 1):
        if not isinstance(row, dict) or row.get("attempt") != number:
            raise AdapterError("Subprocess attempts failed validation.")
        for field in TOKEN_FIELDS:
            v = row.get(field)
            if v is not None and (type(v) is not int or v < 0):
                raise AdapterError("Subprocess token counts failed validation.")
        attempts.append({k: row.get(k) for k in ATTEMPT_FIELDS})
    if body["provider"] == "mock" and attempts:
        raise AdapterError("Mock output cannot record Claude consumption.")
    result = {k: value.get(k) for k in RESULT_FIELDS}
    result["usage"] = {k: usage.get(k) for k in (*TOKEN_FIELDS, "model_id", "request_id", "stop_reason", "timestamp", "latency_ms", "status", "api_status", "generation_status")}
    result["usage"]["attempts"] = attempts
    return result


class SubprocessAdapter:
    def __call__(self, body):
        if not re.fullmatch(r"cg-syn-\d{3}", body["case_id"]) or body["provider"] not in {"mock", "claude"}:
            raise AdapterError("Only public synthetic cases are supported.")
        command = [sys.executable, str(ROOT / "scripts/developer_platform_demo.py"),
                   "--case-id", body["case_id"], "--question", body["question"], "--provider", body["provider"]]
        if body.get("model"):
            command += ["--model", body["model"]]
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                       encoding="utf-8", timeout=180, check=False)
            if completed.returncode != 0:
                raise AdapterError("Subprocess failed; consumption may be unknown.")
            return validate_result(json.loads(completed.stdout), body)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            raise AdapterError("Subprocess unavailable; consumption may be unknown.") from None
