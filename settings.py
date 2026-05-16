"""
Global settings and policy loader.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional

# Backend URLs
GATEWAY_UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
BACKEND_BASE = "https://api.openai.com/v1"

# Auth
KEY_CLIENT_ID = os.getenv("GATEWAY_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
AUTH_ROOT = os.getenv("GATEWAY_AUTH_ROOT", "https://auth.openai.com")


def _load_resource(name: str) -> str:
    search_paths = [Path.cwd() / name, Path(__file__).parent / name]
    for p in search_paths:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return ""


# 加载指令集
SYSTEM_PROMPT = _load_resource("identity_policy.txt") or "You are a helpful assistant."
SPECIAL_PROMPT = _load_resource("codex_policy.txt") or SYSTEM_PROMPT
