import { useState } from "react";
import { money } from "../lib/format";
import type { Action, Signal } from "../api/types";

export interface ModalState {
  ticker: string;
  side: Action;
  shares: number;
  price: number;
}

interface Props {
  state: ModalState;
  signal: Signal | null;
  onCancel: () => void;
  onConfirm: () => Promise<boolean>;
}

export function TradeModal({ state, signal, onCancel, onConfirm }: Props) {
  const [placing, setPlacing] = useState(false);
  const act = signal?.action || "—";
  const conf = signal ? Math.round(signal.confidence_pct) + "%" : "—";

  async function confirm() {
    setPlacing(true);
    const ok = await onConfirm();
    if (!ok) setPlacing(false); // on success the modal unmounts
  }

  return (
    <div
      className="modal-bg"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="modal">
        <h3>Confirm {state.side.toLowerCase()} order</h3>
        <div className="order">
          <span>
            <span className={state.side === "BUY" ? "up" : "down"}>{state.side}</span> {state.ticker}
          </span>
          <span>{money(state.shares * state.price)}</span>
        </div>
        <div className="rows">
          <div className="row">
            <span>Shares</span>
            <b>{state.shares}</b>
          </div>
          <div className="row">
            <span>Est. price</span>
            <b>{money(state.price)}</b>
          </div>
          <div className="row">
            <span>Order type</span>
            <b>Market · paper</b>
          </div>
        </div>
        <div className="sig-line">
          <span className={"pill " + act}>{act}</span> AI signal · {conf} confidence
        </div>
        <div className="disc">
          ⚠️ Paper trade — no real money moves. Educational only, not financial advice.
        </div>
        <div className="acts">
          <button className="cancel" onClick={onCancel}>
            Cancel
          </button>
          <button className={"confirm " + state.side} disabled={placing} onClick={confirm}>
            {placing ? "Placing…" : `Confirm ${state.side.toLowerCase()}`}
          </button>
        </div>
      </div>
    </div>
  );
}
