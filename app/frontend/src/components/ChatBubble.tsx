import { marked } from "marked";
import { mdSafe } from "../lib/markdown";
import type { Citation, SignalAction } from "../api/types";

export interface Msg {
  id: number;
  role: "user" | "ai";
  text: string;
  images: string[];
  sources: Citation[];
  signal: { action: SignalAction; ticker: string; confidence_pct: number } | null;
  progress: string;
  done: boolean;
  feedback: "up" | "down" | null;
}

interface Props {
  m: Msg;
  onFeedback: (id: number, rating: "up" | "down", text: string) => void;
}

export function ChatBubble({ m, onFeedback }: Props) {
  if (m.role === "user") return <div className="m user">{m.text}</div>;

  // Chart images are markdown we generate server-side (trusted base64) — DOMPurify
  // would strip their data: URIs, so they're parsed but not sanitized. The model's
  // prose answer IS sanitized via mdSafe.
  const imgsHtml = m.images.map((md) => marked.parse(md, { async: false }) as string).join("");
  const showProgress = !m.text && !imgsHtml && !m.signal;

  return (
    <div className="m ai">
      {m.signal && (
        <div className="sigmini">
          <span className={"pill " + m.signal.action}>{m.signal.action}</span>
          <span className="num" style={{ color: "var(--soft)" }}>
            {m.signal.ticker} · {Math.round(m.signal.confidence_pct)}%
          </span>
        </div>
      )}

      {imgsHtml && <div dangerouslySetInnerHTML={{ __html: imgsHtml }} />}

      {m.text ? (
        <div dangerouslySetInnerHTML={{ __html: mdSafe(m.text) }} />
      ) : (
        showProgress && <span className="prog">{m.progress || "…"}</span>
      )}

      {m.sources.length > 0 && (
        <details className="sources">
          <summary>📎 Sources ({m.sources.length})</summary>
          <ul>
            {m.sources.map((s, i) => (
              <li key={i}>
                <b>{s.label}</b> — {s.detail}
              </li>
            ))}
          </ul>
        </details>
      )}

      {m.done && m.text && (
        <div className="fb">
          <button
            className={m.feedback === "up" ? "on" : ""}
            title="Helpful"
            onClick={() => onFeedback(m.id, "up", m.text)}
          >
            👍
          </button>
          <button
            className={m.feedback === "down" ? "on" : ""}
            title="Not helpful"
            onClick={() => onFeedback(m.id, "down", m.text)}
          >
            👎
          </button>
          {m.feedback && <span className="thanks">thanks!</span>}
        </div>
      )}
    </div>
  );
}
