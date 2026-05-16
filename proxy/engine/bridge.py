"""
Backend to Frontend stream bridge.
后端到前端的流桥接器。
"""
from __future__ import annotations
import json
import time
from typing import AsyncGenerator, Dict, Any, Optional, Tuple

import httpx


class FlowAdapter:
    @staticmethod
    async def _read_stream(response: httpx.Response) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                raw = line[len("data: "):].strip()
                if raw == "[DONE]": yield "[DONE]", {}
                else:
                    try: yield "data", json.loads(raw)
                    except Exception: continue

    @classmethod
    async def stream_response(
        cls, response: httpx.Response, meta: Dict[str, Any]
    ) -> AsyncGenerator[str, None]:
        rid = "chatcmpl-stream"
        model, created = meta["model"], meta["created"]
        think_mode = (meta.get("reasoning_compat") or "think-tags").strip().lower()
        include_usage = meta.get("include_usage", False)
        
        think_open, think_closed = False, False
        sent_stop = False
        usage_data = None

        def _wrap(delta: Dict[str, Any], finish: Optional[str] = None) -> str:
            payload = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        async for kind, data in cls._read_stream(response):
            if kind == "[DONE]": break
            
            ev_type = data.get("type")
            resp_info = data.get("response")
            if isinstance(resp_info, dict) and isinstance(resp_info.get("id"), str):
                rid = resp_info.get("id") or rid

            # 1. 处理正文内容 / Handle output text
            if ev_type == "response.output_text.delta":
                delta_val = data.get("delta") or ""
                if think_mode == "think-tags" and think_open and not think_closed:
                    yield _wrap({"content": "</think>"})
                    think_open, think_closed = False, True
                yield _wrap({"content": delta_val})

            # 2. 处理推理内容 / Handle reasoning
            elif ev_type in ("response.reasoning_text.delta", "response.reasoning_summary_text.delta"):
                delta_val = data.get("delta") or ""
                if think_mode == "o3":
                    yield _wrap({"reasoning_content": delta_val})
                elif think_mode == "think-tags":
                    if not think_open and not think_closed:
                        yield _wrap({"content": "<think>"})
                        think_open = True
                    if think_open and not think_closed:
                        yield _wrap({"content": delta_val})
            
            # 3. 处理工具调用 / Handle tool calls
            elif ev_type == "response.output_item.done":
                item = data.get("item") or {}
                if item.get("type") == "function_call":
                    yield _wrap({"tool_calls": [{"index": 0, "id": item.get("call_id"), "type": "function", "function": {"name": item.get("name"), "arguments": item.get("arguments")}}]})

            # 4. 完成事件 / Completion
            elif ev_type == "response.completed":
                usage = (data.get("response") or {}).get("usage")
                if isinstance(usage, dict):
                    pt = int(usage.get("input_tokens") or 0)
                    ct = int(usage.get("output_tokens") or 0)
                    usage_data = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": usage.get("total_tokens") or (pt + ct)}
                
                if think_mode == "think-tags" and think_open and not think_closed:
                    yield _wrap({"content": "</think>"})
                    think_open, think_closed = False, True
                
                if not sent_stop:
                    yield _wrap({}, finish="stop")
                    sent_stop = True
                
                if include_usage and usage_data:
                    u_payload = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": None}], "usage": usage_data}
                    yield f"data: {json.dumps(u_payload, ensure_ascii=False)}\n\n"
                break
                
        yield "data: [DONE]\n\n"

    @classmethod
    async def sync_response(cls, response: httpx.Response, meta: Dict[str, Any]) -> Dict[str, Any]:
        rid = "chatcmpl"
        model, created, think_mode = meta["model"], meta["created"], (meta.get("reasoning_compat") or "think-tags").strip().lower()
        
        full_text, reasoning_text = "", ""
        usage_data, tool_calls = None, []
        
        async for kind, data in cls._read_stream(response):
            if kind == "[DONE]": break
            
            ev_type = data.get("type")
            resp_info = data.get("response")
            if isinstance(resp_info, dict) and isinstance(resp_info.get("id"), str):
                rid = resp_info.get("id") or rid
            
            if ev_type == "response.output_text.delta":
                full_text += data.get("delta") or ""
            elif ev_type in ("response.reasoning_text.delta", "response.reasoning_summary_text.delta"):
                reasoning_text += data.get("delta") or ""
            elif ev_type == "response.output_item.done":
                item = data.get("item") or {}
                if item.get("type") == "function_call":
                    tool_calls.append({"id": item.get("call_id"), "type": "function", "function": {"name": item.get("name"), "arguments": item.get("arguments")}})
            elif ev_type == "response.completed":
                usage = (data.get("response") or {}).get("usage")
                if isinstance(usage, dict):
                    pt = int(usage.get("input_tokens") or 0)
                    ct = int(usage.get("output_tokens") or 0)
                    usage_data = {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": usage.get("total_tokens") or (pt + ct)}
                break

        content = full_text
        if reasoning_text and think_mode == "think-tags":
            content = f"<think>{reasoning_text}</think>{full_text}"
        
        msg = {"role": "assistant", "content": content}
        if reasoning_text and think_mode == "o3":
            msg["reasoning_content"] = reasoning_text
        if tool_calls:
            msg["tool_calls"] = tool_calls
            
        res = {"id": rid, "object": "chat.completion", "created": created, "model": model, "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]}
        if usage_data:
            res["usage"] = usage_data
        return res
