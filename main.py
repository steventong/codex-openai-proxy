"""
Main Entry Service - Gateway and Administrative Portal.
"""
import os
import time
import json
import logging
import secrets
import hashlib
import base64
import urllib.parse
import traceback
from logging.handlers import TimedRotatingFileHandler
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import pydantic

# Boot log
LOG_ROOT = os.path.join(os.getenv("PROXY_DATA_DIR", "./data"), "logs")
os.makedirs(LOG_ROOT, exist_ok=True)
for h in logging.root.handlers[:]: logging.root.removeHandler(h)
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
fh = TimedRotatingFileHandler(os.path.join(LOG_ROOT, "gateway.log"), when="midnight", backupCount=30)
fh.setFormatter(fmt)
ch = logging.StreamHandler()
ch.setFormatter(fmt)
logging.basicConfig(level=logging.INFO, handlers=[fh, ch])

from identity import account_store
from settings import KEY_CLIENT_ID, AUTH_ROOT
from engine.catalog import model_hub
from engine.protocol import CodecRegistry
from engine.history import session_manager
from engine.bridge import FlowAdapter
from gateway import orchestrator

logger = logging.getLogger("ProxyApp")

# 对于官方 Client ID，必须使用此固定回调地址
FIXED_REDIRECT_URI = "http://localhost:1455/auth/callback"

