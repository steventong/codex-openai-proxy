import json
import os
import time
import threading
import logging
from typing import Dict, Optional, List, Tuple
import requests
from .config import KEY_CLIENT_ID, AUTH_ROOT

logger = logging.getLogger("IdentityVault")

DATA_DIR = os.getenv("PROXY_DATA_DIR", "./data")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

OAUTH_TOKEN_URL = f"{AUTH_ROOT}/oauth/token"
DEFAULT_REFRESH_INTERVAL = 2700


def _compute_next_refresh_at(refreshed_at: float, expires_in: Optional[object] = None) -> float:
    """
    Schedule refresh slightly before token expiry.
    Fall back to 45 minutes when expiry is unavailable or invalid.
    """
    try:
        expires_in_value = int(expires_in) if expires_in is not None else 0
    except (TypeError, ValueError):
        expires_in_value = 0

    if expires_in_value > 300:
        return refreshed_at + max(300, expires_in_value - 300)
    return refreshed_at + DEFAULT_REFRESH_INTERVAL

class AccountPool:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.accounts: Dict[str, dict] = {}
        self.sessions: Dict[str, dict] = {}
        self.lock = threading.Lock()
        self.sync_accounts_from_disk()
        self.sync_sessions_from_disk()
        
        # 启动后台守护线程进行 Token 自动续期
        self.refresh_thread = threading.Thread(target=self._auto_refresh_daemon, daemon=True)
        self.refresh_thread.start()

    def sync_sessions_from_disk(self):
        with self.lock:
            if not os.path.exists(SESSIONS_FILE):
                with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                    json.dump({}, f)
            try:
                with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                    self.sessions = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load sessions: {e}")
                self.sessions = {}

    def flush_sessions_to_disk(self):
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.sessions, f, indent=2)

    def sync_accounts_from_disk(self):
        """
        从磁盘同步并加载所有账号信息，进行数据结构的向下兼容与补全。
        Synchronize and load all accounts from disk, ensuring backward compatibility and field completion.
        """
        with self.lock:
            if not os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, "w") as f:
                    json.dump({}, f)
            try:
                with open(ACCOUNTS_FILE, "r") as f:
                    data = json.load(f)
                    now_time = time.time()
                    # 鲁棒性补全 / Robustness autocompletion
                    for aid, acc in data.items():
                        acc["status"] = "active"
                        if "last_refresh" not in acc: acc["last_refresh"] = now_time
                        if "next_refresh_at" not in acc:
                            acc["next_refresh_at"] = _compute_next_refresh_at(
                                acc.get("last_refresh", now_time),
                                acc.get("expires_in")
                            )
                        if "refresh_history" not in acc:
                            acc["refresh_history"] = [{
                                "time": acc.get("last_refresh", now_time),
                                "status": "success",
                                "action": "sync",
                                "message": "Account synchronized from disk"
                            }]
                    self.accounts = data
            except Exception as e:
                logger.error(f"Failed to load accounts: {e}")
                self.accounts = {}

    def flush_accounts_to_disk(self):
        with self.lock:
            with open(ACCOUNTS_FILE, "w") as f:
                json.dump(self.accounts, f, indent=2)

    def register_account(self, account_id: str, tokens: dict):
        """
        添加或更新一个账号到账号池中，并记录注册历史。
        Add or update an account in the account pool, and record registration history.
        """
        # 补充初始状态 / Set initial fields
        now_time = time.time()
        tokens["status"] = "active"
        tokens["last_refresh"] = now_time
        tokens["next_refresh_at"] = _compute_next_refresh_at(now_time, tokens.get("expires_in"))
        tokens["refresh_history"] = [{
            "time": now_time,
            "status": "success",
            "action": "register",
            "message": "Account registered"
        }]
        with self.lock:
            self.accounts[account_id] = tokens
        self.flush_accounts_to_disk()
        logger.info(f"Account {account_id} added/updated.")

    def unregister_account(self, account_id: str):
        with self.lock:
            if account_id in self.accounts:
                del self.accounts[account_id]
        self.flush_accounts_to_disk()

    def peek_pool(self) -> dict:
        with self.lock:
            return dict(self.accounts)

    def get_session_count(self) -> int:
        with self.lock:
            return len(self.sessions)

    def lease_account(self, session_id: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        获取一个可用的账号，优先根据 session_id 命中缓存。
        返回 (account_id, access_token)
        """
        now = time.time()

        # 1. 检查会话缓存
        if session_id:
            with self.lock:
                cached_data = self.sessions.get(session_id)
                if cached_data:
                    cached_acc_id = cached_data.get("account_id")
                    acc = self.accounts.get(cached_acc_id)
                    if acc:
                        return cached_acc_id, acc.get("access_token")

        # 2. 缓存未命中或缓存账号不可用，选择一个可用账号
        with self.lock:
            account_ids = list(self.accounts.keys())

            if not account_ids:
                logger.warning("No accounts available in pool.")
                return None

            chosen_id = account_ids[0]
            chosen_token = self.accounts[chosen_id].get("access_token")

        # 3. 更新会话映射
        if session_id:
            with self.lock:
                self.sessions[session_id] = {
                    "account_id": chosen_id,
                    "updated_at": now
                }
                self.flush_sessions_to_disk()

        return chosen_id, chosen_token

    def refresh_session(self, account_id: str) -> bool:
        """
        立即刷新单个账号的 Access Token，并记录刷新状态及详细结果至历史记录中。
        Immediately refresh the Access Token of a single account, recording the refresh status and detailed result in history.
        """
        with self.lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return False
            refresh_token = acc.get("refresh_token")
            
        if not refresh_token:
            with self.lock:
                if account_id in self.accounts:
                    history = self.accounts[account_id].setdefault("refresh_history", [])
                    history.append({
                        "time": time.time(),
                        "status": "failed",
                        "action": "refresh",
                        "message": "No refresh token available"
                    })
                    self.accounts[account_id]["refresh_history"] = history[-10:]
            self.flush_accounts_to_disk()
            return False

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": KEY_CLIENT_ID,
            "scope": "openid profile email offline_access",
        }
        try:
            resp = requests.post(
                OAUTH_TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            if resp.status_code < 400:
                data = resp.json()
                now_time = time.time()
                with self.lock:
                    if account_id in self.accounts:
                        self.accounts[account_id]["access_token"] = data.get("access_token", acc.get("access_token"))
                        self.accounts[account_id]["id_token"] = data.get("id_token", acc.get("id_token"))
                        self.accounts[account_id]["refresh_token"] = data.get("refresh_token", refresh_token)
                        self.accounts[account_id]["expires_in"] = data.get("expires_in", acc.get("expires_in"))
                        self.accounts[account_id]["last_refresh"] = now_time
                        self.accounts[account_id]["next_refresh_at"] = _compute_next_refresh_at(
                            now_time,
                            data.get("expires_in", acc.get("expires_in"))
                        )
                        self.accounts[account_id]["status"] = "active"
                        
                        history = self.accounts[account_id].setdefault("refresh_history", [])
                        history.append({
                            "time": now_time,
                            "status": "success",
                            "action": "refresh",
                            "message": "Token refreshed successfully"
                        })
                        self.accounts[account_id]["refresh_history"] = history[-10:]
                self.flush_accounts_to_disk()
                logger.info(f"Successfully refreshed token for {account_id}")
                return True
            else:
                err_msg = f"HTTP {resp.status_code}: {resp.text[:100]}"
                with self.lock:
                    if account_id in self.accounts:
                        history = self.accounts[account_id].setdefault("refresh_history", [])
                        history.append({
                            "time": time.time(),
                            "status": "failed",
                            "action": "refresh",
                            "message": err_msg
                        })
                        self.accounts[account_id]["refresh_history"] = history[-10:]
                self.flush_accounts_to_disk()
                logger.error(f"Refresh failed for {account_id}: {resp.text}")
                return False
        except Exception as e:
            err_msg = str(e)
            with self.lock:
                if account_id in self.accounts:
                    history = self.accounts[account_id].setdefault("refresh_history", [])
                    history.append({
                        "time": time.time(),
                        "status": "failed",
                        "action": "refresh",
                        "message": err_msg
                    })
                    self.accounts[account_id]["refresh_history"] = history[-10:]
            self.flush_accounts_to_disk()
            logger.error(f"Refresh request error for {account_id}: {e}")
            return False

    def _auto_refresh_daemon(self):
        """守护线程：每隔 15 分钟扫描一次，如果有过期风险（如上一次刷新超过 45 分钟），则自动刷新"""
        while True:
            try:
                now = time.time()
                needs_refresh = []
                with self.lock:
                    for aid, acc in self.accounts.items():
                        next_refresh_at = acc.get("next_refresh_at")
                        if next_refresh_at is None:
                            next_refresh_at = _compute_next_refresh_at(
                                acc.get("last_refresh", 0),
                                acc.get("expires_in")
                            )

                        if now >= next_refresh_at:
                            needs_refresh.append(aid)
                
                for aid in needs_refresh:
                    self.refresh_session(aid)
                    time.sleep(2) # 避免请求过于密集
                    
            except Exception as e:
                logger.error(f"Auto refresh daemon error: {e}")
            
            time.sleep(900) # 每 15 分钟执行一次检查

account_store = AccountPool()
