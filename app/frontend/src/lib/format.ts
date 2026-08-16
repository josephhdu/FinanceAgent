// Display formatters shared across the dashboard. Ported from the original UI so
// numbers render identically (monospace, tabular, em-dash for missing values).

export const money = (n: number | null | undefined): string =>
  n == null || Number.isNaN(n) ? "—" : (n < 0 ? "-" : "") + "$" + Math.abs(n).toFixed(2);

export const pctTxt = (n: number | null | undefined): string =>
  n == null || Number.isNaN(n) ? "—" : (n >= 0 ? "+" : "") + n.toFixed(2) + "%";

export const arrow = (n: number): string => (n >= 0 ? "▲" : "▼");

export type Dir = "muted" | "up" | "down";
export const cls = (n: number | null | undefined): Dir =>
  n == null ? "muted" : n >= 0 ? "up" : "down";

// Analyst recommendationKey → human label.
export const REC_TITLE: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  outperform: "Outperform",
  hold: "Hold",
  underperform: "Underperform",
  sell: "Sell",
  strong_sell: "Strong Sell",
};
