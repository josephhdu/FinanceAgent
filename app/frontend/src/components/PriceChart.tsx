import { useEffect, useRef, useState } from "react";
import {
  createChart,
  LineStyle,
  type AreaData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import { useApi } from "../api/useApi";
import type { History } from "../api/types";

const TIMEFRAMES = ["1D", "1W", "1M", "3M", "1Y"];
const toTime = (iso: string) => Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;

export function PriceChart({ sel }: { sel: string }) {
  const { get } = useApi();
  const [tf, setTf] = useState("1M");
  const [showForecast, setShowForecast] = useState(true);
  const [hist, setHist] = useState<History | null>(null);
  const [loading, setLoading] = useState(true);

  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const fcRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Fetch history whenever the ticker or timeframe changes.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    get<History>(`/api/history/${sel}?tf=${tf}`)
      .then((d) => {
        if (!cancelled) {
          setHist(d);
          setLoading(false);
        }
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [get, sel, tf]);

  // Create the chart once and dispose on unmount.
  useEffect(() => {
    if (!wrapRef.current) return;
    const chart = createChart(wrapRef.current, {
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor: "#5f7797",
        fontFamily: "ui-monospace, monospace",
        // Hide the floating on-chart TradingView logo; attribution is kept as a
        // discreet credit under the legend instead (see below) per their terms.
        attributionLogo: false,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "#16283f" } },
      rightPriceScale: { borderColor: "#20364f" },
      timeScale: { borderColor: "#20364f", timeVisible: false },
      crosshair: {
        vertLine: { color: "#3a5170", width: 1, style: LineStyle.Solid, labelBackgroundColor: "#13203a" },
        horzLine: { color: "#3a5170", labelBackgroundColor: "#13203a" },
      },
    });
    areaRef.current = chart.addAreaSeries({
      lineColor: "#3ce7f5",
      topColor: "rgba(60,231,245,0.26)",
      bottomColor: "rgba(60,231,245,0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    fcRef.current = chart.addLineSeries({
      color: "#4d8dff",
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
      areaRef.current = null;
      fcRef.current = null;
    };
  }, []);

  // Push data whenever history or the forecast toggle changes.
  useEffect(() => {
    const area = areaRef.current;
    const fc = fcRef.current;
    const chart = chartRef.current;
    if (!area || !fc || !chart) return;

    const pts = hist?.points ?? [];
    const seen = new Set<number>();
    const areaData: AreaData[] = [];
    for (const p of pts) {
      const t = toTime(p.t);
      if (seen.has(t)) continue; // lightweight-charts requires strictly-ascending unique times
      seen.add(t);
      areaData.push({ time: t, value: p.c });
    }
    area.setData(areaData);

    const fcPts = (showForecast ? hist?.forecast : []) ?? [];
    if (fcPts.length && pts.length) {
      // Anchor the dashed forecast to the last real point so the line is continuous.
      const fseen = new Set<number>();
      const seg: LineData[] = [];
      for (const p of [pts[pts.length - 1], ...fcPts]) {
        const t = toTime(p.t);
        if (fseen.has(t)) continue;
        fseen.add(t);
        seg.push({ time: t, value: p.c });
      }
      fc.setData(seg);
    } else {
      fc.setData([]);
    }
    chart.timeScale().fitContent();
  }, [hist, showForecast]);

  const noData = !loading && (!hist || hist.points.length === 0);

  return (
    <section className="card chart-card">
      <div className="chart-head">
        <div className="chart-title">{sel} · price</div>
        <div className="chart-controls">
          <div className="seg">
            {TIMEFRAMES.map((t) => (
              <button key={t} className={t === tf ? "on" : ""} onClick={() => setTf(t)}>
                {t}
              </button>
            ))}
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={showForecast}
              onChange={(e) => setShowForecast(e.target.checked)}
            />{" "}
            forecast
          </label>
        </div>
      </div>
      <div className="chart-wrap">
        <div className="lwchart" ref={wrapRef} />
        {(loading || noData) && (
          <div className="chart-msg">{loading ? "Loading…" : "No price history available."}</div>
        )}
      </div>
      <div className="chart-legend">
        <span>
          <i className="sw cyan" /> price history
        </span>
        <span>
          <i className="sw blue dash" /> 14-day OLS forecast
        </span>
        <a
          className="attr"
          href="https://www.tradingview.com"
          target="_blank"
          rel="noreferrer noopener"
        >
          Charts by TradingView
        </a>
      </div>
    </section>
  );
}
