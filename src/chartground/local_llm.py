"""Optional local LLM client abstraction for ChartGround."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResult:
    text: str
    used_provider: str
    error: str | None = None


class LocalLLMClient:
    """Local-only LLM interface with deterministic fallback."""

    def __init__(self, provider: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        self.provider = (provider or os.getenv("CHARTGROUND_LLM_PROVIDER", "none")).lower()
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "")

    def generate(self, prompt: str, fallback_text: str) -> LLMResult:
        if self.provider != "ollama":
            return LLMResult(text=fallback_text, used_provider="deterministic_fallback", error=None)
        if not self.model:
            return LLMResult(
                text=fallback_text,
                used_provider="deterministic_fallback",
                error="CHARTGROUND_LLM_PROVIDER=ollama but OLLAMA_MODEL is not set.",
            )
        try:
            return LLMResult(text=self._call_ollama(prompt), used_provider="ollama", error=None)
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return LLMResult(text=fallback_text, used_provider="deterministic_fallback", error=f"Ollama unavailable: {exc}")

    def _call_ollama(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(body.get("response") or "").strip()
