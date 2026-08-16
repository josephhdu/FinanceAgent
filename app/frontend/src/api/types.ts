// TypeScript mirrors of the FastAPI JSON responses (see web_server.py + market_data.py).

export type Action = "BUY" | "SELL";
export type SignalAction = "BUY" | "SELL" | "HOLD";

export interface Quote {
  ticker: string;
  last: number | null;
  change: number | null;
  pct: number | null;
}

export interface StockDetail {
  ticker: string;
  name: string;
  last: number | null;
  change: number | null;
  pct: number | null;
  market_cap: string;
  pe: number | null;
  low_52w: number | null;
  high_52w: number | null;
  sector?: string | null;
}

/** A price point. `t` is an ISO-8601 timestamp string; `c` is the close. */
export interface PricePoint {
  t: string;
  c: number;
}

export interface History {
  ticker: string;
  timeframe: string;
  points: PricePoint[];
  forecast: PricePoint[];
}

export interface SignalDrivers {
  forecast_return_14d_pct?: number | null;
  analyst_recommendation?: string;
  analyst_score?: number;
  price_target?: number | null;
  upside_pct?: number | null;
}

export interface Signal {
  status: string;
  ticker: string;
  action: SignalAction;
  signal_score?: number;
  confidence_pct: number;
  current_price?: number;
  suggested_shares?: number;
  drivers?: SignalDrivers;
}

export interface Position {
  ticker: string;
  shares: number;
  avg_cost: number;
  market_price: number;
  value: number;
  pl: number;
  pl_pct: number;
}

export interface PortfolioKpis {
  portfolio_value: number;
  invested: number;
  cash: number;
  total_pl: number;
  total_pl_pct: number;
}

export interface Portfolio {
  positions: Position[];
  kpis: PortfolioKpis;
}

export interface Trade {
  trade_id: string;
  timestamp: string;
  ticker: string;
  action: Action;
  shares: number;
  price: number;
  notional: number;
}

export interface SessionMeta {
  session_id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface StoredMessage {
  role: "user" | "assistant";
  text: string;
}

export interface Citation {
  label: string;
  detail: string;
}

/** SSE event shapes streamed by POST /api/chat/{id}. */
export type ChatEvent =
  | { type: "progress"; text: string }
  | { type: "signal"; ticker: string; action: SignalAction; confidence_pct: number }
  | { type: "image"; markdown: string }
  | { type: "citations"; sources: Citation[] }
  | { type: "token"; text: string }
  | { type: "error"; text: string }
  | { type: "done"; title?: string };
