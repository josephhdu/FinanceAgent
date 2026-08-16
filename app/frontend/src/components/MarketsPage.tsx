import { useState } from "react";
import { arrow, cls, money, pctTxt } from "../lib/format";
import type { Action, Signal, StockDetail } from "../api/types";
import { PriceChart } from "./PriceChart";
import { TradeTicket } from "./TradeTicket";

interface Props {
  sel: string;
  detail: StockDetail | null;
  signal: Signal | null;
  onPlaceOrder: (side: Action, shares: number) => void;
}

function StatStrip({ detail }: { detail: StockDetail | null }) {
  const rows: [string, string][] = [
    ["Last", money(detail?.last)],
    ["Day", pctTxt(detail?.pct)],
    ["Mkt cap", "$" + (detail?.market_cap ?? "—")],
    ["P/E", detail?.pe != null ? String(detail.pe) : "—"],
    ["52-wk low", money(detail?.low_52w)],
    ["52-wk high", money(detail?.high_52w)],
  ];
  return (
    <section className="stat-strip">
      {rows.map(([l, v]) => (
        <div className="stat" key={l}>
          <div className="l">{l}</div>
          <div className="v">{v}</div>
        </div>
      ))}
    </section>
  );
}

export function MarketsPage({ sel, detail, signal, onPlaceOrder }: Props) {
  const [side, setSide] = useState<Action>("BUY");
  const [qty, setQty] = useState<number>(4);
  const day = detail?.pct ?? null;
  const lastPrice = detail?.last ?? 0;

  return (
    <div className="page">
      <section className="stock-head">
        <div className="stock-id">
          <div className="stock-tk num">{sel}</div>
          <div className="stock-nm">{detail?.name || sel}</div>
        </div>
        <div className="stock-price">
          <div className="sp-last num">{money(detail?.last)}</div>
          <div className={"sp-day num " + cls(day)}>
            {day != null
              ? `${arrow(day)} ${money(Math.abs(detail?.change || 0))} · ${pctTxt(day)}`
              : "—"}
          </div>
        </div>
        <div className="stock-actions">
          <button
            className="btn buy"
            onClick={() => {
              setSide("BUY");
              onPlaceOrder("BUY", qty);
            }}
          >
            Buy
          </button>
          <button
            className="btn sell"
            onClick={() => {
              setSide("SELL");
              onPlaceOrder("SELL", qty);
            }}
          >
            Sell
          </button>
        </div>
      </section>

      <StatStrip detail={detail} />

      <div className="markets-grid">
        <PriceChart sel={sel} />
        <TradeTicket
          sel={sel}
          side={side}
          setSide={setSide}
          qty={qty}
          setQty={setQty}
          lastPrice={lastPrice}
          signal={signal}
          onPlaceOrder={onPlaceOrder}
        />
      </div>
    </div>
  );
}
