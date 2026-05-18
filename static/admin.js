/**
 * Codex Proxy Administrative Console - Interactive Logics
 * Codex 代理管理控制台 - 交互脚本
 */

const API_BASE = '/api/accounts';
const API_LOGS = '/api/logs';

let localLogs = ""; // Keep a local cache of logs
let autoRefreshInterval = null;
let accountsData = {}; // Cache of current accounts to support live timer update

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '';
    if (type === 'success') {
        icon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--accent-success);"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    } else if (type === 'error') {
        icon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--accent-danger);"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`;
    } else {
        icon = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--accent-warning);"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
    }
    
    toast.innerHTML = `${icon} <span>${message}</span>`;
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Formats relative time
function formatRelativeTime(secondsAgo) {
    if (secondsAgo < 5) return 'Just now';
    if (secondsAgo < 60) return `${Math.floor(secondsAgo)}s ago`;
    const minutes = secondsAgo / 60;
    if (minutes < 60) return `${Math.floor(minutes)}m ago`;
    const hours = minutes / 60;
    if (hours < 24) return `${Math.floor(hours)}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
}

// Formats absolute time
function formatAbsoluteTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// Formats precise timestamp for history items
function formatHistoryTime(timestamp) {
    const date = new Date(timestamp * 1000);
    return `${date.getMonth()+1}/${date.getDate()} ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
}

// Periodic timer updates for live relative time and next ETA
function updateTimers() {
    const now = Date.now() / 1000;
    
    for (const [aid, acc] of Object.entries(accountsData)) {
        // Update Last Refresh
        const lastRefreshSpan = document.getElementById(`last-refresh-${aid.replace(/[^a-zA-Z0-9]/g, '_')}`);
        if (lastRefreshSpan && acc.last_refresh) {
            const elapsed = now - acc.last_refresh;
            lastRefreshSpan.innerText = formatRelativeTime(elapsed >= 0 ? elapsed : 0);
        }

        // Update Next ETA
        const etaSpan = document.getElementById(`eta-${aid.replace(/[^a-zA-Z0-9]/g, '_')}`);
        if (etaSpan && (acc.next_refresh_at || acc.last_refresh)) {
            const etaTime = acc.next_refresh_at || (acc.last_refresh + 2700);
            const remaining = etaTime - now;
            
            if (acc.status === 'cooldown') {
                // For cooldown accounts, auto refresh daemon won't refresh it, but it shows recovery ETA instead.
                const recoveryRemaining = 900 - (now - (acc.last_error_time || 0));
                if (recoveryRemaining > 0) {
                    const m = Math.floor(recoveryRemaining / 60);
                    const s = Math.floor(recoveryRemaining % 60);
                    etaSpan.innerText = `Recover in ${m}m ${s}s`;
                    etaSpan.style.color = 'var(--accent-danger)';
                } else {
                    etaSpan.innerText = 'Pending Recovery';
                    etaSpan.style.color = 'var(--accent-warning)';
                }
            } else {
                if (remaining > 0) {
                    const m = Math.floor(remaining / 60);
                    const s = Math.floor(remaining % 60);
                    etaSpan.innerText = `in ${m}m ${s}s`;
                    etaSpan.style.color = 'var(--text-main)';
                } else {
                    etaSpan.innerText = 'Due now';
                    etaSpan.style.color = 'var(--accent-warning)';
                }
            }
        }
    }
}

async function fetchAccounts() {
    document.getElementById('pool-loader').style.display = 'block';
    try {
        const res = await fetch(API_BASE);
        const data = await res.json();
        document.getElementById('session-counter').innerText = data.session_count || 0;
        
        accountsData = data.accounts || {};
        renderAccounts(accountsData);
    } catch (err) {
        showToast('Failed to load accounts from pool', 'error');
    } finally {
        document.getElementById('pool-loader').style.display = 'none';
    }
}

// Toggles history section
function toggleHistory(aidSafe) {
    const container = document.getElementById(`history-container-${aidSafe}`);
    const btn = document.getElementById(`history-btn-${aidSafe}`);
    const isExpanded = container.classList.toggle('expanded');
    
    if (isExpanded) {
        btn.innerHTML = `Hide History <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"></polyline></svg>`;
    } else {
        btn.innerHTML = `View History <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>`;
    }
}

