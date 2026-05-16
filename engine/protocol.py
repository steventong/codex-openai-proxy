"""
Core mapping engine for cross-API communication.
"""
from __future__ import annotations
import base64
import json
import binascii
from typing import Any, Dict, List, Optional


class CodecRegistry:
    @staticmethod
    def parse_claims(token: str) -> Optional[Dict[str, Any]]:
        """Safely unravel information from encoded bearer tokens."""
        try:
            if not token or token.count(".") != 2: return None
            # 提取 payload 部分
            p = token.split(".")[1]
            # 自动补全填充并解码
            padded = p + "=" * (-len(p) % 4)
            return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        except Exception: return None

    @staticmethod
    def _sanitize_b64(raw: str) -> str:
        """Sanitize base64 strings for standard decoding."""
        try:
            if not raw or "," not in raw: return raw
            prefix, data = raw.split(",", 1)
            clean_data = data.replace("-", "+").replace("_", "/").strip()
            missing_padding = len(clean_data) % 4
            if missing_padding: clean_data += "=" * (4 - missing_padding)
            return f"{prefix},{clean_data}"
        except Exception: return raw

    @classmethod
    def ingest_messages(cls, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ingest external messages into internal format."""
        result = []
        handlers = {
            "user": cls._process_user_part,
            "assistant": cls._process_assistant_part,
            "tool": cls._process_tool_part
        }
        for m in messages:
            role = m.get("role")
            handler = handlers.get(role)
            if handler:
                node = handler(m)
                if isinstance(node, list): result.extend(node)
                elif node: result.append(node)
        return result

    @classmethod
    def _process_user_part(cls, m: Dict[str, Any]) -> Dict[str, Any]:
        content = m.get("content", "")
        parts = []
        if isinstance(content, list):
            for p in content:
                if p.get("type") == "text":
                    parts.append({"type": "input_text", "text": p.get("text", "")})
                elif p.get("type") == "image_url":
                    url = p.get("image_url", {}).get("url") if isinstance(p.get("image_url"), dict) else p.get("image_url")
                    if url: parts.append({"type": "input_image", "image_url": cls._sanitize_b64(url)})
        else:
            parts.append({"type": "input_text", "text": str(content)})
        return {"type": "message", "role": "user", "content": parts}

    @classmethod
    def _process_assistant_part(cls, m: Dict[str, Any]) -> List[Dict[str, Any]]:
        nodes = []
        if "tool_calls" in m:
            for tc in m["tool_calls"]:
                f = tc.get("function", {})
                nodes.append({"type": "function_call", "name": f.get("name"), "arguments": f.get("arguments"), "call_id": tc.get("id")})
        content = m.get("content", "")
        if content:
            nodes.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": str(content)}]})
        return nodes

    @classmethod
    def _process_tool_part(cls, m: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "function_call_output", "call_id": m.get("tool_call_id") or m.get("id"), "output": str(m.get("content", ""))}

    @staticmethod
    def translate_tools(tools: Any) -> List[Dict[str, Any]]:
        """Map tool definitions."""
        if not isinstance(tools, list): return []
        res = []
        for t in tools:
            kind = t.get("type")
            if kind in ("web_search", "web_search_preview"):
                res.append({"type": kind})
            elif kind == "function":
                fn = t.get("function", {})
                res.append({"type": "function", "name": fn.get("name"), "description": fn.get("description", ""), "parameters": fn.get("parameters")})
        return res
