import { useState } from "react";
import { cls, money, pctTxt } from "../lib/format";
import type { Portfolio, Trade } from "../api/types";

interface Props {
  portfolio: Portfolio | null;
  trades: Trade[];
}

export function PortfolioPage({ portfolio, trades }: Props) {
  const [tab, setTab] = useState<"positions" | "history">("positions");
  const k = portfolio?.kpis;
  const positions = portfolio?.positions ?? [];

  const kpis: [string, string, number | null, string][] = [
    ["Portfolio value", money(k?.portfolio_value), null, ""],
    ["Total P/L", money(k?.total_pl), k?.total_pl ?? null, pctTxt(k?.total_pl_pct) + " all-time"],
    ["Cash", money(k?.cash), null, "buying power"],
    ["Invested", money(k?.invested), null, positions.length + " open"],
  ];

  return (
    <div className="page">
      <div className="page-title">
        <h1>Portfolio</h1>
        <span className="page-sub">Paper account · live-priced</span>
      </div>

      <section className="kpis">
        {kpis.map(([label, val, dir, sub]) => (
          <div className="kpi" key={label}>
            <div className="kpi-label">{label}</div>
            <div className={"kpi-val num " + (dir != null ? cls(dir) : "")}>{val}</div>
            <div className={"kpi-delta " + (dir != null ? cls(dir) : "muted")}>{sub}</div>
          </div>
        ))}
      </section>

      <div className="card panel">
        <div className="tabs">
          <button className={tab === "positions" ? "on" : ""} onClick={() => setTab("positions")}>
            Positions
          </button>
          <button className={tab === "history" ? "on" : ""} onClick={() => setTab("history")}>
            Trade history
          </button>
        </div>

        {tab === "positions" ? (
          <div className="tab-body">
            {positions.length ? (
              <table className="grid">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th className="r">Shares</th>
                    <th className="r">Avg cost</th>
                    <th className="r">Mkt price</th>
                    <th className="r">Value</th>
                    <th className="r">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.map((p) => (
                    <tr key={p.ticker}>
                      <td className="tk">{p.ticker}</td>
                      <td className="r num">{p.shares}</td>
                      <td className="r num">{money(p.avg_cost)}</td>
                      <td className="r num">{money(p.market_price)}</td>
                      <td className="r num">{money(p.value)}</td>
                      <td className={"r num " + cls(p.pl)}>
                        {(p.pl >= 0 ? "+" : "") + money(p.pl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty">
                No open positions. Ask the AI copilot for a signal, then approve a paper trade.
              </div>
            )}
          </div>
        ) : (
          <div className="tab-body">
            {trades.length ? (
              <table className="grid">
                <thead>
                  <tr>
                    <th>Trade ID</th>
                    <th>Action</th>
                    <th className="r">Shares</th>
                    <th className="r">Price</th>
                    <th className="r">When</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t) => (
                    <tr key={t.trade_id}>
                      <td className="mono-sm">{t.trade_id}</td>
                      <td>
                        <span className={"tag " + t.action.toLowerCase()}>{t.action}</span>
                      </td>
                      <td className="r num">{t.shares}</td>
                      <td className="r num">{money(t.price)}</td>
                      <td className="r muted">
                        {new Date(t.timestamp).toLocaleString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty">No trades yet.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