app = FastAPI(title="Backend Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- Core Gateway Endpoints ---

@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": m, "object": "model"} for m in model_hub.available_ids(True)]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
        sid_header = request.headers.get("x-session-id", "") or request.headers.get("session_id", "")
        
        ctx = orchestrator.transform_request(body, sid_header)
        client = httpx.AsyncClient()
        resp, _ = await orchestrator.execute_upstream(ctx["data"], ctx["sid"], client)
        
        ts = int(time.time())
        meta = {
            "model": ctx["model_id"], "created": ts, 
            "include_usage": bool(body.get("stream_options",{}).get("include_usage")), 
            "reasoning_compat": "think-tags"
        }

        if bool(body.get("stream", False)):
            async def stream_output():
                try:
                    async for chunk in FlowAdapter.stream_response(resp, meta): yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()
            return StreamingResponse(stream_output(), media_type="text/event-stream")
        else:
            try:
                result = await FlowAdapter.sync_response(resp, meta)
                return JSONResponse(result)
            finally:
                await resp.aclose()
                await client.aclose()
    except HTTPException as he:
        # 直接抛出 FastAPI 异常，避免变成 500
        raise he
    except Exception as e:
        logger.error(f"Chat completion error: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse({"error": {"message": str(e)}}, status_code=500)


@app.post("/v1/completions")
async def text_completions(request: Request):
    try:
        body = await request.json()
        prompt = body.get("prompt", "")
        chat_body = {
            "model": body.get("model"),
            "messages": [{"role": "user", "content": "".join(prompt) if isinstance(prompt, list) else prompt}],
            "stream": body.get("stream", False),
            "reasoning": body.get("reasoning")
        }
        ctx = orchestrator.transform_request(chat_body, request.headers.get("x-session-id", ""))
        client = httpx.AsyncClient()
        resp, _ = await orchestrator.execute_upstream(ctx["data"], ctx["sid"], client)
        
        ts = int(time.time())
        if bool(body.get("stream", False)):
            async def stream_output():
                try:
                    async for chunk in FlowAdapter.stream_response(resp, {"model": ctx["model_id"], "created": ts}): yield chunk
                finally:
                    await resp.aclose()
                    await client.aclose()
            return StreamingResponse(stream_output(), media_type="text/event-stream")
        else:
            try:
                result = await FlowAdapter.sync_response(resp, {"model": ctx["model_id"], "created": ts})
                return JSONResponse(result)
            finally:
                await resp.aclose()
                await client.aclose()
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Completions error: {str(e)}")
        return JSONResponse({"error": {"message": str(e)}}, status_code=500)


@app.post("/v1/responses")
async def direct_responses(request: Request):
    try:
        body = await request.json()
        sid_header = request.headers.get("x-session-id", "")
        
        model_id = body.get("model")
        backend_model = model_hub.map_target(model_id)
        
        normalized = dict(body)
        normalized["model"] = backend_model
        if "instructions" not in normalized:
            normalized["instructions"] = orchestrator.resolve_instructions(backend_model)
        
        r_val = normalized.get("reasoning") or model_hub.resolve_tag(model_id)[1]
        normalized["reasoning"] = orchestrator.build_inference_config(model_id, r_val)
        
        inc = normalized.get("include") or []
        if "reasoning.encrypted_content" not in inc: inc.append("reasoning.encrypted_content")
        normalized["include"] = inc
        
        sid = session_manager.fetch_context(normalized["instructions"], [], sid_header)
        normalized["prompt_cache_key"] = sid
        normalized["stream"] = True
        
        client = httpx.AsyncClient()
        resp, _ = await orchestrator.execute_upstream(normalized, sid, client)
        
        if bool(body.get("stream", False)):
            async def stream_raw():
                try:
                    async for kind, data in FlowAdapter._read_stream(resp):
                        if kind == "[DONE]": yield b"data: [DONE]\n\n"
                        else:
                            session_manager.track_event(sid, data)
                            yield (f"data: {json.dumps(data, ensure_ascii=False)}\n\n").encode("utf-8")
                finally:
                    await resp.aclose()
                    await client.aclose()
            return StreamingResponse(stream_raw(), media_type="text/event-stream")
        else:
            try:
                final_obj, err_obj = None, None
                async for kind, data in FlowAdapter._read_stream(resp):
                    if kind == "[DONE]": break
                    session_manager.track_event(sid, data)
                    if data.get("event") == "response.completed": final_obj = data.get("response")
                    elif data.get("event") == "response.failed": err_obj = data
                if err_obj: return JSONResponse(err_obj, status_code=502)
                return JSONResponse(final_obj)
            finally:
                await resp.aclose()
                await client.aclose()
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Responses error: {str(e)}")
        return JSONResponse({"error": {"message": str(e)}}, status_code=500)


@app.get("/health")
async def health_check():
    return {"status": "operational", "sessions": session_manager.cleanup_expired()}


# --- Administrative & OAuth ---

class AccountReq(pydantic.BaseModel):
    account_id: str
    access_token: str
    refresh_token: str
    id_token: Optional[str] = ""

oauth_states = {}

def create_pkce():
    cv = secrets.token_hex(64)
    ch = base64.urlsafe_b64encode(hashlib.sha256(cv.encode()).digest()).rstrip(b"=").decode()
    return cv, ch

@app.get("/admin", response_class=HTMLResponse)
async def admin_ui():
    try:
        with open("admin.html", "r") as f: return f.read()
    except: return "<h1>Portal Unavailable</h1>"

@app.get("/api/auth/login")
async def oauth_login():
    cv, ch = create_pkce()
    state = secrets.token_hex(32)
    oauth_states[state] = cv
    params = {
        "response_type": "code", "client_id": KEY_CLIENT_ID,
        "redirect_uri": FIXED_REDIRECT_URI, "scope": "openid profile email offline_access",
        "code_challenge": ch, "code_challenge_method": "S256", "state": state,
    }
    return {"url": f"{AUTH_ROOT}/oauth/authorize?" + urllib.parse.urlencode(params)}

@app.get("/auth/callback")
async def oauth_callback(code: str, state: str):
    try:
        cv = oauth_states.pop(state, None)
        if not cv: raise HTTPException(status_code=400, detail="Invalid session state")
        
        data = {
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": FIXED_REDIRECT_URI, "client_id": KEY_CLIENT_ID, "code_verifier": cv
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{AUTH_ROOT}/oauth/token", data=data)
            if r.status_code != 200:
                logger.error(f"OAuth exchange failed: {r.text}")
                return HTMLResponse(f"<h1>Auth Failed</h1><p>{r.text}</p>", status_code=400)
            
            p = r.json()
            id_token = p.get("id_token", "")
            claims = CodecRegistry.parse_claims(id_token) or {}
            
            auth_info = claims.get("https://api.openai.com/auth", {})
            aid = auth_info.get("chatgpt_account_id") if isinstance(auth_info, dict) else None
            if not aid:
                aid = claims.get("email") or f"user_{secrets.token_hex(4)}"
            
            account_store.register_account(aid, {
                "access_token": p.get("access_token"), "refresh_token": p.get("refresh_token"),
                "id_token": id_token, "last_refresh": time.time()
            })
            
            logger.info(f"Account authenticated: {aid}")
            return HTMLResponse("""<script>
                if(window.opener) window.opener.postMessage('oauth_success','*');
                alert('Login successful!'); window.close();
            </script><h1>Authentication Success</h1>""")
    except Exception as e:
        logger.error(f"Callback error: {str(e)}\n{traceback.format_exc()}")
        return HTMLResponse(f"<h1>Internal Server Error</h1><pre>{str(e)}</pre>", status_code=500)

@app.get("/api/accounts")
async def list_accounts():
    return {"accounts": account_store.peek_pool()}

@app.post("/api/accounts")
async def add_account(req: AccountReq):
    account_store.register_account(req.account_id, {
        "access_token": req.access_token, "refresh_token": req.refresh_token, "id_token": req.id_token,
        "last_refresh": time.time()
    })
    return {"status": "success"}

@app.delete("/api/accounts/{aid}")
async def delete_account(aid: str):
    account_store.unregister_account(aid)
    return {"status": "success"}

@app.post("/api/accounts/{aid}/refresh")
async def refresh_account(aid: str):
    if account_store.refresh_session(aid): return {"status": "success"}
    raise HTTPException(status_code=400, detail="Refresh failed")

@app.get("/api/logs")
async def get_logs(lines: int = 150):
    import collections
    try:
        with open(os.path.join(LOG_ROOT, "gateway.log"), "r") as f:
            return {"logs": "".join(collections.deque(f, lines))}
    except: return {"logs": "No logs."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=1455)
