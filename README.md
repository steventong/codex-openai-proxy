# Codex OpenAI Proxy

A lightweight, self-hosted FastAPI proxy that exposes a standard OpenAI-compatible API (`/v1/chat/completions`) while managing multiple accounts, automatic token refresh, and session stickiness behind the scenes.

> **Disclaimer:** This project is not affiliated with or endorsed by OpenAI. Use it responsibly and in accordance with OpenAI's Terms of Service.

---

## ✨ Features

| Feature | Description |
|---|---|
| **Multi-account Pool** | Register multiple accounts; the proxy auto-rotates on `429` / `403` errors and places failing accounts in a cooldown queue. |
| **Sticky Sessions** | Requests bearing the same `user` field or `x-session-id` header are pinned to the same account, maximising cache-hit rates. |
| **Automatic Token Refresh** | A background daemon silently refreshes tokens every ~45 minutes, keeping the proxy alive 24/7 without manual intervention. |
| **OAuth Login Flow** | Web admin panel supports one-click login via the official Auth0 PKCE flow — no manual token copying needed. |
| **Reasoning Compat** | Translates private `reasoning` / `summary` stream events into standard `<think>…</think>` tags understood by most clients. |
| **OpenAI-compatible API** | Drop-in replacement for `https://api.openai.com/v1`. Point any OpenAI SDK or tool at `http://localhost:8000/v1`. |
| **Glassmorphism Admin UI** | Beautiful dark-mode web dashboard for managing accounts, monitoring status, and viewing live logs. |
| **Docker-ready** | Single `docker compose up -d` to deploy. Cross-compiles to `linux/amd64` on Apple Silicon. |

---

## 🚀 Quick Start

### Option 1 — Local (Python)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Register your first account (interactive)
python cli.py add

# 3. Start the proxy
python main.py
# → Listening on http://0.0.0.0:8000
```

### Option 2 — Docker Compose

```bash
docker compose up -d
```

The `data/` directory is mounted as a volume, so your account pool and session cache persist across container restarts.

---

## 🖥️ Admin Dashboard

Navigate to **http://localhost:8000/admin** after starting the service.

From the dashboard you can:
- **Login** new accounts via the official OAuth flow (no tokens to copy)
- **Monitor** each account's status (`active` / `cooldown`), error count, and last error reason
- **Sync Token** — manually trigger a token refresh for any account
- **Remove** accounts from the pool
- **View live logs** in a modal log viewer

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and adjust as needed:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| `GATEWAY_CLIENT_ID` | *(built-in)* | OAuth client ID |
| `GATEWAY_AUTH_ROOT` | `https://auth.openai.com` | OAuth authorization root |
| `PROXY_DATA_DIR` | `./data` | Path for accounts, sessions, and logs |

---

## 🔌 API Reference

### POST `/v1/chat/completions`

Drop-in replacement for the OpenAI Chat Completions endpoint.

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": true
  }'
```

**Session pinning** — pass `user` in the request body or `x-session-id` header to activate sticky session routing:

```json
{
  "model": "gpt-5",
  "messages": [...],
  "user": "my-unique-session-id"
}
```

### GET `/v1/models`

Returns the list of supported model IDs.

### POST `/v1/completions`

Legacy completions endpoint, internally forwarded as a chat request.

### POST `/v1/responses`

Pass-through to the upstream Responses API (streaming raw events).

### GET `/health`

Liveness check. Returns active session count.

---

## 📦 CLI Reference

```bash
# Add an account manually
python cli.py add

# List all accounts and their status
python cli.py ls

# Remove an account
python cli.py rm <account_id>

# Force-refresh a token
python cli.py refresh <account_id>
```

---

## 📁 Project Structure

```
codex-openai-proxy/
├── main.py           # FastAPI application — routes & OAuth flow
├── gateway.py        # Request orchestration — upstream retry logic
├── identity.py       # Account pool — storage, rotation, token refresh
├── settings.py       # Global configuration loader
├── cli.py            # CLI management tool
├── admin.html        # Web admin dashboard (single-file SPA)
├── engine/
│   ├── bridge.py     # Stream adapter — translates upstream SSE to OpenAI format
│   ├── catalog.py    # Model registry — aliases, reasoning bounds, backend IDs
│   ├── history.py    # Session tracker — context hashing & event tracking
│   └── protocol.py   # Message codec — converts Chat format ↔ Responses API format
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 🔒 Security Notes

- **Account tokens are stored locally** in `data/accounts.json`. This file is excluded from git via `.gitignore`. Keep it safe.
- The admin panel has **no built-in authentication**. If you expose port `8000` publicly, add a reverse proxy (e.g., Nginx basic auth) in front of `/admin` and `/api/*`.
- The OAuth callback is bound to `http://localhost:1455/auth/callback`, which must be accessible from the machine running the proxy when performing the login flow.

---

## 🤝 Contributing

Contributions are welcome! Please open an issue first to discuss major changes.

1. Fork the repository
2. Create your branch: `git checkout -b feat/my-feature`
3. Commit your changes: `git commit -m "feat: add my feature"`
4. Push and open a Pull Request

---

## 📄 License

[MIT](LICENSE)
