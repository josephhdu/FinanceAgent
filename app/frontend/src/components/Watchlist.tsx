import { useState, type FormEvent } from "react";
import { arrow, cls, money } from "../lib/format";
import type { Portfolio, Quote } from "../api/types";

interface Props {
  watchlist: string[];
  quotes: Record<string, Quote>;
  sel: string;
  portfolio: Portfolio | null;
  onSelect: (tk: string) => void;
  onAdd: (raw: string) => Promise<string | null>;
  onRemove: (tk: string) => void;
}

export function Watchlist({ watchlist, quotes, sel, portfolio, onSelect, onAdd, onRemove }: Props) {
  const [input, setInput] = useState("");
  const [err, setErr] = useState("");

  async function add(e: FormEvent) {
    e.preventDefault();
    setErr("");
    const msg = await onAdd(input);
    if (msg) setErr(msg);
    else setInput("");
  }

  return (
    <aside className="watchlist">
      <div className="rail-head">
        <span>Watchlist</span>
      </div>
      <div className="watch-rows">
        {watchlist.map((t) => {
          const q = quotes[t];
          const p = q?.pct ?? null;
          return (
            <div
              key={t}
              className={"wl" + (t === sel ? " on" : "")}
              onClick={() => onSelect(t)}
            >
              <span className="tk">{t}</span>
              <span className="q">
                <div className="p num">{q?.last != null ? q.last.toFixed(2) : "—"}</div>
                <div className={"c num " + cls(p)}>
                  {p != null ? arrow(p) + Math.abs(p).toFixed(2) + "%" : "—"}
                </div>
              </span>
              <button
                className="rm"
                title={`Remove ${t}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onRemove(t);
                }}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>

      <form className="wl-add" onSubmit={add}>
        <input
          placeholder="Add ticker…"
          autoComplete="off"
          maxLength={6}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button type="submit" title="Add to watchlist">
          +
        </button>
      </form>
      <span className="wl-add-err">{err}</span>

      <div className="rail-head" style={{ marginTop: "auto" }}>
        Account
      </div>
      <div className="acct">
        <div className="acct-row">
          <span>Buying power</span>
          <b className="num">{money(portfolio?.kpis.cash)}</b>
        </div>
        <div className="acct-row">
          <span>Positions</span>
          <b className="num">{portfolio ? portfolio.positions.length : "—"}</b>
        </div>
      </div>
    </aside>
  );
}
