"""
System Model Catalog and capability registry.
系统模型目录和能力注册表。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, List, FrozenSet, Tuple


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    backend: str
    aliases: Tuple[str, ...]
    reasoning_bounds: FrozenSet[str]
    default_variants: Tuple[str, ...]
    is_special: bool = False


class ModelCapabilityHub:
    _SPECS = [
        CapabilitySpec("gpt-5", "gpt-5", ("gpt5", "gpt-5-latest"), frozenset(("none", "minimal", "low", "medium", "high", "xhigh")), ("high", "medium", "low")),
        CapabilitySpec("gpt-5.4", "gpt-5.4", ("gpt5.4", "gpt-5.4-latest"), frozenset(("none", "low", "medium", "high", "xhigh")), ("xhigh", "high", "medium")),
        CapabilitySpec("gpt-5.4-mini", "gpt-5.4-mini", (), frozenset(("low", "medium", "high")), ("high", "medium")),
        CapabilitySpec("gpt-5-codex", "gpt-5-codex", ("codex", "gpt-5-codex-latest"), frozenset(("none", "low", "medium", "high")), ("high", "medium"), is_special=True),
        CapabilitySpec("codex-mini", "codex-mini-latest", ("codex-mini",), frozenset(("low", "medium", "high")), (), is_special=True),
    ]

    def __init__(self):
        self._lookup = {}
        for s in self._SPECS:
            self._lookup[s.id] = s
            for a in s.aliases: self._lookup[a] = s

    def resolve_tag(self, name: Optional[str]) -> Tuple[str, Optional[str]]:
        """Identify base model and reasoning effort from a string."""
        if not name: return "gpt-5.4", None
        raw = name.strip().lower()
        
        effort = None
        for e in ("none", "minimal", "low", "medium", "high", "xhigh"):
            for sep in (":", "-", "_"):
                suffix = f"{sep}{e}"
                if raw.endswith(suffix):
                    effort = e
                    raw = raw[:-len(suffix)]
                    break
        return raw, effort

    def map_target(self, name: Optional[str]) -> str:
        base, _ = self.resolve_tag(name)
        spec = self._lookup.get(base)
        return spec.backend if spec else base

    def is_isolated(self, name: Optional[str]) -> bool:
        base, _ = self.resolve_tag(name)
        spec = self._lookup.get(base)
        return spec.is_special if spec else "codex" in (name or "").lower()

    def supported_levels(self, name: Optional[str]) -> FrozenSet[str]:
        base, _ = self.resolve_tag(name)
        spec = self._lookup.get(base)
        return spec.reasoning_bounds if spec else frozenset(["medium"])

    def available_ids(self, expand: bool = False) -> List[str]:
        res = []
        for s in self._SPECS:
            res.append(s.id)
            if expand: res.extend([f"{s.id}-{v}" for v in s.default_variants])
        return res

model_hub = ModelCapabilityHub()
