# Privacy Protection — FinanceAI

**Version:** 1.0 | **Date:** 2026-05-06

This document describes every measure taken to protect user privacy in FinanceAI. Privacy protection spans identity management, personal data handling, access control, data isolation, secure file serving, audit log hygiene, and data lifecycle management.

---

## Table of Contents

1. [Overview — Complete Privacy Stack](#1-overview--complete-privacy-stack)
2. [PII Detection and Tokenisation](#2-pii-detection-and-tokenisation)
3. [Encrypted PII Token Store](#3-encrypted-pii-token-store)
4. [PII Detokenisation and Output Scanning](#4-pii-detokenisation-and-output-scanning)
5. [Authentication — Passwords and Tokens](#5-authentication--passwords-and-tokens)
6. [Role-Based Access Control (RBAC)](#6-role-based-access-control-rbac)
7. [Per-User Session Isolation](#7-per-user-session-isolation)
8. [Trading History Per-User Isolation](#8-trading-history-per-user-isolation)
9. [Secure File Serving — Path Traversal Guard](#9-secure-file-serving--path-traversal-guard)
10. [Audit Log Privacy](#10-audit-log-privacy)
11. [Data Lifecycle and Retention](#11-data-lifecycle-and-retention)
12. [Known Limitations](#12-known-limitations)
13. [Summary Table](#13-summary-table)

---

## 1. Overview — Complete Privacy Stack

```
┌──────────────────────────────────────────────────────────────┐
│  IDENTITY & ACCESS                                           │
│  bcrypt password hashing → JWT HS256 (8h expiry)           │
│  RBAC: viewer / analyst / admin via roles.yaml              │
│  Per-user session isolation + ownership checks              │
├──────────────────────────────────────────────────────────────┤
│  PII LIFECYCLE                                               │
│                                                             │
│  Input ──► detect ──► tokenise ──► LLM sees [TYPE_N] only  │
│                           │                                 │
│                    Fernet-encrypted SQLite                   │
│                    (AES-128-CBC + HMAC-SHA256)               │
│                    masked values only — raw PII never stored │
│                    90-day TTL → lazy auto-purge              │
│                           │                                 │
│  Output ◄── detokenise ◄──┘  masked display to user        │
│           + rescan for LLM-generated PII                    │
├──────────────────────────────────────────────────────────────┤
│  DATA ISOLATION                                              │
│  trades_{username} in localStorage (per-user namespace)     │
│  Session data scoped by user_id in SQLite                   │
│  DELETE /api/sessions → ownership verified before removal   │
├──────────────────────────────────────────────────────────────┤
│  FILE SYSTEM                                                 │
│  Path traversal guard on /api/downloads/                    │
│  Dotfiles blocked; paths outside output/ return 403        │
│  .pii_key chmod 0600 (owner-read-only)                      │
│  pii_tokens.db git-ignored                                  │
├──────────────────────────────────────────────────────────────┤
│  AUDIT LOGS                                                  │
│  No raw PII in logs (tokenised before LLM boundary)         │
│  No base64 images in logs (stripped at callback level)      │
│  No message text in audit entries                           │
│  90-day rotation → gzip → auto-delete                       │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. PII Detection and Tokenisation

### The Problem

Large language models are trained on internet text and can memorise, echo, or inadvertently expose personal data that appears in prompts. A user who includes their email address in a query ("send the report to john@example.com") could have that email forwarded to the LLM API, logged in API provider infrastructure, or echoed back in the response. Social Security Numbers, credit card numbers, and phone numbers pose even greater risk.

### What We Detect

Five PII types are detected via named-group regular expressions in `guardrails.py`:

```python
_PII_SPECS: list[tuple[str, str]] = [
    ("EMAIL",   r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    ("PHONE",   r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    ("SSN",     r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
    ("CC",      r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ("IP",      r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
]
```

### The Tokenisation Flow

Before every LLM call, detected PII is replaced with an opaque, reversible token. The LLM never receives real personal data:

```
User message:
  "My email is john@example.com — what is AAPL's price?"
           │
           ▼
  tokenize_pii(text)
           │
  ┌────────────────────────────────────────────────┐
  │  Pattern match: john@example.com → EMAIL       │
  │  Token assigned: [EMAIL_0]                     │
  │  Masked value: j***@example.com                │
  │  token_map = { "[EMAIL_0]": "j***@example.com" }│
  └────────────────────────────────────────────────┘
           │
  Text sent to LLM:
  "My email is [EMAIL_0] — what is AAPL's price?"

  token_map stored in encrypted SQLite (pii_store.py)
```

### Masking Rules

Raw PII is **never stored anywhere** — not in the database, not in logs, not in session state. Only the masked representation is persisted:

| Type | Example | Masked form stored |
|---|---|---|
| EMAIL | john.smith@example.com | `j***@example.com` |
| PHONE | +1-555-123-4567 | `***-***-4567` |
| SSN | 123-45-6789 | `***-**-6789` |
| CC | 4111 1111 1111 1111 | `***-**-1111` |
| IP | 192.168.1.1 | `192.***.***。1` |

This design means even if the encrypted database were compromised, only masked values would be recoverable — not the originals.

### Where It Fires

The tokenisation check runs as a `before_model_callback` on the root agent, once per turn. A session-state flag (`guardrail_input_validated`) prevents redundant scanning on sub-agent calls within the same invocation.

---

## 3. Encrypted PII Token Store

### The Problem

Tokenisation must be reversible across multiple LLM calls within a multi-turn session (so the output guardrail can swap tokens back to masked values in the response). The token-to-masked-value map must be stored somewhere — but plaintext session state is visible to all agents and is not encrypted.

### Design

`pii_store.py` implements a purpose-built encrypted store:

```
data/pii_tokens.db   ← SQLite, git-ignored
data/.pii_key        ← Fernet key, chmod 0600, git-ignored

Schema:
  pii_tokens (
    inv_id     TEXT     -- invocation ID (one per LLM call chain)
    token      TEXT     -- e.g. "[EMAIL_0]"
    masked_enc BLOB     -- Fernet ciphertext of "j***@example.com"
    created_at INTEGER  -- Unix timestamp
    PRIMARY KEY (inv_id, token)
  )
```

### Encryption

Every masked value is encrypted with **Fernet** (symmetric authenticated encryption):
- Algorithm: AES-128-CBC + HMAC-SHA256
- Library: `cryptography>=47.0.0`
- Key length: 32 bytes (256-bit)

```
put(inv_id, token_map):
    f = Fernet(key)
    for token, masked in token_map.items():
        ciphertext = f.encrypt(masked.encode())
        INSERT INTO pii_tokens (inv_id, token, ciphertext, now)

get(inv_id):
    rows = SELECT token, masked_enc WHERE inv_id = ?
    return { token: f.decrypt(ciphertext) for each row }
```

### Key Management

```
Priority order:
  1. PII_STORE_KEY env var  ← production (base64url-encoded 32-byte key)
  2. data/.pii_key          ← dev (auto-generated, chmod 0600)

If PII_STORE_KEY is set:
  key validated to be exactly 32 bytes after decoding
  RuntimeError raised immediately on startup if invalid

If not set (dev only):
  Fernet.generate_key() called once
  Written to data/.pii_key with chmod 0600
  Warning logged: "Set PII_STORE_KEY in .env for production"
```

The key file receives `chmod 0600` (owner-read-only) immediately after creation, preventing other OS users from reading it.

### PII Never in Session State

ADK session state is a plain-text key-value store accessible to all agents in a pipeline. The PII token map is deliberately **not** stored there. Only the session-state flag `guardrail_input_validated` is written — this carries no sensitive data.

---

## 4. PII Detokenisation and Output Scanning

### The Problem

After the LLM responds, two risks remain:
1. The LLM may echo back tokens it received (`[EMAIL_0]`), which are meaningless to the user.
2. The LLM may independently generate PII it learned during training (e.g. inferring or fabricating an email address).

### Two-Pass Output Guardrail

The `after_model_callback` runs on every LLM response across all agents:

```
LLM response text
        │
        ▼
Pass 1: detokenise
  Replace [EMAIL_0] → "j***@example.com"
  Replace [PHONE_0] → "***-***-4567"
  (using token_map retrieved from pii_store)
        │
        ▼
Pass 2: rescan for independently generated PII
  _PII_RE.sub(mask_pii_in_text, response)
  Any email/phone/SSN/CC/IP the LLM generated
  itself is masked before the user sees it
        │
        ▼
User sees: masked values only — never raw PII
```

This double-pass design closes both the echo gap and the generation gap.

---

## 5. Authentication — Passwords and Tokens

### Password Storage

Passwords are stored as **bcrypt hashes** — never in plaintext. bcrypt is a deliberately slow hashing function that makes offline brute-force attacks computationally expensive:

```python
# auth.py
def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify_pw(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

`bcrypt.gensalt()` generates a unique random salt per password, so identical passwords produce different hashes. The users table stores only `(username, hashed_pw, role)`.

### JWT Tokens

After successful login, a signed JWT is issued:

```
POST /api/login  {username, password}
        │
        ├── verify_user: bcrypt.checkpw(password, stored_hash)
        │
        └── create_token(username, role)
              jwt.encode(
                { "sub": username, "role": role,
                  "exp": now + timedelta(hours=8) },
                secret=JWT_SECRET,
                algorithm="HS256"
              )
              → token string returned to client
```

```
Every protected API call:
  Authorization: Bearer <token>
        │
        ▼
  _require_auth() FastAPI dependency
    decode_token(token)  ← validates signature + expiry
    returns {username, role}  or raises 401
```

Key properties:
- **Algorithm:** HS256 (HMAC-SHA256) — server-side signature, tamper-evident
- **Expiry:** 8 hours (`JWT_EXPIRY_HOURS` env var)
- **Secret:** `JWT_SECRET` env var — defaults to `"dev-secret-change-me-in-production"` with an explicit warning
- **Stateless:** no server-side session table — the token is self-contained and verified on every request

### Client-Side Storage

The token is stored in `localStorage` under `auth_token`. On logout, all three auth keys are explicitly removed:

```javascript
function logout() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_role');
    localStorage.removeItem('auth_username');
    // clears displayed sessions, chat area, trades
}
```

---

## 6. Role-Based Access Control (RBAC)

### The Problem

Not all users should have access to all features. Financial trading data is sensitive; exposing trade history and analytics to every user regardless of role creates unnecessary privacy risk and potential regulatory concern.

### Role Definitions

Roles and their permitted intents are declared in `roles.yaml` — no code change required to update permissions, only a server restart:

```yaml
viewer:
  - PRICE
  - VISUALIZATION
  - ANNUAL_REPORT

analyst:
  - PRICE
  - VISUALIZATION
  - ANNUAL_REPORT
  - PREDICTION
  - ALERT
  - FINANCIAL_REPORT
  - STOCK_COMPARISON
  - INVESTMENT_RESEARCH
  - PRICE_PREDICTION
  - PRICE_PREDICT_CHART
  - ANNUAL_FINANCIAL
  - PDF_REPORT
  - TRADE_ANALYSIS

admin:
  - "*"          # all intents
```

### Enforcement — Two Layers

RBAC is enforced independently at the frontend and backend so neither layer alone is a single point of failure:

```
FRONTEND (index.html — _showApp()):
  role decoded from JWT on login
  if role === 'viewer':
    #tab-trades.style.display   = 'none'
    #tab-analytics.style.display = 'none'
    switchTab('chat')   ← forced, cannot be overridden by URL

BACKEND (agent.py — GraphOrchestrator):
  _current_role ContextVar set per-request by web_server
  before routing any intent:
    is_allowed(role, intent) → bool
    if not allowed → yield forbidden_event(ctx, intent)

  Pending-trade approval bypass also RBAC-gated:
    if has_pending_trade() and looks_like_approval:
      if not is_allowed(role, "TRADE_ANALYSIS"):
        cancel_pending_trade()
        yield forbidden_event(ctx, "TRADE_ANALYSIS")
        return   ← trading_agent never runs
```

A viewer cannot access trading features even by:
- Crafting a direct API request (backend check blocks it)
- Manipulating localStorage (backend re-validates role from JWT on every call)
- Typing an approval message like "yes" while a trade is pending (bypass is RBAC-gated)

### Role Assignment and Display

The role badge in the sidebar footer shows the current user's role at all times, so users always know what access level they are operating with. Roles are assigned at account creation and can only be changed by an administrator directly in the database.

---

## 7. Per-User Session Isolation

### The Problem

In a multi-user application, one user's conversation history must be completely invisible to another. Without strict session ownership enforcement, a user could enumerate or read another user's sessions by guessing session IDs.

### How Sessions Are Scoped

Every session carries a `user_id` field (the authenticated username). This is set at creation and never changed:

```
POST /api/sessions  (requires JWT)
  session = {
    "id":         uuid4(),
    "title":      "New Conversation",
    "created_at": now,
    "user_id":    authenticated_username,   ← locked at creation
    "messages":   []
  }
  → stored in _sessions dict (in-memory)
  → persisted to sessions_meta.db
  → ADK session created under user_id=username
```

```
GET /api/sessions  (requires JWT)
  return [s for s in _sessions.values()
          if s.get("user_id") == authenticated_username]
  ← filtered — other users' sessions never returned
```

```
DELETE /api/sessions/{session_id}  (requires JWT)
  if _sessions[session_id]["user_id"] != authenticated_username:
    raise HTTPException(403, "Not authorised to delete this session")
  ← ownership verified before any deletion
```

The ADK runner (`SqliteSessionService`) is also called with `user_id=username`, so conversation history in `sessions.db` is partitioned at the ADK level as well — double isolation.

---

## 8. Trading History Per-User Isolation

### The Problem

The client-side trade ledger is stored in `localStorage`. Without a user-specific namespace, all users sharing a browser would see the same trades.

### localStorage Namespacing

Every read and write to the trade ledger uses a key scoped to the authenticated username:

```javascript
function _tradesKey() {
    return 'trades_' + _authUser();   // e.g. "trades_alice"
}
// alice's trades stored under:  "trades_alice"
// admin's trades stored under:  "trades_admin"
// bob's trades stored under:    "trades_bob"
```

This means different browser accounts on the same machine maintain separate ledgers.

### Sample Data Bug — Fixed

An earlier version seeded identical sample trades (IDs `s1`–`s5`) for every new user on first login, making all accounts appear to share a trading history. This was fixed with a one-time purge on load:

```javascript
const _SAMPLE_IDS = new Set(['s1','s2','s3','s4','s5']);

function loadTrades() {
    const stored = localStorage.getItem(_tradesKey());
    if (stored === null) return [];
    const parsed = JSON.parse(stored);
    // Purge any lingering seeded sample trades
    const cleaned = parsed.filter(t => !_SAMPLE_IDS.has(t.id));
    if (cleaned.length !== parsed.length) {
        // Persist cleaned list (or remove key if now empty)
        if (cleaned.length === 0) localStorage.removeItem(_tradesKey());
        else localStorage.setItem(_tradesKey(), JSON.stringify(cleaned));
    }
    return cleaned;
}
```

New users now start with an empty ledger. Real trades added by the user have UUID-format IDs (e.g. `TRD-20260506-487CF0`) and are never purged.

### Logout Clears the Display

On logout, `auth_username` is removed from localStorage. Since `_tradesKey()` returns `'trades_'` (empty username suffix) when no user is logged in, and `loadTrades()` finds no entry under that key, the trade table shows empty. No explicit per-user data deletion is needed — the namespace mismatch ensures isolation.

---

## 9. Secure File Serving — Path Traversal Guard

### The Problem

`GET /api/downloads/{filename}` serves generated PDF reports from the `output/` directory. Without validation, a malicious filename like `../../etc/passwd` or `../sessions_meta.db` could expose arbitrary server files.

### The Guard

```python
_OUTPUT_DIR = (Path(__file__).parent / "output").resolve()

@app.get("/api/downloads/{filename}")
async def download_file(filename: str, user=Depends(_require_auth)):
    """Path-traversal guard: only basename allowed; resolved path must
    stay inside output/."""

    candidate = (_OUTPUT_DIR / filename).resolve()

    # Rule 1: resolved path must be inside output/
    try:
        candidate.relative_to(_OUTPUT_DIR)
    except ValueError:
        raise HTTPException(403, "Access denied")

    # Rule 2: no dotfiles (e.g. .pii_key, .env)
    if candidate.name.startswith("."):
        raise HTTPException(403, "Access denied")

    # Rule 3: must be a regular file (not a directory or symlink)
    if not candidate.is_file():
        raise HTTPException(404, "File not found")

    return FileResponse(
        path=str(candidate),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={candidate.name}"},
    )
```

`Path.resolve()` collapses all `../` components before the check — there is no way for a traversal sequence to bypass `relative_to()` after resolution. The endpoint also requires a valid JWT (`Depends(_require_auth)`), so unauthenticated requests are rejected before the path check even runs.

---

## 10. Audit Log Privacy

### The Problem

Comprehensive audit logs are required for compliance (90-day financial services retention), but logs that contain raw PII or full message text create their own privacy liability.

### What Is and Is Not Logged

```
LOGGED (structured JSON per event):
  session_id        ← session identifier (pseudonymous)
  user_id           ← username
  agent             ← agent name
  tool              ← tool name + status
  token counts      ← input/output token count
  cost_usd          ← LLM call cost
  model_version     ← "gemini-2.5-flash"
  model_build       ← "2026-05-06"
  timestamp         ← ISO 8601

NOT LOGGED:
  Raw user message text    ← never written to audit
  Raw PII                  ← tokenised before LLM boundary,
                              never appears in any context
  Base64 chart images      ← stripped by after_tool_callback
                              before they can appear in any log
                              (~50 KB per chart — would flood logs)
  Passwords / JWT secrets  ← never in any code path near logging
  Financial report content ← response text not written to audit
```

### Base64 Stripping

Chart tools return ~50 KB base64 PNG strings in their responses. The `after_tool_callback` in `audit.py` strips the `markdown` field from chart tool responses before logging:

```python
if tool.name in _CHART_RENDER_TOOLS and "markdown" in tool_response:
    stripped = {k: v for k, v in tool_response.items() if k != "markdown"}
    stripped["chart_displayed"] = True
    return stripped   # LLM and audit both receive the stripped version
```

This serves two purposes: it prevents the audit log from ballooning with binary data, and it prevents the 50 KB base64 string from entering the LLM's 170K-token context window.

### Log Rotation and Retention

```python
# audit.py
_file_handler = logging.handlers.TimedRotatingFileHandler(
    filename="audit.log",
    when="midnight",          # rotate daily at 00:00
    backupCount=90,           # keep 90 days of rotated logs
    encoding="utf-8",
)
# Previous day's log is gzip-compressed automatically
# Logs older than 90 days are deleted automatically
```

Rotation produces files named `audit.log.YYYY-MM-DD.gz`. After 90 days, the handler deletes the oldest file automatically. No manual cleanup is required.

---

## 11. Data Lifecycle and Retention

| Data store | Contains | Retention | Encryption |
|---|---|---|---|
| `pii_tokens.db` | Fernet ciphertexts of masked PII values | 90-day TTL, lazy purge | Fernet AES-128-CBC |
| `sessions_meta.db` | Session metadata + bcrypt password hashes | Indefinite (user-deletable) | None (plaintext SQLite) |
| `sessions.db` | Full ADK conversation history | Indefinite (user-deletable) | None (plaintext SQLite) |
| `trades.jsonl` | Mock trade records with session_id | Indefinite (append-only) | None |
| `feedback.jsonl` | Vote + username + session_id | Indefinite (append-only) | None |
| `audit.log` / `audit.log.*.gz` | Structured agent events | 90 days, auto-deleted | None (filesystem permissions) |
| `cost.jsonl` | LLM cost per call, agent, model | Indefinite | None |
| `localStorage trades_{user}` | Client-side trade ledger | Until browser data cleared | None (browser storage) |
| `localStorage auth_token` | JWT bearer token | Until logout or 8h expiry | Signed (not encrypted) |

### PII Token TTL

PII tokens are purged lazily on every write to `pii_store.put()`:

```python
cutoff = now - PII_TOKEN_TTL_SECONDS   # default: 90 days
conn.execute("DELETE FROM pii_tokens WHERE created_at < ?", (cutoff,))
```

This runs in the same transaction as the new insert, so no separate cleanup job is needed. Tokens are kept for 90 days to support detokenisation across long-running multi-turn sessions.

---

## 12. Known Limitations

These gaps are acknowledged and represent future privacy work:

| Limitation | Detail | Risk Level |
|---|---|---|
| **No right-to-erasure** | Deleting a session removes chat history but `trades.jsonl`, `feedback.jsonl`, and audit logs retain entries linked to that username indefinitely | Medium |
| **No data portability** | Users cannot export their own sessions, trades, or feedback in a portable format (GDPR Article 20) | Low |
| **sessions.db / sessions_meta.db not encrypted at rest** | Only `pii_tokens.db` uses Fernet; conversation history and session metadata sit in plaintext SQLite files | Medium |
| **JWT in localStorage** | Vulnerable to XSS on the same origin; `HttpOnly` cookie would be more secure but requires additional CORS and same-site configuration | Medium |
| **No consent mechanism** | No cookie banner, privacy policy, or explicit data processing consent — required for GDPR compliance in production | High |
| **Single data source for user identity** | Users table in `sessions_meta.db` has no multi-factor authentication, account lockout on failed attempts, or password rotation policy | Medium |
| **Audit log user_id is plaintext** | `session_id` and `user_id` (username) are written in plaintext to `audit.log` — pseudonymous but not anonymous | Low |

---

## 13. Summary Table — All Privacy Measures

| # | Measure | Layer | File(s) |
|---|---|---|---|
| 1 | PII regex detection (EMAIL, PHONE, SSN, CC, IP) | Input | `guardrails.py` |
| 2 | PII tokenisation before every LLM call | Input | `guardrails.py` |
| 3 | Masked values — raw PII never stored anywhere | Input | `guardrails.py` |
| 4 | Fernet-encrypted SQLite PII token store | Storage | `pii_store.py` |
| 5 | AES-128-CBC + HMAC-SHA256 encryption | Storage | `pii_store.py` |
| 6 | Key from env var (prod) or chmod 0600 file (dev) | Storage | `pii_store.py` |
| 7 | 90-day TTL with lazy purge on every write | Storage | `pii_store.py` |
| 8 | PII never written to session state | Storage | `guardrails.py` |
| 9 | Output detokenisation (token → masked value) | Output | `guardrails.py` |
| 10 | Output rescan for LLM-generated PII | Output | `guardrails.py` |
| 11 | bcrypt password hashing (salted, slow) | Auth | `auth.py` |
| 12 | JWT HS256 with 8h expiry | Auth | `auth.py` |
| 13 | JWT_SECRET env var with prod warning | Auth | `auth.py` |
| 14 | JWT validated on every protected API call | Auth | `web_server.py` |
| 15 | Logout clears all auth localStorage keys | Auth | `static/index.html` |
| 16 | RBAC via roles.yaml (viewer / analyst / admin) | Access | `rbac.py`, `roles.yaml` |
| 17 | Frontend tab hiding for restricted roles | Access | `static/index.html` |
| 18 | Backend is_allowed() check on every intent | Access | `agent.py`, `rbac.py` |
| 19 | Pending-trade bypass RBAC-gated | Access | `agent.py` |
| 20 | Sessions scoped by user_id at creation | Isolation | `web_server.py` |
| 21 | GET /api/sessions filtered by authenticated user | Isolation | `web_server.py` |
| 22 | DELETE /api/sessions ownership check (403 if mismatch) | Isolation | `web_server.py` |
| 23 | ADK sessions partitioned by user_id | Isolation | `web_server.py` |
| 24 | localStorage trade ledger namespaced trades_{username} | Isolation | `static/index.html` |
| 25 | Sample trade purge (s1–s5) on load | Isolation | `static/index.html` |
| 26 | Logout clears trade display | Isolation | `static/index.html` |
| 27 | Path traversal guard on /api/downloads/ | File system | `web_server.py` |
| 28 | Dotfile blocking on download endpoint | File system | `web_server.py` |
| 29 | .pii_key chmod 0600 | File system | `pii_store.py` |
| 30 | pii_tokens.db git-ignored | File system | `.gitignore` |
| 31 | No raw PII in audit logs (tokenised upstream) | Audit | `audit.py` |
| 32 | Base64 chart images stripped before logging | Audit | `audit.py` |
| 33 | No message text in audit entries | Audit | `audit.py` |
| 34 | 90-day log rotation with gzip + auto-delete | Audit | `audit.py` |
| 35 | Feedback records minimum fields only (no message text) | Audit | `web_server.py` |
