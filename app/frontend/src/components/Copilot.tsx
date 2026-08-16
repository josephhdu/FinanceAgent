import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { cls, pctTxt, REC_TITLE } from "../lib/format";
import type { ChatEvent, SessionMeta, Signal, StoredMessage } from "../api/types";
import { ChatBubble, type Msg } from "./ChatBubble";

const newId = () => crypto.randomUUID().replace(/-/g, "");

const CHIPS = ["Why this signal?", "Risk factors", "Forecast chart", "Compare to NVDA"];

interface Props {
  sel: string;
  signal: Signal | null;
  onTurnComplete: () => void;
}

export function Copilot({ sel, signal, onTurnComplete }: Props) {
  const { get, del } = useApi();
  const { token } = useAuth();

  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [panelOpen, setPanelOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [sessionId, setSessionId] = useState<string>(() => {
    const s = localStorage.getItem("financeai_sid") || newId();
    localStorage.setItem("financeai_sid", s);
    return s;
  });

  const chatRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const loadSessions = useCallback(async () => {
    try {
      const d = await get<{ sessions: SessionMeta[] }>("/api/sessions");
      setSessions(d.sessions || []);
    } catch {
      /* ignore */
    }
  }, [get]);

  const rehydrate = useCallback(
    async (sid: string) => {
      try {
        const d = await get<{ messages: StoredMessage[] }>(`/api/sessions/${sid}/messages`);
        setMessages(
          (d.messages || []).map((m, i) => ({
            id: i,
            role: m.role === "user" ? "user" : "ai",
            text: m.text,
            images: [],
            sources: [],
            signal: null,
            progress: "",
            done: true,
            feedback: null,
          })),
        );
      } catch {
        /* ignore */
      }
    },
    [get],
  );

  // Restore the last conversation + session list on mount.
  useEffect(() => {
    rehydrate(sessionId);
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const newChat = useCallback(() => {
    const sid = newId();
    localStorage.setItem("financeai_sid", sid);
    setSessionId(sid);
    setMessages([]);
    setPanelOpen(false);
    loadSessions();
  }, [loadSessions]);

  const openSession = useCallback(
    async (id: string) => {
      localStorage.setItem("financeai_sid", id);
      setSessionId(id);
      await rehydrate(id);
      setPanelOpen(false);
    },
    [rehydrate],
  );

  const deleteSession = useCallback(
    async (id: string) => {
      try {
        await del(`/api/sessions/${id}`);
      } catch {
        /* ignore */
      }
      if (id === sessionId) newChat();
      else loadSessions();
    },
    [del, sessionId, newChat, loadSessions],
  );

  const sendFeedback = useCallback(
    (msgId: number, rating: "up" | "down", text: string) => {
      setMessages((ms) => ms.map((m) => (m.id === msgId ? { ...m, feedback: rating } : m)));
      fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ session_id: sessionId, rating, message: text.slice(0, 500) }),
      }).catch(() => {});
    },
    [token, sessionId],
  );

  const askAI = useCallback(
    async (text: string) => {
      setBusy(true);
      const aiId = Date.now() + 1;
      setMessages((ms) => [
        ...ms,
        { id: Date.now(), role: "user", text, images: [], sources: [], signal: null, progress: "", done: true, feedback: null },
        { id: aiId, role: "ai", text: "", images: [], sources: [], signal: null, progress: "", done: false, feedback: null },
      ]);
      const patch = (fn: (m: Msg) => Msg) =>
        setMessages((ms) => ms.map((m) => (m.id === aiId ? fn(m) : m)));

      try {
        const resp = await fetch(`/api/chat/${sessionId}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ message: text }),
        });
        if (resp.status === 401 || !resp.body) {
          patch((m) => ({ ...m, progress: "Session expired — sign in again.", done: true }));
          return;
        }
        const reader = resp.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const parts = buf.split("\n\n");
          buf = parts.pop() || "";
          for (const part of parts) {
            const line = part.replace(/^data: /, "").trim();
            if (!line) continue;
            let ev: ChatEvent;
            try {
              ev = JSON.parse(line);
            } catch {
              continue;
            }
            if (ev.type === "progress") patch((m) => ({ ...m, progress: ev.text }));
            else if (ev.type === "signal")
              patch((m) => ({ ...m, signal: { action: ev.action, ticker: ev.ticker, confidence_pct: ev.confidence_pct } }));
            else if (ev.type === "image") patch((m) => ({ ...m, images: [...m.images, ev.markdown] }));
            else if (ev.type === "citations") patch((m) => ({ ...m, sources: ev.sources || [] }));
            else if (ev.type === "token") patch((m) => ({ ...m, text: m.text + ev.text }));
            else if (ev.type === "error") patch((m) => ({ ...m, text: m.text + "\n\n**Error:** " + ev.text }));
            else if (ev.type === "done") {
              patch((m) => ({ ...m, done: true }));
              onTurnComplete();
            }
          }
        }
        patch((m) => ({ ...m, done: true }));
        loadSessions();
      } catch {
        patch((m) => ({ ...m, progress: "Connection error.", done: true }));
      } finally {
        setBusy(false);
      }
    },
    [sessionId, token, onTurnComplete, loadSessions],
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    const t = input.trim();
    if (t) {
      askAI(t);
      setInput("");
    }
  }

  function chip(label: string) {
    let t = label;
    if (/signal/i.test(label)) t = `Why is ${sel} a ${signal?.action || ""}? Explain the trade signal.`;
    else if (/risk/i.test(label)) t = `What are ${sel}'s risk factors from its 10-K?`;
    else if (/forecast/i.test(label)) t = `Show me a forecast chart for ${sel}`;
    else if (/compare/i.test(label)) t = `Compare ${sel} to NVDA`;
    askAI(t);
  }

  const act = signal?.action || "HOLD";
  const conf = signal ? Math.round(signal.confidence_pct) : null;
  const dr = signal?.drivers;

  return (
    <aside className="copilot">
      <div className="cop-head">
        <span>
          AI Copilot <span className="ctx">· {sel}</span>
        </span>
        <span className="head-actions">
          <button className="hbtn" onClick={newChat} title="Start a new chat">
            ＋ New
          </button>
          <button
            className="hbtn"
            onClick={() => {
              loadSessions();
              setPanelOpen(true);
            }}
            title="Chat history"
          >
            History
          </button>
        </span>
      </div>

      {panelOpen && (
        <div className="session-panel">
          <div className="sp-head">
            <span>Recent chats</span>
            <button onClick={() => setPanelOpen(false)} title="Close">
              ✕
            </button>
          </div>
          <div className="session-list">
            {sessions.length ? (
              sessions.map((s) => (
                <div
                  key={s.session_id}
                  className={"srow" + (s.session_id === sessionId ? " on" : "")}
                  onClick={() => openSession(s.session_id)}
                >
                  <span className="st">{s.title}</span>
                  <span className="stime">
                    {new Date(s.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </span>
                  <button
                    className="del"
                    title="Delete chat"
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteSession(s.session_id);
                    }}
                  >
                    🗑
                  </button>
                </div>
              ))
            ) : (
              <div className="sp-empty">
                No saved chats yet.
                <br />
                Ask the copilot anything to start one.
              </div>
            )}
          </div>
        </div>
      )}

      <div className="signal-card">
        <div className="sig-top">
          <span className={"pill " + act}>{act}</span>
          <span className="sig-tk num">{sel}</span>
          <span className="sig-conf num">{conf != null ? conf + "%" : "—"}</span>
        </div>
        <div className="sig-bar">
          <span style={{ width: (conf || 0) + "%" }} />
        </div>
        <ul className="sig-drivers">
          {dr ? (
            <>
              <li>
                <span>14-day forecast</span>
                <b className={dr.forecast_return_14d_pct != null ? "num " + cls(dr.forecast_return_14d_pct) : ""}>
                  {dr.forecast_return_14d_pct != null ? pctTxt(dr.forecast_return_14d_pct) : "—"}
                </b>
              </li>
              <li>
                <span>Analyst consensus</span>
                <b>{REC_TITLE[dr.analyst_recommendation || ""] || dr.analyst_recommendation || "—"}</b>
              </li>
              <li>
                <span>Price-target upside</span>
                <b className={dr.upside_pct != null ? "num " + cls(dr.upside_pct) : ""}>
                  {dr.upside_pct != null ? pctTxt(dr.upside_pct) : "—"}
                </b>
              </li>
            </>
          ) : (
            <li>
              <span className="muted">No signal available.</span>
            </li>
          )}
        </ul>
      </div>

      <div className="chips">
        {CHIPS.map((c) => (
          <button key={c} onClick={() => chip(c)}>
            {c}
          </button>
        ))}
      </div>

      <div className="chat" ref={chatRef}>
        {messages.map((m) => (
          <ChatBubble key={m.id} m={m} onFeedback={sendFeedback} />
        ))}
      </div>

      <form className="composer" onSubmit={submit}>
        <input
          placeholder={`Ask about ${sel}…`}
          autoComplete="off"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" disabled={busy}>
          Send
        </button>
      </form>
    </aside>
  );
}
