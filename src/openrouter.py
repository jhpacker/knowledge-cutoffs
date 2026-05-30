"""Thin OpenRouter API client (chat completions + model catalog)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

API_BASE = "https://openrouter.ai/api/v1"
FRONTEND_BASE = "https://openrouter.ai/api/frontend"


class OpenRouterError(RuntimeError):
    pass


@dataclass
class ChatResult:
    text: str
    ok: bool
    error: str | None = None


class OpenRouter:
    def __init__(self, api_key: str | None = None, timeout: int = 60):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY not set (check your .env)")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/knowlege-cutoffs",
                "X-Title": "knowledge-cutoff-probe",
                "Content-Type": "application/json",
            }
        )

    # ---- model catalog -------------------------------------------------
    def list_models(self) -> list[dict]:
        r = self.session.get(f"{API_BASE}/models", timeout=self.timeout)
        r.raise_for_status()
        return r.json()["data"]

    def top_models(self, order: str = "top-weekly") -> list[dict]:
        """Ranked leaderboard via the frontend endpoint (slug, name, author, ...)."""
        r = self.session.get(
            f"{FRONTEND_BASE}/models/find", params={"order": order}, timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()["data"]["models"]

    # ---- chat ----------------------------------------------------------
    def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 400,
        retries: int = 3,
    ) -> ChatResult:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        last_err = None
        for attempt in range(retries):
            try:
                r = self.session.post(
                    f"{API_BASE}/chat/completions", json=payload, timeout=self.timeout
                )
                if r.status_code == 429 or r.status_code >= 500:
                    last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                data = r.json()
                if "choices" not in data or not data["choices"]:
                    return ChatResult("", False, f"no choices: {str(data)[:200]}")
                msg = data["choices"][0]["message"]
                text = msg.get("content") or ""
                if isinstance(text, list):  # some providers return content parts
                    text = " ".join(
                        p.get("text", "") for p in text if isinstance(p, dict)
                    )
                return ChatResult(text.strip(), True)
            except requests.RequestException as e:
                last_err = str(e)
                time.sleep(2 * (attempt + 1))
        return ChatResult("", False, last_err or "unknown error")
