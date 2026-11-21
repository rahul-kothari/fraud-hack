"""Extract the names and aliases of a watchlist hit.

The workbook shows aliases as one string, ``"Name (AKA); نام (None, Arabic);
2734 2651 (CCC)"``. The JSON Lines source may hold a list of strings or of
objects. Both are accepted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

_TAG = re.compile(r"\s*[\(（]([^()（）]*)[\)）]\s*$")


@dataclass(frozen=True)
class HitName:
    text: str
    kind: str = "name"      # name | AKA | Nickname | Acronym | DBA | CCC | <script> ...
    primary: bool = False

    @property
    def is_telegraph_code(self) -> bool:
        return self.kind.upper().startswith("CCC")


def _split_alias_string(s: str) -> list[tuple[str, str]]:
    out = []
    for chunk in re.split(r"\s*;\s*|\n+", s):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _TAG.search(chunk)
        kind = m.group(1).strip() if m else "AKA"
        out.append((chunk, kind))
    return out


def _alias_items(value: Any) -> Iterable[tuple[str, str]]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_alias_string(value)
    items: list[tuple[str, str]] = []
    if isinstance(value, dict):
        value = [value]
    for v in value:
        if isinstance(v, str):
            items += _split_alias_string(v)
        elif isinstance(v, dict):
            text = v.get("name") or v.get("alias") or v.get("value") or v.get("full_name") or ""
            kind = v.get("type") or v.get("kind") or v.get("alias_type") or v.get("script") or "AKA"
            if text:
                items.append((str(text), str(kind)))
    return items


def hit_names(hit: dict, include_telegraph_codes: bool = False) -> list[HitName]:
    """Primary name first, then aliases (deduplicated, order kept)."""
    names: list[HitName] = []
    primary = hit.get("name") or hit.get("full_name") or hit.get("primary_name")
    if primary:
        names.append(HitName(str(primary), "name", primary=True))
    for text, kind in _alias_items(hit.get("aliases")):
        hn = HitName(text, kind)
        if hn.is_telegraph_code and not include_telegraph_codes:
            continue
        names.append(hn)
    seen: set[str] = set()
    unique = []
    for n in names:
        if n.text not in seen:
            seen.add(n.text)
            unique.append(n)
    return unique
