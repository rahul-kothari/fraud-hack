"""Name variant groups and company legal forms (SOP name_variants.json)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).with_name("data") / "name_variants.json"


@dataclass
class Variants:
    groups: list[frozenset[str]] = field(default_factory=list)
    legal_forms: frozenset[str] = frozenset()
    _index: dict[str, set[int]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._index = {}
        for i, g in enumerate(self.groups):
            for name in g:
                self._index.setdefault(name, set()).add(i)

    def same_group(self, a: str, b: str) -> bool:
        ia = self._index.get(a)
        return bool(ia and ia & self._index.get(b, set()))

    def variants_of(self, a: str) -> set[str]:
        out: set[str] = set()
        for i in self._index.get(a, ()):
            out |= self.groups[i]
        out.discard(a)
        return out

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Variants":
        """Load the SOP's variants file.

        Accepts the bundled format ({"given_name_groups": [...],
        "company_legal_forms": [...]}) and the shapes the data room file is
        likely to use: a bare list of groups, or a dict whose list-of-lists
        value holds the groups and whose list-of-strings value the legal forms.
        """
        path = Path(path or os.environ.get("NAME_VARIANTS_PATH") or DEFAULT_PATH)
        raw = json.loads(path.read_text(encoding="utf-8"))
        groups: list[list[str]] = []
        forms: list[str] = []
        if isinstance(raw, list):
            groups = raw
        elif isinstance(raw, dict):
            for key, value in raw.items():
                if not isinstance(value, list) or key.startswith("_"):
                    continue
                if value and all(isinstance(v, list) for v in value):
                    groups.extend(value)
                elif value and all(isinstance(v, str) for v in value):
                    if "form" in key.lower() or "legal" in key.lower() or "compan" in key.lower():
                        forms.extend(value)
                    else:  # a dict of name -> [variants] flattened elsewhere
                        groups.append(value)
                elif value and all(isinstance(v, dict) for v in value):
                    for v in value:
                        members = v.get("variants") or v.get("names") or v.get("group") or []
                        if v.get("name"):
                            members = [v["name"], *members]
                        groups.append(members)
            # {"muhammad": ["mohammed", ...], ...}
            if not groups and all(isinstance(v, list) for v in raw.values()):
                groups = [[k, *v] for k, v in raw.items()]
        norm = lambda s: s.strip().lower().replace(".", "")
        return cls(
            groups=[frozenset(norm(n) for n in g if isinstance(n, str)) for g in groups if g],
            legal_forms=frozenset(norm(f) for f in forms),
        )


_DEFAULT: Variants | None = None


def default_variants() -> Variants:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Variants.load()
    return _DEFAULT
