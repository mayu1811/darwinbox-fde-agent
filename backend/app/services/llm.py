"""OpenAI-compatible LLM client (Ollama by default), with a hard fallback.

Design rule for this project: the LLM is an *advisor*, never the decision
maker. It can nudge a mapping confidence within a bounded range; the autonomy
thresholds, the validation rules and the escalation boundary stay
deterministic. That keeps behaviour reproducible for a demo and, more
importantly, keeps the blast radius of a hallucination at zero.

If LLM_PROVIDER is unset (the default) the whole module is a no-op and the
agent runs in DEMO MODE on deterministic rules alone.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import settings
from ..utils.logging import get_logger

log = get_logger("llm")

#: The LLM may only move a deterministic score by this much, either way.
MAX_LLM_ADJUSTMENT = 0.12

_SYSTEM_PROMPT = (
    "You are a data-migration schema mapping assistant. You are given one source "
    "column (its name, inferred type and sample values) and a list of candidate "
    "target fields. Reply with STRICT JSON only, no prose:\n"
    '{"target_field": "<one of the candidates or null>", "confidence": <0..1>, '
    '"reason": "<one short sentence>"}'
)


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.provider = settings.llm_provider.lower()
        self.enabled = settings.llm_enabled
        self._healthy: bool | None = None

    # -- transport ---------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.llm_api_key:
            headers["Authorization"] = f"Bearer {settings.llm_api_key}"
        return headers

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "provider": "none", "reachable": False,
                    "mode": "demo (deterministic rules)"}
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(
                    settings.llm_base_url.rstrip("/") + "/models", headers=self._headers()
                )
            reachable = resp.status_code < 500
        except Exception as exc:  # pragma: no cover - network dependent
            log.warn("llm_unreachable", provider=self.provider, error=type(exc).__name__)
            reachable = False
        self._healthy = reachable
        return {
            "enabled": True,
            "provider": self.provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "reachable": reachable,
            "mode": "llm-assisted" if reachable else "demo (fallback: LLM unreachable)",
        }

    def _chat(self, prompt: str) -> str:
        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        body = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "stream": False,
        }
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(url, headers=self._headers(), json=body)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]

    # -- public API --------------------------------------------------------
    def suggest_mapping(
        self, source_field: str, profile: dict, candidates: list[str]
    ) -> dict | None:
        """Return {target_field, confidence, reason} or None when unavailable."""
        if not self.enabled:
            return None
        if self._healthy is False:
            return None
        prompt = json.dumps(
            {
                "source_column": source_field,
                "inferred_type": profile.get("semantic_type"),
                "sample_values": profile.get("samples", [])[:5],
                "candidate_target_fields": candidates,
            },
            indent=2,
        )
        try:
            raw = self._chat(prompt)
            self._healthy = True
        except Exception as exc:  # pragma: no cover - network dependent
            log.warn("llm_call_failed", field=source_field, error=type(exc).__name__)
            self._healthy = False
            if not settings.llm_fallback_to_deterministic:
                raise LLMUnavailable(str(exc)) from exc
            return None

        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[-1] if "\n" in text else text
            text = text.rsplit("```", 1)[0]
        try:
            parsed = json.loads(text[text.find("{") : text.rfind("}") + 1])
        except Exception:
            log.warn("llm_unparseable_response", field=source_field)
            return None

        target = parsed.get("target_field")
        if target is not None and target not in candidates:
            return None
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "target_field": target,
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(parsed.get("reason", ""))[:280],
        }


llm_client = LLMClient()
