# User Experience Design

**Version:** 1.0  
**Date:** 2026-05-06  
**Scope:** All UX measures — existing and new — taken to make FinanceAI feel fast, clear, and effortless for every type of user.

---

## Table of Contents

1. [Overview](#1-overview)
2. [What We Already Had](#2-what-we-already-had)
   - [Visual Design & Brand Identity](#21-visual-design--brand-identity)
   - [Layout & Navigation](#22-layout--navigation)
   - [Chat Interface](#23-chat-interface)
   - [Streaming & Real-Time Progress](#24-streaming--real-time-progress)
   - [Rich Content Rendering](#25-rich-content-rendering)
   - [Feedback Loop](#26-feedback-loop)
   - [Prompt Library](#27-prompt-library)
   - [Trading History Tab](#28-trading-history-tab)
   - [Analytics Tab](#29-analytics-tab)
   - [Role-Based Access & Identity](#210-role-based-access--identity)
   - [Conversational Intelligence](#211-conversational-intelligence)
3. [New Fixes — Seven UX Gaps](#3-new-fixes--seven-ux-gaps)
   - [Gap 1 — Keyboard Shortcuts](#gap-1--keyboard-shortcuts)
   - [Gap 2 — Copy Button on Responses](#gap-2--copy-button-on-responses)
   - [Gap 3 — Session Rename](#gap-3--session-rename)
   - [Gap 4 — Suggested Follow-Up Prompts](#gap-4--suggested-follow-up-prompts)
   - [Gap 5 — Mobile-Responsive Layout](#gap-5--mobile-responsive-layout)
   - [Gap 6 — Edit / Resend User Messages](#gap-6--edit--resend-user-messages)
   - [Gap 7 — Scroll-to-Bottom Button](#gap-7--scroll-to-bottom-button)
4. [Complete Summary Table](#4-complete-summary-table)
5. [Known Limitations](#5-known-limitations)

---

## 1. Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UX DESIGN LAYERS                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  VISUAL          Consistent dark theme, color semantics,           │
│                  typography, micro-transitions                      │
│                                                                     │
│  NAVIGATION      Collapsible/resizable sidebar, session history,   │
│                  search, tabs, market status, user identity         │
│                                                                     │
│  CHAT            Streaming tokens, typed progress labels,          │
│                  markdown rendering, inline images, signal cards    │
│                                                                     │
│  DISCOVERY       Prompt library (Ctrl+K), suggested follow-ups,   │
│                  categorised templates with ticker substitution     │
│                                                                     │
│  TRADING         Per-user history, agent-trade sync, analytics     │
│                  dashboard with live prices and P&L charts          │
│                                                                     │
│  CONVERSATION    Disambiguation, context-switch notices,           │
│                  jargon definitions, edit/resend, copy button       │
│                                                                     │
│  ACCESSIBILITY   Mobile layout, keyboard shortcuts, scroll-to-     │
│                  bottom, session rename, follow-up chips            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. What We Already Had

### 2.1 Visual Design & Brand Identity

**Consistent color system**

The entire UI uses a single coherent palette. Every component references the same six semantic colors — no ad-hoc values anywhere:

| Role | Hex | Used for |
|---|---|---|
| Background | `#091526` | Page, messages panel |
| Surface | `#0d1e33` | Bubbles, cards, inputs |
| Border | `#152236` | All dividers and borders |
| Accent | `#1a6fd4` | Buttons, active states, links |
| Text primary | `#cdddf0` | Main readable content |
| Text secondary | `#5d7a99` | Labels, timestamps, hints |
| Positive / BUY | `#2ecc8e` | Gains, market open, BUY badge |
| Negative / SELL | `#e05252` | Losses, danger actions, SELL badge |

This means green always means "good" and red always means "danger" — users build intuition once and it applies everywhere: the analytics P&L card, the BUY/SELL badge in trading, the market status indicator, the thumbs-down feedback button.

**Typography**

Inter is loaded as the primary font with a full system-font stack fallback (`-apple-system, BlinkMacSystemFont, "Segoe UI"`). All financial figures use `font-variant-numeric: tabular-nums` so decimal points align vertically in tables — a subtle detail that makes scanning numbers significantly faster.

**Micro-transitions**

Every interactive element has a `transition: 0.12s–0.22s ease`. Hover states, sidebar collapse, modal open/close, and the signal confidence bar fill all animate smoothly. This removes the jarring "snap" that makes interfaces feel unpolished. The transitions are fast enough to feel instantaneous yet slow enough to communicate state change.

**Favicon and logo**

An SVG favicon (`/static/favicon.svg`) and logo (`/static/logo.svg`) give the app a distinct identity in browser tabs and bookmarks.

---

### 2.2 Layout & Navigation

**Collapsible sidebar**

The sidebar starts at 240px and collapses to 48px with a single click on the `‹` button. In collapsed mode, the session list, search, and user info are hidden — the user gets the full viewport width for reading responses. The collapse state persists in `localStorage` so it survives page refreshes.

```
Expanded (240px)                  Collapsed (48px)
┌──────────────┐                  ┌──┐
│ FinanceAI  + │                  │  │
│ ─────────── │                  │  │
│ Search…      │    ──────────►   │  │
│ Session 1    │                  │  │
│ Session 2    │                  │  │
│ (user) admin │                  │  │
└──────────────┘                  └──┘
```

**Resizable sidebar**

A 4px drag handle sits between the sidebar and main area. Dragging it turns the cursor to `col-resize` and recolors the handle blue. Width is clamped between 160px and 480px and saved to `localStorage` on release:

```javascript
localStorage.setItem('sidebar_width', parseInt(sidebar.style.width, 10));
```

**Session history with search**

Every conversation is stored as a session with a title (auto-set from the first message) and a creation timestamp. Sessions are displayed in reverse-chronological order. A live search box filters in real time with the matched text highlighted using `<mark>` tags. A "no results" empty state shows when nothing matches.

**Session delete with confirmation**

The delete button (✕) on session items is hidden by default and appears only on hover — preventing accidental clicks. Clicking shows a modal confirmation dialog rather than deleting immediately. The dialog uses a red destructive action button to signal irreversibility.

**Three main tabs — RBAC-controlled**

The tab bar contains Chat, Trading History, and Analytics. The last two are hidden entirely for `viewer`-role users — they are not just disabled, they do not exist in the DOM for that role. If a viewer's role changes mid-session, `switchTab('chat')` is called automatically.

**Market status indicator**

A small badge in the header shows `OPEN` (green) or `CLOSED` (gray) based on NYSE trading hours (09:30–16:00 ET, Mon–Fri). It refreshes every minute so users know at a glance whether live prices are current or from the previous close.

---

### 2.3 Chat Interface

**Chat bubbles with distinct geometry**

User messages: solid `#1a6fd4` blue bubble, right-aligned, rounded with a flat bottom-right corner — the standard "sent" message shape. Assistant messages: dark `#0d1e33` surface with a `#152236` border, left-aligned, flat bottom-left corner — the standard "received" shape. The asymmetry removes any ambiguity about who said what.

**Auto-growing textarea**

The input field grows from its minimum height of 44px up to 150px as the user types. `oninput="autoResize(this)"` recalculates `scrollHeight` on every keystroke:

```javascript
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 150) + 'px';
}
```

**Enter to send, Shift+Enter for newline**

The standard convention for messaging apps. The textarea's `onkeydown` intercepts `Enter` without `Shift`, calls `sendMessage()`, and prevents the default newline.

**Send button disabled during streaming**

While a response is streaming, `$('send-btn').disabled = true` prevents double-submission. The button turns to a dark muted color to signal it's unavailable.

**Empty state**

When a session has no messages, a centred illustration placeholder (`<h2>Stock Analysis Agent</h2>`) fills the space rather than a blank panel.

**Separator events between pipeline stages**

In compound pipelines (e.g. PRICE_PREDICTION: price agent → prediction agent), a blank-line separator event is emitted between steps so the two agents' outputs start on separate paragraphs rather than running together.

---

### 2.4 Streaming & Real-Time Progress

**Token-by-token streaming via SSE**

Responses arrive as Server-Sent Events. The client reads the stream with `ReadableStream` and `TextDecoder`, accumulating partial text in `accText`. The `marked.js` parser re-renders the full accumulated text on every token event — the user sees formatted markdown appear live, not raw text followed by a render flash.

**Typing dots animation**

While waiting for the first token, three animated dots appear inside the assistant bubble:

```css
.typing-dots span {
  animation: tdot 1.2s infinite;
}
.typing-dots span:nth-child(2) { animation-delay: 0.2s; }
.typing-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes tdot {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
  40%           { transform: translateY(-5px); opacity: 1; }
}
```

The staggered delays create a wave motion that reads clearly as "working."

**Inline progress labels alongside the dots**

During pipeline execution, progress events replace the dots-only state with dots + a descriptive label:

```
● ● ●  Fetching live price data…
● ● ●  Running 2-week forecast…
● ● ●  Rendering chart…
```

Each pipeline has a specific set of labels defined in `_STEP_PROGRESS` in `agent.py`. This means users always know which stage is running — they're not staring at a spinner with no information.

```python
_STEP_PROGRESS = {
    "PRICE_PREDICTION":    ["Fetching live price…", "Running forecast…"],
    "ANNUAL_FINANCIAL":    ["Searching 10-K filing…", "Analysing financials…"],
    "PRICE_PREDICT_CHART": ["Fetching live price…", "Running forecast…", "Rendering chart…"],
    ...
}
```

**Cross-pipeline consistency cue**

In the `ANNUAL_FINANCIAL` pipeline, an additional progress event fires before the financial report stage: `"Cross-checking 10-K insights against financial data…"`. This tells the user the system is doing an extra verification step, not just running the same agent twice.

**Pipeline abort message**

If an intermediate pipeline stage fails validation, the orchestrator emits a clear abort message naming the failed stage and suggesting how to fix it — not a generic error page.

**Agent-trade sync without page refresh**

When the agent executes a paper trade, a `trade_executed` SSE event is emitted. The frontend catches it and writes the trade to `localStorage` immediately. If the SSE event is missed, the `done` handler runs `_syncTradeFromText(accText)` which regex-parses the agent's structured confirmation block as a fallback. Both paths call the same `_syncAgentTrade()` deduplication function. The result: trades appear in the Trading History tab the instant the response finishes — no manual refresh.

---

### 2.5 Rich Content Rendering

**Full Markdown via marked.js**

All assistant responses are rendered through `marked.js` with `{ breaks: true, gfm: true }`. The output supports:

| Element | CSS styling |
|---|---|
| `h1` / `h2` / `h3` | Sized 16/15/14px, `#cdddf0` color |
| Bold, italic | Standard weight/style |
| Unordered and ordered lists | `20px` left margin |
| Tables | Collapsed borders, alternating row shading (`#0a1828`) |
| Code blocks | `#07111f` background, monospace font, horizontal scroll |
| Inline code | `#0a1828` background, `#c9a84c` amber color |
| Blockquotes | Left `#1c3050` border, `#5d7a99` text |
| Images | `max-width: 100%`, `border-radius: 8px` |
| Links | `#1a6fd4` blue |

**Inline chart images**

Charts generated by the visualization agent are streamed as base64-encoded PNG data via the `image` SSE event type, then rendered as `<img>` tags directly inside the chat bubble. No download or new tab required.

**Signal badge widget**

Trading signal responses include a structured `signal` SSE event that renders a dedicated visual card:

```
┌──────────────────────────────────┐
│  BUY  NVDA                0.72  │
│  Confidence ████████░░░░  72%   │
└──────────────────────────────────┘
```

- Color-coded pill: green `BUY`, red `SELL`, gray `HOLD`
- The confidence bar fills with a `transition: width 0.4s ease` animation
- Score displayed to 2 decimal places

**Citation chips with source snippets**

10-K answers include a collapsible "📎 Sources (N)" toggle below the response. Each cited passage renders as a chip. Hovering any chip shows the first 120 characters of the source passage as a tooltip:

```javascript
chip.title = s.snippet || '';
```

This lets users verify what text the answer is grounded in without leaving the chat.

**Authenticated PDF download**

Markdown links to `/api/downloads/*.pdf` are intercepted by a delegated click handler that fetches the file with the JWT auth header, creates a Blob URL, and triggers a native download — all transparently. The link text changes to "⏳ Downloading…" then "✅ Downloaded" for 2 seconds:

```javascript
document.addEventListener('click', async (ev) => {
  const a = ev.target.closest('a[href^="/api/downloads/"]');
  if (!a) return;
  ev.preventDefault();
  // fetch with auth, create Blob, trigger download
});
```

---

### 2.6 Feedback Loop

**Per-response thumbs up/down**

Each assistant response has a feedback row (👍 / 👎) that fades in with a 0.2s delay after the response completes. The fade-in prevents the buttons from appearing mid-stream and startling the user.

Selected state is visually distinct:
- 👍 selected → green border + green icon + green background tint
- 👎 selected → red border + red icon + red background tint

Once a vote is submitted, both buttons are disabled to prevent duplicate votes. Votes POST to `/api/feedback` and feed into the `thumbs_down_rate` metric in the evaluation dashboard.

---

### 2.7 Prompt Library

**Discoverable prompt templates**

A `☰` button (Prompt Library, `Ctrl+K`) next to the input opens a full modal of pre-written prompts organised into 18 categories covering every pipeline:

- 📈 Price, 🔮 Forecast, 📊 Price + Forecast, 🖼️ Charts, 🔭 Price + Forecast Chart
- 💰 Financial Reports, 📋 Annual Reports (10-K), ⚖️ Stock Comparison, 📄 PDF Export
- 🔔 Drop Alerts, 🤝 Trading (Mock)
- 🔬 Investment Research (6 sub-categories: Cross-filing Trends, Cross-section Analysis, Segments & Products, Risk & Legal, Executive & Governance, Forward Guidance, Entity Tracing)

**Company ticker selector**

A dropdown at the top of the modal lets users pick any of 40 supported companies. Selecting a company instantly replaces `{TICKER}` and `{COMPANY}` placeholders in all prompt texts. Clicking a prompt chip fills the prepared query into the input and closes the modal.

**Investment Research lock**

The 6 Investment Research categories are dimmed and unclickable when a non-MSFT company is selected (since only Microsoft filings are indexed in the knowledge graph). A `🔒 Investment Research locked to MSFT` banner explains why.

**Real-time prompt search**

Typing in the modal's search box hides non-matching chips and collapses entire categories. A "No prompts match your search" empty state appears when nothing matches.

---

### 2.8 Trading History Tab

**Per-user data isolation**

Trades are stored in `localStorage` under `trades_{username}`. Different users on the same browser see completely separate histories. Sample trades seeded by a previous bug (`s1`–`s5`) are automatically purged on load:

```javascript
const _SAMPLE_IDS = new Set(['s1', 's2', 's3', 's4', 's5']);
function loadTrades() {
  const cleaned = parsed.filter(t => !_SAMPLE_IDS.has(t.id));
  // persist cleaned list
}
```

**Trade table**

Columns: Date, Symbol (bold), Type (BUY/SELL badge), Quantity (tabular numerals), Price (USD formatted), Total (USD formatted), Notes. Rows highlight on hover. Reverse-chronological by default.

**Manual trade entry**

An "Add Transaction" button opens a modal form with: Date (pre-filled to today), Type (BUY/SELL select), Symbol (auto-uppercased), Quantity, Price per Share, and Notes. Validation prevents submission with empty required fields.

**BUY/SELL color-coded badges**

```css
.trade-type.buy  { background: rgba(46,204,142,0.12); color: #2ecc8e; }
.trade-type.sell { background: rgba(224,82,82,0.12);  color: #e05252; }
```

---

### 2.9 Analytics Tab

**Portfolio summary cards**

Four metric cards at the top:
- **Total Portfolio** — cash + market value of all open positions
- **Cash** — starting $100,000 minus net invested amount
- **Open Positions** — count of tickers with non-zero shares
- **Unrealised P&L** — current market value minus total cost; green if positive, red if negative; percentage shown below

**Allocation donut chart**

Chart.js doughnut chart showing cash and each position as a percentage slice. Tooltips show exact dollar value and percentage. Legend below the chart.

**Holdings table**

Per-ticker breakdown: Symbol, Shares, Avg Cost, Current Price (live), Market Value, Gain/Loss ($), Gain/Loss (%). Gain/Loss cells use green/red coloring.

**Live price cards**

For each held ticker, a small card fetches the current price from `/api/prices` and shows the symbol, price, and daily change (color-coded positive/negative).

**Portfolio value trend chart**

Line chart of portfolio value over the last 3 months, computed from trade history combined with historical price data from `/api/price-history`.

**Individual stock price chart**

Separate multi-line chart showing 3-month price history for each held ticker in distinct colors from `_CHART_PALETTE`.

**Refresh button**

Manual `⟳ Refresh` button in the analytics header re-fetches all live price and history data.

---

### 2.10 Role-Based Access & Identity

**User identity display**

The sidebar footer shows: a circular avatar with the user's initial (styled with the accent color), username, role label, and a role badge:

```
  A   admin                  [Admin]
      Role
      [ Sign out ]
```

The role badge is color-coded: green for viewer, blue for analyst, red for admin.

**Tab visibility enforcement**

Trading History and Analytics tabs are hidden from the DOM entirely for viewer-role users. If a viewer somehow lands on a restricted tab (e.g. role changed mid-session), `switchTab('chat')` is called automatically.

**Session ownership**

Every API endpoint that reads or modifies a session (`GET`, `PATCH`, `DELETE`, `POST /api/chat`) checks `sess.get("user_id") != user["username"]` and returns 403 if the requesting user doesn't own the session. This prevents users from accessing each other's conversation history even if they guess a session ID.

---

### 2.11 Conversational Intelligence (UX Layer)

These were covered in detail in `docs/misinterpretation.md` but are listed here as UX measures too:

| Measure | UX benefit |
|---|---|
| Ambiguous query clarification | User is never silently sent down the wrong pipeline |
| Ticker disambiguation list | User picks the exact company before any data is fetched |
| Trade quantity override ("5 shares") | User can adjust the auto-calculated quantity without restarting |
| Context-switch notice | User always knows which company the system is now focused on |
| Financial jargon definitions | Non-expert users understand every term in the response |
| UNKNOWN intent clarification | User gets specific alternatives, not a generic "I don't understand" |
| Pending trade auto-cancel on pivot | User isn't stuck in the trade flow when they want to ask something else |

---

## 3. New Fixes — Seven UX Gaps

---

### Gap 1 — Keyboard Shortcuts

#### Problem

Every interaction required a mouse click. Power users who prefer keyboard-driven workflows had no shortcuts to:
- Open the prompt library (forced to reach for the `☰` button)
- Close any modal (forced to click the ✕ or overlay)

#### Fix

**File: `static/index.html`**

A global `keydown` listener was added that handles three shortcuts:

```javascript
document.addEventListener('keydown', e => {
  // Ctrl+K / Cmd+K → toggle prompt library
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const overlay = $('prompt-modal-overlay');
    overlay.classList.contains('open') ? closePromptLib() : openPromptLib();
  }
  // Escape → close whichever modal is currently open
  if (e.key === 'Escape') {
    if ($('prompt-modal-overlay').classList.contains('open'))  closePromptLib();
    if ($('trade-modal-overlay').classList.contains('open'))   closeTradeModal();
    if ($('confirm-overlay').classList.contains('open') && _confirmResolve)
      _confirmResolve(false);
    closeMobileSidebar();
  }
});
```

The prompt library button tooltip was updated to show `(Ctrl+K)` as a discoverability hint. `Cmd+K` on macOS and `Ctrl+K` on Windows/Linux are both handled.

**Coverage:**

| Shortcut | Action |
|---|---|
| `Ctrl+K` / `Cmd+K` | Open / close prompt library |
| `Escape` | Close prompt library |
| `Escape` | Close trade entry modal |
| `Escape` | Dismiss confirm dialog (equivalent to Cancel) |
| `Escape` | Close mobile sidebar |

---

### Gap 2 — Copy Button on Responses

#### Problem

To copy a response, users had to manually select all the text in the assistant bubble — difficult because markdown renders as HTML (selecting rendered text copies formatted content inconsistently across browsers). There was no way to copy the clean raw markdown.

#### Risk

Users pasting financial data into spreadsheets or other tools get messy formatted output with invisible HTML artifacts instead of clean plain text.

#### Fix

**File: `static/index.html`**

A `⎘ Copy` button was added to every assistant response's feedback row (alongside 👍/👎). It copies the raw accumulated markdown text via `navigator.clipboard.writeText()`:

```javascript
const copyBtn = document.createElement('button');
copyBtn.className   = 'copy-btn';
copyBtn.textContent = '⎘ Copy';
copyBtn.onclick     = async () => {
  try {
    await navigator.clipboard.writeText(getPreview());   // raw markdown
    copyBtn.textContent = '✓ Copied';
    copyBtn.classList.add('copied');                      // turns green
    setTimeout(() => {
      copyBtn.textContent = '⎘ Copy';
      copyBtn.classList.remove('copied');
    }, 2000);
  } catch (_) {
    copyBtn.textContent = '✕ Failed';
    setTimeout(() => { copyBtn.textContent = '⎘ Copy'; }, 2000);
  }
};
```

State transitions:
- Default: `⎘ Copy` (muted border, muted color)
- On success: `✓ Copied` (green border, green text, green background tint) for 2 seconds
- On clipboard failure: `✕ Failed` for 2 seconds then resets

The `getPreview()` closure captures `accText` (the raw markdown string) at the time the feedback row is created — it will always return the complete response text regardless of when the button is clicked.

---

### Gap 3 — Session Rename

#### Problem

Session titles were auto-generated from the first message (truncated to 55 characters). Users had no way to give a session a meaningful name like "AAPL Q2 Analysis" or "Comparison with MSFT". The sidebar became a list of truncated first messages with no way to organise them.

#### Fix

**File: `web_server.py`**

A `PATCH /api/sessions/{session_id}` endpoint was added:

```python
class RenameRequest(BaseModel):
    title: str

@app.patch("/api/sessions/{session_id}")
def rename_session(session_id, req, user):
    if session_id not in _sessions:
        raise HTTPException(404)
    sess = _sessions[session_id]
    if sess.get("user_id") != user["username"]:
        raise HTTPException(403)
    title = req.title.strip()[:80] or "Untitled"
    sess["title"] = title
    _meta_upsert_session(sess)     # persists to sessions_meta.db
    return sess
```

The title is clamped to 80 characters and falls back to "Untitled" if blank.

**File: `static/index.html`**

Session title elements in the sidebar have `ondblclick="startRename(id, this)"`. Double-clicking replaces the title `<div>` with an inline `<input>`:

```javascript
function startRename(id, titleEl) {
  const current = sessions[id]?.title || '';
  const input   = document.createElement('input');
  input.className = 'session-title-input';    // styled with blue border
  input.value     = current;
  input.maxLength = 80;
  titleEl.replaceWith(input);
  input.focus();
  input.select();

  async function commitRename() {
    const newTitle = input.value.trim() || current;
    // Restore the title element
    const restored = document.createElement('div');
    restored.className = 'session-title';
    restored.textContent = newTitle;
    restored.setAttribute('ondblclick', `startRename('${id}', this)`);
    input.replaceWith(restored);

    if (newTitle === current) return;
    // Optimistic update — UI updates before network response
    if (sessions[id]) sessions[id].title = newTitle;
    if (id === activeId) $('chat-title').textContent = newTitle;
    renderSidebar();
    // Persist to server
    await fetch(`/api/sessions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ..._authHeaders() },
      body: JSON.stringify({ title: newTitle }),
    });
  }

  input.addEventListener('blur',    commitRename);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') { input.value = current; input.blur(); }
  });
}
```

Interaction design:
- **Double-click** on any session title → enters edit mode
- **Enter** or **click away** → commits the new name (optimistic UI, then persists)
- **Escape** → cancels without saving (restores original)
- The active chat header (`#chat-title`) updates immediately if renaming the active session
- Survives page refresh because the title is persisted in `sessions_meta.db`

---

### Gap 4 — Suggested Follow-Up Prompts

#### Problem

After receiving a response, users — especially new ones — had no obvious next step. They either closed the tab, re-typed a similar query, or opened the prompt library manually. There was no contextual guidance on what to explore next.

#### Risk

Users don't discover the full breadth of the system's capabilities. A user who asks for a price quote might not know they can immediately follow up with a forecast, chart, or trading signal.

#### Fix

**File: `web_server.py`**

The `done` SSE event now includes a `follow_ups` array. The list is chosen by reading the `pipeline` key from the ADK session state (set by the orchestrator on every routing decision) and looking it up in a 14-entry table:

```python
_FOLLOWUPS = {
    "PRICE":            ["Run a 2-week forecast →", "Show a price chart →",    "Get the financial report →"],
    "PREDICTION":       ["Show the forecast as a chart →", "Get the current price →", "Check financial health →"],
    "FINANCIAL_REPORT": ["Read the 10-K annual filing →", "Run a 2-week forecast →", "Generate a PDF report →"],
    "TRADE_ANALYSIS":   ["Show my portfolio →", "See trade history →", "Get the financial report →"],
    "ANNUAL_REPORT":    ["Get the financial report →", "See both 10-K + financials →", "Export as PDF →"],
    # ... 9 more entries
}
yield _sse({"type": "done", "title": session["title"], "follow_ups": _follow_ups})
```

**File: `static/index.html`**

On the `done` SSE event, if `follow_ups` is present and the response was non-empty, a row of pill chips is appended below the feedback row with a 0.3s fade-in:

```javascript
} else if (ev.type === 'done') {
  // ... title update, trade sync ...
  if (ev.follow_ups && ev.follow_ups.length && accText.trim()) {
    const followRow = document.createElement('div');
    followRow.className = 'followup-row';
    ev.follow_ups.forEach(label => {
      const chip = document.createElement('button');
      chip.className   = 'followup-chip';
      chip.textContent = label;
      chip.onclick = () => {
        const company = _lastMentionedCompany(accText);
        const q       = _followUpToQuery(label, company);
        $('user-input').value = q;
        autoResize($('user-input'));
        $('user-input').focus();
      };
      followRow.appendChild(chip);
    });
    bubble.appendChild(followRow);
  }
}
```

`_lastMentionedCompany(text)` extracts the first likely ticker symbol from the response text. `_followUpToQuery(label, company)` maps the chip label to a complete query string with the company substituted in — so clicking "Run a 2-week forecast →" after an AAPL price response fills the input with `"What is the 2-week price forecast for AAPL?"`.

**Example:**

After asking "What is the current price of NVDA?":
```
👍  👎  ⎘ Copy

  Run a 2-week forecast →   Show a price chart →   Get the financial report →
```

Clicking "Run a 2-week forecast →" fills the input with:
> `What is the 2-week price forecast for NVDA?`

---

### Gap 5 — Mobile-Responsive Layout

#### Problem

The layout had no `@media` breakpoints. On screens narrower than 768px (phones, small tablets), the 240px sidebar consumed a third of the viewport leaving a tiny 240px chat area that was unusable. The analytics grid, modals, and bubble widths also overflowed on mobile.

#### Fix

**File: `static/index.html`**

A mobile hamburger button and a sidebar overlay element were added to the HTML:

```html
<!-- Tapping the overlay closes the sidebar -->
<div id="sidebar-overlay" onclick="closeMobileSidebar()"></div>

<!-- In the chat header -->
<button id="mobile-menu-btn" onclick="toggleMobileSidebar()">☰</button>
```

Two media query blocks were added:

**`@media (max-width: 768px)`** — tablets and phones:
```css
#mobile-menu-btn { display: block; }

#sidebar {
  position: fixed;
  top: 0; left: 0; height: 100%;
  z-index: 50;
  transform: translateX(-100%);    /* off-screen by default */
  transition: transform 0.25s ease;
  width: 280px !important;
}
#sidebar.mobile-open { transform: translateX(0); }  /* slide in */
#sidebar-resizer     { display: none; }

.msg               { max-width: 94%; }
.analytics-cards   { grid-template-columns: repeat(2, 1fr); }
.analytics-row     { grid-template-columns: 1fr; }
#prompt-modal      { width: calc(100vw - 16px); }
```

**`@media (max-width: 480px)`** — small phones:
```css
#main-tabs .main-tab { padding: 9px 10px; font-size: 12px; }
.bubble              { padding: 8px 11px; }
```

JavaScript functions:
```javascript
function toggleMobileSidebar() {
  const isOpen = $('sidebar').classList.contains('mobile-open');
  $('sidebar').classList.toggle('mobile-open', !isOpen);
  $('sidebar-overlay').classList.toggle('visible', !isOpen);
}
function closeMobileSidebar() {
  $('sidebar').classList.remove('mobile-open');
  $('sidebar-overlay').classList.remove('visible');
}
```

The `Escape` key handler also calls `closeMobileSidebar()`.

**Before / After on mobile (375px screen):**

```
Before:                          After:
┌────────┬───────────┐           ┌──────────────────────┐
│Sidebar │  Chat     │           │ ☰ Chat title   OPEN  │
│(240px) │  (135px!) │           │──────────────────────│
│        │           │           │                      │
│        │ (unusable)│           │  (full 375px chat)   │
│        │           │           │                      │
│        │           │           │ [                  ] │
└────────┴───────────┘           └──────────────────────┘
                                 Sidebar slides in on ☰ tap
```

---

### Gap 6 — Edit / Resend User Messages

#### Problem

If a user sent a message with a typo, wrong ticker, or incomplete question, their only option was to retype it from scratch in the input field. For long, detailed prompts this was frustrating.

#### Fix

**File: `static/index.html`**

An `✏ Edit` button is created for every user message bubble in `appendMsg()`:

```javascript
if (role === 'user') {
  const editBtn         = document.createElement('button');
  editBtn.className     = 'msg-edit-btn';
  editBtn.textContent   = '✏ Edit';
  editBtn.title         = 'Edit and resend this message';
  editBtn.onclick       = () => {
    const inp = $('user-input');
    inp.value = content;          // fills original text into input
    autoResize(inp);
    inp.focus();
    inp.setSelectionRange(inp.value.length, inp.value.length);  // cursor at end
  };
  wrap.appendChild(editBtn);
}
```

The button is hidden by default (`display: none`) and appears on hover via CSS:

```css
.msg.user:hover .msg-edit-btn { display: inline-block; }
```

Clicking "✏ Edit" copies the message text into the textarea with the cursor positioned at the end, ready to modify. The user can then edit inline and press Enter to send — the edited message will be appended as a new message in the conversation.

---

### Gap 7 — Scroll-to-Bottom Button

#### Problem

In a long conversation, after scrolling up to re-read an earlier response, the user had to manually scroll all the way back down to see the latest response or use the input field. There was no quick way to jump to the bottom.

#### Fix

**File: `static/index.html`**

A floating `↓` button was added as a sibling of the `#messages` panel:

```html
<button id="scroll-bottom-btn" onclick="scrollBottom()" title="Scroll to bottom">↓</button>
```

CSS positions it fixed relative to the messages panel:

```css
#scroll-bottom-btn {
  display: none;
  position: absolute;
  bottom: 76px; right: 20px;
  background: #0d1e33;
  border: 1px solid #1a6fd4;
  border-radius: 50%;
  width: 34px; height: 34px;
  color: #1a6fd4;
  box-shadow: 0 2px 10px rgba(0,0,0,0.5);
  transition: background 0.15s, transform 0.15s;
}
#scroll-bottom-btn.visible { display: flex; }
#scroll-bottom-btn:hover   { background: #152236; transform: translateY(2px); }
```

A scroll event listener on `#messages` toggles the `.visible` class:

```javascript
(function () {
  const msgs = $('messages');
  const btn  = $('scroll-bottom-btn');
  msgs.addEventListener('scroll', () => {
    const distFromBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight;
    btn.classList.toggle('visible', distFromBottom > 180);
  });
})();
```

The button appears when the user is more than 180px from the bottom, disappears when they scroll back down. Clicking calls the existing `scrollBottom()` function which sets `scrollTop = scrollHeight`.

---

## 4. Complete Summary Table

### Existing UX measures

| Feature | Where | What it does |
|---|---|---|
| Consistent color system | CSS | Semantic green/red/blue applied everywhere |
| Tabular numerals | CSS | Financial figures align at decimal point |
| Micro-transitions | CSS | 0.12–0.22s ease on all interactive elements |
| Collapsible sidebar | HTML + JS | Full viewport width when collapsed; state persists |
| Resizable sidebar | JS | Drag handle, 160–480px, saved to localStorage |
| Session history | JS | Reverse-chronological, with timestamps |
| Session search | JS | Live filter with keyword `<mark>` highlighting |
| Delete with confirmation | JS | Hidden on hover, modal dialog, red destructive button |
| RBAC tab visibility | JS | Trading/Analytics hidden for viewers |
| Market status badge | JS | OPEN/CLOSED based on NYSE hours, refreshes per minute |
| Chat bubble geometry | CSS | User = blue right, Assistant = dark left |
| Auto-growing textarea | JS | 44px–150px based on scrollHeight |
| Enter to send | JS | Shift+Enter for newline |
| Send button disabled during stream | JS | Prevents double-submission |
| Empty state | HTML | Placeholder when no messages |
| Token streaming | JS | SSE ReadableStream, re-renders markdown on each token |
| Typing dots animation | CSS | Staggered wave for 3 dots |
| Inline progress labels | JS | Per-pipeline step labels alongside dots |
| Cross-pipeline cue | Backend | "Cross-checking 10-K insights…" |
| Pipeline abort message | Backend | Names failed stage, suggests fix |
| Agent-trade sync | JS | SSE event + text-parsing fallback, no refresh needed |
| Markdown rendering | JS | marked.js with GFM + line breaks |
| Inline chart images | JS | Base64 PNG via `image` SSE event |
| Signal badge widget | JS | BUY/SELL/HOLD pill + animated confidence bar |
| Citation chips + hover tooltip | JS | Source passage preview on hover |
| Authenticated PDF download | JS | Delegated click, Blob URL, status text |
| 👍/👎 feedback | JS | Fade-in, visual selected state, POST to /api/feedback |
| Prompt library (18 categories) | JS | 100+ templates, categorised |
| Company ticker selector | JS | {TICKER}/{COMPANY} substitution in all prompts |
| Investment Research lock | JS | Dimmed when non-MSFT company selected |
| Prompt search | JS | Real-time chip filter, empty state |
| Per-user trade isolation | JS | `trades_{username}` localStorage key |
| Sample trade purge | JS | Auto-removes legacy s1–s5 seed trades |
| Manual trade entry | HTML + JS | Modal form with validation |
| BUY/SELL badges | CSS | Green/red color-coded pill labels |
| Analytics summary cards | JS | Total, Cash, Positions, P&L |
| Allocation donut chart | Chart.js | Per-ticker percentage breakdown |
| Holdings table | JS | Shares, avg cost, live price, gain/loss |
| Live price cards | JS | Per-held-ticker price + daily change |
| Portfolio value trend | Chart.js | 3-month line chart |
| Individual stock trends | Chart.js | Multi-line per held ticker |
| Role badge + avatar | HTML | Color-coded, shows username initial |
| Session ownership | Backend | 403 if user doesn't own the session |

### New fixes

| Gap | Feature | Files | What it does |
|---|---|---|---|
| 1 | Keyboard shortcuts | `index.html` | `Ctrl+K` → prompt library, `Escape` → close any modal |
| 2 | Copy button | `index.html` | Copies raw markdown; green ✓ for 2s on success |
| 3 | Session rename | `web_server.py`, `index.html` | Double-click title → inline input; `PATCH /api/sessions/{id}` persists |
| 4 | Follow-up chips | `web_server.py`, `index.html` | Pipeline-aware suggestions in `done` SSE; chips fill input with full query |
| 5 | Mobile layout | `index.html` | Slide-in sidebar, hamburger button, overlay, responsive grid at 768px/480px |
| 6 | Edit / resend | `index.html` | `✏ Edit` on user bubble hover → copies text to input, cursor at end |
| 7 | Scroll-to-bottom | `index.html` | Floating `↓` button appears when >180px from bottom |

---

## 5. Known Limitations

| Limitation | Impact |
|---|---|
| Edit/resend appends a new message | The original message is still visible; conversation history grows rather than being rewritten |
| Follow-up ticker extraction is regex-based | If the response doesn't contain a clear ticker symbol, the follow-up query uses `AAPL` as a default |
| Session rename is local-only if the PATCH fails | Network errors silently leave the server title unchanged while the UI shows the new name |
| Mobile sidebar uses `position: fixed` | On some older mobile browsers, `position: fixed` inside a `transform` parent can cause z-index stacking issues |
| Copy button requires Clipboard API | Older browsers or non-HTTPS contexts will hit the `catch` path and show `✕ Failed` |
| Keyboard shortcuts conflict | `Ctrl+K` is used by some browsers (e.g. Firefox focus bar) — `e.preventDefault()` suppresses the default but may surprise users |
| No swipe-to-close on mobile sidebar | Mobile users must tap the overlay or press `Escape`; swipe gestures are not implemented |
