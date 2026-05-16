import json
import os
import time
import threading
import logging
from typing import Dict, Optional, List, Tuple
import requests

logger = logging.getLogger("IdentityVault")

DATA_DIR = os.getenv("PROXY_DATA_DIR", "./data")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID_DEFAULT = "app_EMoamEEZ73f0CkXaXp7hrann"

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
        with self.lock:
            if not os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, "w") as f:
                    json.dump({}, f)
            try:
                with open(ACCOUNTS_FILE, "r") as f:
                    data = json.load(f)
                    # 鲁棒性补全
                    for aid, acc in data.items():
                        if "status" not in acc: acc["status"] = "active"
                        if "error_count" not in acc: acc["error_count"] = 0
                        if "last_error_time" not in acc: acc["last_error_time"] = 0
                    self.accounts = data
            except Exception as e:
                logger.error(f"Failed to load accounts: {e}")
                self.accounts = {}

    def flush_accounts_to_disk(self):
        with self.lock:
            with open(ACCOUNTS_FILE, "w") as f:
                json.dump(self.accounts, f, indent=2)

    def register_account(self, account_id: str, tokens: dict):
        """添加或更新账号"""
        # 补充初始状态
        tokens["status"] = "active"
        tokens["error_count"] = 0
        tokens["last_error_time"] = 0
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

    def report_fault(self, account_id: str, error_type: str):
        """当遇到限流、配额不足时标记账号状态并进入冷却"""
        with self.lock:
            if account_id in self.accounts:
                acc = self.accounts[account_id]
                acc["status"] = "cooldown"
                acc["error_count"] = acc.get("error_count", 0) + 1
                acc["last_error_time"] = time.time()
                acc["last_error_reason"] = error_type
        self.flush_accounts_to_disk()
        logger.warning(f"Account {account_id} marked as cooldown due to {error_type}.")

    def lease_account(self, session_id: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        获取一个可用的账号，优先根据 session_id 命中缓存。
        返回 (account_id, access_token)
        """
        now = time.time()
        
        # 1. 恢复已经过了冷却期（例如15分钟）的账号
        with self.lock:
            for aid, acc in self.accounts.items():
                if acc.get("status") == "cooldown":
                    if now - acc.get("last_error_time", 0) > 900: # 15分钟冷却
                        acc["status"] = "active"
                        acc["error_count"] = 0
                        logger.info(f"Account {aid} recovered from cooldown.")
            
        # 2. 检查会话缓存
        if session_id:
            with self.lock:
                cached_data = self.sessions.get(session_id)
                if cached_data:
                    cached_acc_id = cached_data.get("account_id")
                    acc = self.accounts.get(cached_acc_id)
                    if acc and acc.get("status") == "active":
                        return cached_acc_id, acc.get("access_token")

        # 3. 缓存未命中或缓存账号不可用，轮询分配一个新的 active 账号
        with self.lock:
            active_accounts = [aid for aid, acc in self.accounts.items() if acc.get("status") == "active"]
            cooldown_accounts = [aid for aid, acc in self.accounts.items() if acc.get("status") == "cooldown"]
            
            if not active_accounts:
                logger.warning(f"No active accounts available. (Total: {len(self.accounts)}, Cooldown: {len(cooldown_accounts)})")
                return None
            
            # 简单的排序分配（可以基于上次使用时间做 Round-Robin，这里随机或取第一个）
            # 为了简单，按 error_count 升序，或者直接取第一个
            active_accounts.sort(key=lambda a: self.accounts[a].get("error_count", 0))
            chosen_id = active_accounts[0]
            chosen_token = self.accounts[chosen_id].get("access_token")

        # 4. 更新会话映射
        if session_id:
            with self.lock:
                self.sessions[session_id] = {
                    "account_id": chosen_id,
                    "updated_at": now
                }
                self.flush_sessions_to_disk()

        return chosen_id, chosen_token

    def refresh_session(self, account_id: str) -> bool:
        """立即刷新单个账号"""
        with self.lock:
            acc = self.accounts.get(account_id)
            if not acc:
                return False
            refresh_token = acc.get("refresh_token")
            
        if not refresh_token:
            return False

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID_DEFAULT,
            "scope": "openid profile email offline_access",
        }
        try:
            resp = requests.post(OAUTH_TOKEN_URL, json=payload, timeout=30)
            if resp.status_code < 400:
                data = resp.json()
                with self.lock:
                    if account_id in self.accounts:
                        self.accounts[account_id]["access_token"] = data.get("access_token", acc.get("access_token"))
                        self.accounts[account_id]["id_token"] = data.get("id_token", acc.get("id_token"))
                        self.accounts[account_id]["refresh_token"] = data.get("refresh_token", refresh_token)
                        self.accounts[account_id]["last_refresh"] = time.time()
                        self.accounts[account_id]["status"] = "active"
                        self.accounts[account_id]["error_count"] = 0
                        self.accounts[account_id]["last_error_time"] = 0
                self.flush_accounts_to_disk()
                logger.info(f"Successfully refreshed token for {account_id}")
                return True
            else:
                logger.error(f"Refresh failed for {account_id}: {resp.text}")
                return False
        except Exception as e:
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
                        last_refresh = acc.get("last_refresh", 0)
                        # 如果距离上次刷新超过 45 分钟 (2700 秒)，则续期
                        if now - last_refresh > 2700:
                            needs_refresh.append(aid)
                
                for aid in needs_refresh:
                    self.refresh_session(aid)
                    time.sleep(2) # 避免请求过于密集
                    
            except Exception as e:
                logger.error(f"Auto refresh daemon error: {e}")
            
            time.sleep(900) # 每 15 分钟执行一次检查

account_store = AccountPool()