function renderAccounts(accounts) {
    const list = document.getElementById('account-list');
    list.innerHTML = '';
    
    if (Object.keys(accounts).length === 0) {
        list.innerHTML = `
            <div class="empty-placeholder" style="grid-column: 1 / -1;">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="color: var(--text-muted); margin-bottom: 1rem;">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                    <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
                <p style="font-weight: 500; font-size: 1rem; color: var(--text-light); margin-bottom: 0.5rem;">No Accounts Registered</p>
                <p style="font-size: 0.85rem;">Click "Connect Account" at the top to complete Auth0 authorization.</p>
            </div>
        `;
        return;
    }

    const now = Date.now() / 1000;

    for (const [aid, acc] of Object.entries(accounts)) {
        const isCooldown = acc.status === 'cooldown';
        const statusClass = isCooldown ? 'pulse-cooldown' : 'pulse-active';
        const statusTextClass = isCooldown ? 'text-cooldown' : 'text-active';
        const cardClass = isCooldown ? 'card-cooldown' : 'card-active';
        
        const errReason = acc.last_error_reason || 'None';
        const errCount = acc.error_count || 0;
        
        // Safe element ID to avoid broken characters
        const aidSafe = aid.replace(/[^a-zA-Z0-9]/g, '_');
        
        // Format relative time on load
        const lastRefreshElapsed = now - (acc.last_refresh || now);
        const lastRefreshText = formatRelativeTime(lastRefreshElapsed >= 0 ? lastRefreshElapsed : 0);
        
        // Render refresh history timeline
        let historyHTML = '';
        const historyList = acc.refresh_history || [];
        
        if (historyList.length === 0) {
            historyHTML = `<div style="color: var(--text-muted); font-size: 0.75rem; text-align: center; padding: 0.5rem 0;">No history recorded</div>`;
        } else {
            // Sort descending by time
            const sortedHistory = [...historyList].sort((a, b) => b.time - a.time);
            sortedHistory.forEach(item => {
                const isSuccess = item.status === 'success';
                const dotClass = isSuccess ? 'indicator-success' : 'indicator-failed';
                const actionName = (item.action || 'refresh').toUpperCase();
                const timeStr = formatHistoryTime(item.time);
                
                historyHTML += `
                    <div class="timeline-item">
                        <div class="timeline-indicator ${dotClass}"></div>
                        <div class="timeline-info">
                            <div class="timeline-meta">
                                <strong style="color: ${isSuccess ? 'var(--accent-success)' : 'var(--accent-danger)'}">${actionName}</strong>
                                <span>${timeStr}</span>
                            </div>
                            <div class="timeline-msg">${item.message || ''}</div>
                        </div>
                    </div>
                `;
            });
        }

        const card = document.createElement('div');
        card.className = `account-card ${cardClass}`;
        card.innerHTML = `
            <div class="acc-header">
                <div class="acc-info" title="${aid}">
                    <div class="acc-avatar">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                    </div>
                    <span class="acc-id">${aid}</span>
                </div>
                <div class="status-badge-container">
                    <span class="pulse-dot ${statusClass}"></span>
                    <span class="status-text ${statusTextClass}">${acc.status}</span>
                </div>
            </div>
            
            <div class="acc-details">
                <div class="detail-row">
                    <span class="detail-label">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        Last Synced
                    </span>
                    <span class="detail-value" id="last-refresh-${aidSafe}">${lastRefreshText}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-label">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
                        Next Auto Refresh
                    </span>
                    <span class="detail-value" id="eta-${aidSafe}" style="font-weight: 600;">Calculating...</span>
                </div>
                ${errCount > 0 || isCooldown ? `
                <div class="detail-row" style="border-top: 1px dashed rgba(255,255,255,0.04); padding-top: 0.4rem; margin-top: 0.2rem;">
                    <span class="detail-label" style="color: var(--accent-danger);">Errors (${errCount})</span>
                    <span class="detail-value error-msg" title="${errReason}">${errReason}</span>
                </div>
                ` : ''}
            </div>

            <!-- Collapsible History Timeline -->
            <div>
                <button class="history-btn" id="history-btn-${aidSafe}" onclick="toggleHistory('${aidSafe}')">
                    View History 
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>
                <div class="history-container" id="history-container-${aidSafe}">
                    ${historyHTML}
                </div>
            </div>

            <div class="card-actions">
                <button type="button" class="btn btn-secondary btn-sm" onclick="refreshAccount('${aid}')" title="Manually Sync Access Token">
                    Sync Token
                </button>
                <button type="button" class="btn btn-danger btn-sm" onclick="deleteAccount('${aid}')" title="Permanently unregister account">
                    Remove
                </button>
            </div>
        `;
        card.id = `account-card-${aidSafe}`;
        list.appendChild(card);
    }
    
    // Perform initial timer tick
    updateTimers();
}

function loginWithChatGPT() {
    showToast('Initializing secure Auth0 handshake...', 'info');
    fetch('/api/auth/login').then(r => r.json()).then(data => {
        const width = 520;
        const height = 720;
        const left = (window.screen.width / 2) - (width / 2);
        const top = (window.screen.height / 2) - (height / 2);
        window.open(data.url, 'ChatGPT Login', `width=${width},height=${height},top=${top},left=${left},status=no,resizable=yes`);
    }).catch(err => {
        showToast('Failed to initialize authorization flow', 'error');
    });
}

