"""
Entry Gateway orchestrator.
"""
from __future__ import annotations
import logging
import time
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import HTTPException

from identity import account_store
from settings import GATEWAY_UPSTREAM, SYSTEM_PROMPT, SPECIAL_PROMPT
from engine.catalog import model_hub
from engine.protocol import CodecRegistry
from engine.history import session_manager

logger = logging.getLogger("Gateway")


class Orchestrator:
    @staticmethod
    def resolve_instructions(model: str) -> str:
        return SPECIAL_PROMPT if model_hub.is_isolated(model) else SYSTEM_PROMPT

    @staticmethod
    def build_inference_config(model_tag: Optional[str], overrides: Any) -> Dict[str, str]:
        _, tag_effort = model_hub.resolve_tag(model_tag)
        effort = (overrides.get("effort") if isinstance(overrides, dict) else None) or tag_effort or "medium"
        
        valid = model_hub.supported_levels(model_tag)
        if effort not in valid:
            effort = "high" if effort == "xhigh" else ("medium" if effort == "high" else (list(valid)[0] if valid else "medium"))
        return {"effort": effort, "summary": "auto"}

    @classmethod
    async def execute_upstream(cls, data: Dict[str, Any], sid: str, client: httpx.AsyncClient) -> Tuple[httpx.Response, str]:
        for attempt in range(3):
            identity = account_store.lease_account(sid)
            if not identity:
                count = len(account_store.peek_pool())
                detail = "Account pool is empty. Please login first." if count == 0 else "All accounts are in cooldown/error."
                raise HTTPException(status_code=429, detail=detail)
            
            aid, token = identity
            
            # 构建上游请求头 / Build upstream headers
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "chatgpt-account-id": aid,
                "OpenAI-Beta": "responses=experimental",
                "session_id": sid
            }
            
            safe_headers = {k: (v[:10] + "..." if k == "Authorization" else v) for k, v in headers.items()}
            log_payload = {"url": GATEWAY_UPSTREAM, "headers": safe_headers, "body": data}
            logger.info(f"UPSTREAM REQUEST [Account: {aid}]:\n{json.dumps(log_payload, indent=2, ensure_ascii=False)}")

            try:
                resp = await client.post(GATEWAY_UPSTREAM, headers=headers, json=data, timeout=None)
                logger.info(f"UPSTREAM RESPONSE STATUS: {resp.status_code}")
                
                if resp.status_code == 200: return resp, aid
                
                logger.error(f"UPSTREAM FAILURE: {resp.status_code} - {resp.text}")
                if resp.status_code in (401, 403, 429):
                    # 增加 401，让失效的 Token 也能自动触发冷却/切换
                    account_store.report_fault(aid, f"E{resp.status_code}")
                    continue
                raise HTTPException(status_code=resp.status_code, detail=f"Backend Failure: {resp.status_code}")
            except Exception as e:
                logger.error(f"UPSTREAM EXCEPTION: {str(e)}")
                account_store.report_fault(aid, str(e))
                continue
        raise HTTPException(status_code=429, detail="Critical Failure")

    @classmethod
    def transform_request(cls, body: Dict[str, Any], sid_header: str) -> Dict[str, Any]:
        """
        Transform an OpenAI Chat Completions request body into the upstream Responses API format.
        将 OpenAI Chat Completions 请求体转换为上游 Responses API 格式。
        """
        req_m = body.get("model")
        target_model = model_hub.map_target(req_m)
        inputs = CodecRegistry.ingest_messages(body.get("messages", []))
        policy = cls.resolve_instructions(target_model)
        sid = session_manager.fetch_context(policy, inputs, sid_header)
        
        # 构建响应负载 / Build response payload
        payload = {
            "model": target_model,
            "instructions": policy,
            "input": inputs,
            "tools": CodecRegistry.translate_tools(body.get("tools")),
            "tool_choice": body.get("tool_choice", "auto"),
            "parallel_tool_calls": bool(body.get("parallel_tool_calls", False)),
            "store": False,
            "stream": True,
            "prompt_cache_key": sid,
            "include": ["reasoning.encrypted_content"]
        }
        
        # 处理推理参数
        r_param = cls.build_inference_config(req_m, body.get("reasoning"))
        if r_param:
            payload["reasoning"] = r_param
            
        return {"data": payload, "sid": sid, "model_id": req_m or target_model}

orchestrator = Orchestrator()
