# Codex OpenAI Proxy

这是一个基于 FastAPI 实现的 OpenAI 协议兼容代理层，专为多账号并发轮询、状态隔离和自动容错而设计，旨在提升在多账号并发请求场景下的稳定性。

## 核心特性完整列表
- 🚀 **多账号池与轮询容错机制**：遇到 `429 Too Many Requests`、`403 Forbidden` 或限流错误时，系统自动捕捉并标记账号进入冷却期，同时无缝在单次请求内重新分配健康账号完成重试，保障请求 100% 高可用。
- 💾 **会话黏性缓存 (Sticky Session)**：为提升缓存命中率，代理根据请求的 `user` 或 `x-session-id` 会话标志，在本地持久化创建 `sessions.json` 临时映射记录。确保同一个会话固定走同一个账号，只有当配额用尽时才解绑分发新渠道。
- 🔐 **多账号 OAuth 授权登录与存储**：支持录入多组 `access_token` 和 `refresh_token`。提供完整的存取逻辑，保障令牌安全加载。
- 🔄 **自动 Token 续期守护**：内置后台 Daemon 守护线程，全自动定期轮询（每 15 分钟），在 Token 过期前静默调用 OpenAI OAuth 接口进行刷新续期，适合长期无人值守的挂机运行。
- 🖥️ **精美的 Web 管理后台**：自带 **Glassmorphism Dark Mode**（高级暗黑玻璃拟物化）现代化 UI 界面，提供新增账号、可视化监控池内账号状态（错误数、冷却状态）、手动强制 Token 刷新等一站式管理。
- 🧠 **推理过程转换兼容**：完整拦截上方的数据流，将模型返回的私有 Reasoning / Summary 字段标准化转化为兼容各类主流客户端的 `<think>` 标签流式输出。
- 🐳 **Docker x86 跨平台部署**：完美支持在苹果 M 芯片环境下一键交叉编译并输出 `linux/amd64` 原生镜像，随时可无缝迁移至标准 x86_64 服务器。
- 🔌 **标准 OpenAI v1 接口**：对外提供完全符合 OpenAI 规范的 `/v1/chat/completions` API。

## 快速开始

### 1. 本地运行

```bash
cd codex-openai-proxy
pip install -r requirements.txt

# 添加你的第一个账号
python cli.py add

# 启动服务
python main.py
```

### 2. Docker 部署

```bash
cd codex-openai-proxy
# 构建镜像
docker build -t codex-openai-proxy .

# 运行容器 (挂载 data 目录持久化账号池和 Session 缓存)
docker compose up -d
```

## 控制台管理方式 (Web UI & CLI)

本系统提供了两种方式来管理和监控账号健康状态。

### 1. Web 拟物化管理后台 (推荐)
在启动服务后，直接在浏览器中访问：
👉 **http://127.0.0.1:8000/admin**
在这里你可以：
- 使用现代化的界面无刷新添加新账号。
- 查看每一个账号的状态是 Active 还是 Cooldown。
- 实时追踪并查看导致账号被封禁或限流的具体 HTTP 报错日志。
- 一键完成账号删除和 Token 续期同步。

### 2. 命令行面板 (CLI)
当你使用纯 Server 环境没有暴露 8000 端口以外的环境时，可以直接使用命令：

```bash
# 查看所有账号状态和限流情况
python cli.py ls

# 结果示例：
# Account ID                     | Status     | Errors | Last Error
# ---------------------------------------------------------------------------
# user1@openai.com               | active     | 0      | -
# user2@openai.com               | cooldown   | 1      | HTTP 429

# 添加账号
python cli.py add

# 删除挂掉的账号
python cli.py rm user2@openai.com

# 手动强制刷新某个账号的 Token
python cli.py refresh user1@openai.com
```

## 客户端请求示例

代理对外提供标准的 `/v1/chat/completions` API：

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "codex",
    "messages": [{"role": "user", "content": "帮我搜索最新的 Python 3.13 特性"}],
    "stream": true,
    "user": "session_wanglin_001" 
  }'
```
> **注意**：传入 `user` 字段（或其他客户端的 `x-session-id` 头）将激活代理层的会话保持功能，有效利用缓存并避免频繁跨账号横跳。
