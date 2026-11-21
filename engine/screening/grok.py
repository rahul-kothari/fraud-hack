"""Grok (xAI) as an extraction tool for free text the regex parsers can't fully read.

Grok never makes the decision. It only turns one piece of text into a small JSON record whose
schema is fixed per task. Every answer is cached on disk by (model, task, text), so reruns are
reproducible and free.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any

from .config import CACHE, GROK_MODEL, XAI_API_KEY, XAI_BASE_URL

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_INT = {"type": ["integer", "null"]}


def _obj(props: dict[str, Any]) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


TASKS: dict[str, dict[str, Any]] = {
    "kyc_note": {
        "instructions": (
            "The text is a note from a bank's onboarding team about an identity verification. "
            "Extract the verified person's or company's name exactly as written, their date of birth, "
            "the country that issued the document, the document type, the verification provider, the date "
            "the check was done, and whether the check was approved (passed). Give dates as ISO "
            "YYYY-MM-DD, or YYYY-MM / YYYY when only partly given. Use null for anything not stated."),
        "schema": _obj({"name": _NULLABLE_STR, "dob": _NULLABLE_STR, "document_country": _NULLABLE_STR,
                        "document_type": _NULLABLE_STR, "provider": _NULLABLE_STR,
                        "checked_at": _NULLABLE_STR, "approved": {"type": ["boolean", "null"]}}),
    },
    "residence_note": {
        "instructions": (
            "The text is a note from a bank's support tool. List the countries the note says the "
            "customer lived or resided in (not countries merely mentioned for other reasons). "
            "Use English country names. Return an empty list when there are none."),
        "schema": _obj({"countries": {"type": "array", "items": {"type": "string"}}}),
    },
    "age_sentence": {
        "instructions": (
            "The text is the first paragraph of a watchlist profile. If it states the subject's age at a "
            "particular time (e.g. 'aged 30 in November 1998', 'in January 2025 he was 38'), return "
            "kind='age_at_date' with the age and the date of that time (ISO, YYYY-MM-DD, YYYY-MM or YYYY). "
            "If it states the date of birth, return kind='birth_date' with birth_date in ISO. Otherwise "
            "kind='none'. Only use facts about the profile's subject that are stated in the text."),
        "schema": _obj({"kind": {"type": "string", "enum": ["age_at_date", "birth_date", "none"]},
                        "age": _NULLABLE_INT, "at_date": _NULLABLE_STR, "birth_date": _NULLABLE_STR}),
    },
    "search_snippet": {
        "instructions": (
            "The text is a web search snippet about a named person. Extract the person's stated age, the "
            "date the snippet refers to (ISO YYYY-MM or YYYY-MM-DD or YYYY), and the country the person "
            "is described in. Use null for anything not stated."),
        "schema": _obj({"age": _NULLABLE_INT, "at_date": _NULLABLE_STR, "country": _NULLABLE_STR}),
    },
}


class Grok:
    def __init__(self, model: str = GROK_MODEL, api_key: str | None = XAI_API_KEY,
                 base_url: str = XAI_BASE_URL, offline: bool = False):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.offline = offline or not api_key   # offline: answer from cache only
        self.cache_dir = CACHE / "grok"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0
        self.cache_hits = 0
        self.errors = 0

    @property
    def available(self) -> bool:
        return not self.offline

    def _key(self, task: str, text: str) -> str:
        return hashlib.sha256(f"{self.model}\x00{task}\x00{text}".encode()).hexdigest()

    def extract(self, task: str, text: str) -> dict | None:
        spec = TASKS[task]
        path = self.cache_dir / f"{self._key(task, text)}.json"
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["result"]
        if self.offline:
            return None
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": spec["instructions"] + " Reply with JSON only."},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": task, "schema": spec["schema"], "strict": True}},
        }
        payload = json.dumps(body).encode()
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions", data=payload, method="POST",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    reply = json.loads(resp.read().decode())
                content = reply["choices"][0]["message"]["content"]
                result = json.loads(content)
                self.calls += 1
                path.write_text(json.dumps({"task": task, "model": self.model, "text": text,
                                            "result": result}, ensure_ascii=False), encoding="utf-8")
                return result
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    break                       # 4xx other than rate limit: retrying won't help
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
                if attempt == 3:
                    break
                time.sleep(2 ** attempt)
        self.errors += 1
        return None

    def stats(self) -> str:
        mode = "offline (cache only)" if self.offline else f"live, model {self.model}"
        return f"grok {mode}: {self.calls} calls, {self.cache_hits} cache hits, {self.errors} errors"
