import type { Dispatch, SetStateAction } from "react";
import { money } from "../lib/format";
import type { Action, Signal } from "../api/types";

interface Props {
  sel: string;
  side: Action;
  setSide: Dispatch<SetStateAction<Action>>;
  qty: number;
  setQty: Dispatch<SetStateAction<number>>;
  lastPrice: number;
  signal: Signal | null;
  onPlaceOrder: (side: Action, shares: number) => void;
}

export function TradeTicket({ sel, side, setSide, qty, setQty, lastPrice, signal, onPlaceOrder }: Props) {
  const est = (qty || 0) * (lastPrice || 0);
  const act = signal?.action || "HOLD";
  const conf = signal ? Math.round(signal.confidence_pct) : null;

  return (
    <aside className="card ticket">
      <div className="ticket-head">
        Trade ticket · <span className="num">{sel}</span>
      </div>
      <div className="bs-seg">
        <button className={side === "BUY" ? "on" : ""} data-side="BUY" onClick={() => setSide("BUY")}>
          Buy
        </button>
        <button className={side === "SELL" ? "on" : ""} data-side="SELL" onClick={() => setSide("SELL")}>
          Sell
        </button>
      </div>
      <label className="fld">
        <span>Shares</span>
        <input
          className="num"
          inputMode="numeric"
          value={qty}
          onChange={(e) => setQty(Math.max(0, parseInt(e.target.value) || 0))}
        />
      </label>
      <label className="fld">
        <span>Order type</span>
        <span className="num muted">Market · paper</span>
      </label>
      <div className="est">
        <span>Est. cost</span>
        <b className="num">{money(est)}</b>
      </div>
      <button className="btn review" onClick={() => onPlaceOrder(side, qty)}>
        Place order
      </button>
      <div className="mini-sig">
        <div className="mini-sig-top">
          <span className={"pill " + act}>{act}</span>
          <span className="sig-conf num">{conf != null ? conf + "%" : "—"}</span>
        </div>
        <div className="sig-bar">
          <span style={{ width: (conf || 0) + "%" }} />
        </div>
      </div>
      <div className="ticket-note">
        Reviewed against the live AI signal before you confirm. Paper trades only.
      </div>
    </aside>
  );
}
