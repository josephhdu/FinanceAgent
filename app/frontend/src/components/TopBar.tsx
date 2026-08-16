import { arrow, cls } from "../lib/format";
import type { Quote } from "../api/types";

interface Props {
  page: "markets" | "portfolio";
  onPage: (p: "markets" | "portfolio") => void;
  watchlist: string[];
  quotes: Record<string, Quote>;
  username: string;
  onLogout: () => void;
}

export function TopBar({ page, onPage, watchlist, quotes, username, onLogout }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        Finance<span>AI</span>
      </div>
      <nav className="topnav">
        <button className={page === "markets" ? "on" : ""} onClick={() => onPage("markets")}>
          Markets
        </button>
        <button className={page === "portfolio" ? "on" : ""} onClick={() => onPage("portfolio")}>
          Portfolio
        </button>
      </nav>
      <div className="ticker-strip">
        {watchlist.map((t) => {
          const q = quotes[t];
          const p = q?.pct ?? null;
          return (
            <span className="t" key={t}>
              {t} <b className="num">{q?.last != null ? q.last.toFixed(2) : "—"}</b>{" "}
              <span className={"num " + cls(p)}>
                {p != null ? arrow(p) + Math.abs(p).toFixed(2) + "%" : ""}
              </span>
            </span>
          );
        })}
      </div>
      <div className="user">
        <span className="dot-live" /> live data
        <span className="who">{username ? "@" + username : ""}</span>
        <button className="link" onClick={onLogout}>
          log out
        </button>
      </div>
    </header>
  );
}
