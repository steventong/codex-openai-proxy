"""
Dialog history and sequence tracking.
对话历史和序列跟踪。
"""
from __future__ import annotations
import hashlib
import time
from typing import Any, Dict, List, Optional


class DialogManager:
    def __init__(self):
        self._states: Dict[str, Dict[str, Any]] = {}

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def fetch_context(self, context: str, items: List[Dict[str, Any]], override: Optional[str] = None) -> str:
        if override: return override
        seed = context
        if items:
            first = items[0].get("content")
            if isinstance(first, list) and first: seed += str(first[0].get("text") or "")
            else: seed += str(first or "")
        return self._hash(seed)

    def track_event(self, sid: str, event: Dict[str, Any]) -> None:
        state = self._states.setdefault(sid, {"last": None, "ts": time.time()})
        state["ts"] = time.time()
        name = event.get("event")
        if name == "response.completed":
            rid = (event.get("response") or {}).get("id")
            if rid: state["last"] = rid

    def get_last_reference(self, sid: str) -> Optional[str]:
        return self._states.get(sid, {}).get("last")

    def cleanup_expired(self, ttl: int = 3600) -> int:
        now = time.time()
        expired = [k for k, v in self._states.items() if now - v["ts"] > ttl]
        for k in expired: del self._states[k]
        return len(self._states)

session_manager = DialogManager()