window.addEventListener('message', (event) => {
    if (event.data === 'oauth_success') {
        showToast('ChatGPT OAuth authenticated & added successfully!', 'success');
        fetchAccounts();
    }
});

async function deleteAccount(aid) {
    if (!confirm(`Are you absolutely sure you want to remove account:\n"${aid}"?\nThis cannot be undone.`)) return;
    
    try {
        const res = await fetch(`${API_BASE}/${aid}`, { method: 'DELETE' });
        if (res.ok) {
            showToast('Account removed from proxy pool', 'success');
            fetchAccounts();
        } else {
            showToast('Failed to remove account from upstream', 'error');
        }
    } catch (err) {
        showToast('Network error during operation', 'error');
    }
}

async function refreshAccount(aid) {
    try {
        showToast(`Force refreshing session credentials for ${aid}...`, 'info');
        const res = await fetch(`${API_BASE}/${aid}/refresh`, { method: 'POST' });
        if (res.ok) {
            showToast('Token refreshed & session validated successfully!', 'success');
            fetchAccounts();
        } else {
            showToast('Sync failed. Auth0 session may have expired.', 'error');
        }
    } catch (err) {
        showToast('Network connectivity error', 'error');
    }
}

// Live Log Colorizer & Renderer
function renderLogs() {
    const content = document.getElementById('log-content');
    const searchVal = document.getElementById('log-search').value.trim().toLowerCase();
    
    if (!localLogs) {
        content.innerHTML = `<span style="color: var(--text-muted)">Empty logs.</span>`;
        return;
    }

    const lines = localLogs.split('\n');
    let outputHTML = "";
    let matchedCount = 0;

    lines.forEach(line => {
        if (!line) return;
        
        // Search filter (skip lines not matching search filter if search exists)
        if (searchVal && !line.toLowerCase().includes(searchVal)) {
            return;
        }
        
        matchedCount++;
        let parsedLine = line;

        // Escape HTML tags to prevent broken injection
        parsedLine = parsedLine
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Highlighting specific log severity markers
        parsedLine = parsedLine
            .replace(/\[INFO\]/g, `<span class="log-info">[INFO]</span>`)
            .replace(/\[WARNING\]/g, `<span class="log-warning">[WARNING]</span>`)
            .replace(/\[ERROR\]/g, `<span class="log-error">[ERROR]</span>`)
            .replace(/\[CRITICAL\]/g, `<span class="log-critical">[CRITICAL]</span>`);

        // Highlighting timestamps (e.g. 2026-05-17 08:05:09,123)
        parsedLine = parsedLine.replace(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?)/, `<span class="log-time">$1</span>`);

        // Highlighting identity and proxy classes (e.g. IdentityVault, ProxyApp)
        parsedLine = parsedLine.replace(/(IdentityVault|ProxyApp|GatewayServer|Orchestrator|FlowAdapter):/g, `<span class="log-module">$1</span>:`);

        // Highlight user search keyword if applicable
        if (searchVal) {
            const regex = new RegExp(`(${searchVal.replace(/[-\/\\^$*+?.()|[\]{}]/g, '\\$&')})`, 'gi');
            parsedLine = parsedLine.replace(regex, `<span class="log-highlight">$1</span>`);
        }

        outputHTML += `<span class="log-line">${parsedLine}</span>`;
    });

    if (matchedCount === 0 && searchVal) {
        content.innerHTML = `<span style="color: var(--text-muted)">No log lines match filter criteria "${searchVal}".</span>`;
    } else {
        content.innerHTML = outputHTML;
    }

    // Auto-scroll to bottom if checked
    if (document.getElementById('log-auto-scroll').checked) {
        content.scrollTop = content.scrollHeight;
    }
}

async function fetchLogs() {
    const count = document.getElementById('log-lines').value;
    try {
        const res = await fetch(`${API_LOGS}?lines=${count}`);
        const data = await res.json();
        localLogs = data.logs || "";
        renderLogs();
    } catch (err) {
        document.getElementById('log-content').innerHTML = `<span style="color: var(--accent-danger)">Failed to fetch remote log stream.</span>`;
    }
}

function clearLogs() {
    localLogs = "";
    renderLogs();
    showToast('Console output cleared locally', 'info');
}

function toggleAutoRefresh(enabled) {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
    
    if (enabled) {
        autoRefreshInterval = setInterval(fetchLogs, 3000);
        showToast('Automatic log polling enabled (3s)', 'success');
    } else {
        showToast('Automatic log polling paused', 'warning');
    }
}

// Initialization
fetchAccounts();

// Initial manual log fetch
fetchLogs();

// 3-second live updates for terminal logs
autoRefreshInterval = setInterval(fetchLogs, 3000);

// 1-second live ticks for countdown timers and relative times
setInterval(updateTimers, 1000);

// Periodically refresh pool status every 20 seconds
setInterval(fetchAccounts, 20000);
