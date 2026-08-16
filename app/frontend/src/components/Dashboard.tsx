import { useCallback, useEffect, useState } from "react";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { money } from "../lib/format";
import type { Action, Portfolio, Quote, Signal, StockDetail, Trade } from "../api/types";
import { TopBar } from "./TopBar";
import { Watchlist } from "./Watchlist";
import { MarketsPage } from "./MarketsPage";
import { PortfolioPage } from "./PortfolioPage";
import { Copilot } from "./Copilot";
import { TradeModal, type ModalState } from "./TradeModal";
import { Toast, type ToastState } from "./Toast";

const DEFAULT_WL = ["AMD", "MSFT", "NVDA", "SNOW", "AAPL", "META"];

function loadWatchlist(): string[] {
  try {
    const s = JSON.parse(localStorage.getItem("financeai_wl") || "null");
    if (Array.isArray(s) && s.length) return s;
  } catch {
    /* fall through to default */
  }
  return DEFAULT_WL.slice();
}

export function Dashboard() {
  const { get, post } = useApi();
  const { username, logout } = useAuth();

  const [page, setPage] = useState<"markets" | "portfolio">("markets");
  const [watchlist, setWatchlist] = useState<string[]>(loadWatchlist);
  const [sel, setSel] = useState<string>(() => loadWatchlist()[0] || "AMD");
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [signal, setSignal] = useState<Signal | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [modal, setModal] = useState<ModalState | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  const showToast = useCallback((message: string, kind: "ok" | "bad") => {
    setToast({ message, kind, id: Date.now() });
  }, []);

  useEffect(() => {
    localStorage.setItem("financeai_wl", JSON.stringify(watchlist));
  }, [watchlist]);

  const loadQuotes = useCallback(async () => {
    try {
      const d = await get<{ quotes: Quote[] }>(`/api/quotes?tickers=${watchlist.join(",")}`);
      const map: Record<string, Quote> = {};
      (d.quotes || []).forEach((q) => (map[q.ticker] = q));
      setQuotes(map);
    } catch {
      /* transient; keep last quotes */
    }
  }, [get, watchlist]);

  const loadAccount = useCallback(async () => {
    try {
      setPortfolio(await get<Portfolio>("/api/portfolio"));
    } catch {
      /* ignore */
    }
    try {
      const t = await get<{ trades: Trade[] }>("/api/trades?limit=20");
      setTrades(t.trades || []);
    } catch {
      /* ignore */
    }
  }, [get]);

  const loadSignal = useCallback(
    async (tk: string) => {
      try {
        const s = await get<Signal>(`/api/signal/${tk}`);
        setSignal(s.status === "success" ? s : null);
      } catch {
        /* ignore */
      }
    },
    [get],
  );

  // Quotes: on mount, whenever the watchlist changes, and every 60s.
  useEffect(() => {
    loadQuotes();
  }, [loadQuotes]);
  useEffect(() => {
    const id = setInterval(() => loadQuotes(), 60_000);
    return () => clearInterval(id);
  }, [loadQuotes]);

  // Account once on mount.
  useEffect(() => {
    loadAccount();
  }, [loadAccount]);

  // Selected stock: header/stats + signal.
  useEffect(() => {
    if (!sel) return;
    let cancelled = false;
    get<StockDetail>(`/api/stock/${sel}`)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => {});
    loadSignal(sel);
    return () => {
      cancelled = true;
    };
  }, [sel, get, loadSignal]);

  const selectTicker = useCallback((tk: string) => {
    setSel(tk);
    setPage("markets");
  }, []);

  const addTicker = useCallback(
    async (raw: string): Promise<string | null> => {
      const sym = (raw || "").trim().toUpperCase().replace(/[^A-Z.]/g, "");
      if (!sym) return null;
      if (watchlist.includes(sym)) return `${sym} is already in your list`;
      try {
        const d = await get<{ quotes: Quote[] }>(`/api/quotes?tickers=${encodeURIComponent(sym)}`);
        const q = (d.quotes || [])[0];
        if (!q || q.last == null) return `Couldn't find "${sym}"`;
      } catch {
        return "Lookup failed";
      }
      setWatchlist((w) => [...w, sym]);
      selectTicker(sym);
      return null;
    },
    [get, watchlist, selectTicker],
  );

  const removeTicker = useCallback(
    (sym: string) => {
      setWatchlist((w) => {
        const next = w.filter((t) => t !== sym);
        if (sel === sym && next.length) setSel(next[0]);
        return next;
      });
    },
    [sel],
  );

  const openModal = useCallback(
    (side: Action, shares: number) => {
      const price = detail?.last || 0;
      if (!price) {
        showToast("Price still loading — try again in a moment", "bad");
        return;
      }
      setModal({ ticker: sel, side, shares: Math.max(1, shares || 1), price });
    },
    [detail, sel, showToast],
  );

  const confirmTrade = useCallback(
    async (m: ModalState): Promise<boolean> => {
      try {
        const res = await post<{
          detail?: string;
          action: string;
          shares: number;
          ticker: string;
          price: number;
          trade_id: string;
        }>("/api/trade", { ticker: m.ticker, action: m.side, shares: m.shares });
        if (!res.ok) {
          showToast(res.data.detail || `Trade failed (${res.status})`, "bad");
          return false;
        }
        const d = res.data;
        showToast(`${d.action} ${d.shares} ${d.ticker} @ ${money(d.price)} · ${d.trade_id}`, "ok");
        loadAccount();
        return true;
      } catch {
        showToast("Connection error", "bad");
        return false;
      }
    },
    [post, showToast, loadAccount],
  );

  return (
    <div id="app">
      <TopBar
        page={page}
        onPage={setPage}
        watchlist={watchlist}
        quotes={quotes}
        username={username}
        onLogout={logout}
      />

      <Watchlist
        watchlist={watchlist}
        quotes={quotes}
        sel={sel}
        portfolio={portfolio}
        onSelect={selectTicker}
        onAdd={addTicker}
        onRemove={removeTicker}
      />

      <main className="workspace">
        {page === "markets" ? (
          <MarketsPage sel={sel} detail={detail} signal={signal} onPlaceOrder={openModal} />
        ) : (
          <PortfolioPage portfolio={portfolio} trades={trades} />
        )}
      </main>

      <Copilot
        sel={sel}
        signal={signal}
        onTurnComplete={() => {
          loadAccount();
          loadSignal(sel);
        }}
      />

      {modal && (
        <TradeModal
          state={modal}
          signal={signal}
          onCancel={() => setModal(null)}
          onConfirm={async () => {
            const ok = await confirmTrade(modal);
            if (ok) setModal(null);
            return ok;
          }}
        />
      )}

      <Toast toast={toast} />
    </div>
  );
}
