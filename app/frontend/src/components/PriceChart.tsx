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
        textColor: "#6b7480",
        fontFamily: "ui-monospace, monospace",
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1f2530" } },
      rightPriceScale: { borderColor: "#262d38" },
      timeScale: { borderColor: "#262d38", timeVisible: false },
      crosshair: {
        vertLine: { color: "#3a4453", width: 1, style: LineStyle.Solid, labelBackgroundColor: "#1c2431" },
        horzLine: { color: "#3a4453", labelBackgroundColor: "#1c2431" },
      },
    });
    areaRef.current = chart.addAreaSeries({
      lineColor: "#f0a93d",
      topColor: "rgba(240,169,61,0.28)",
      bottomColor: "rgba(240,169,61,0)",
      lineWidth: 2,
      priceLineVisible: false,
    });
    fcRef.current = chart.addLineSeries({
      color: "#56beb8",
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
          <i className="sw amber" /> price history
        </span>
        <span>
          <i className="sw teal dash" /> 14-day OLS forecast
        </span>
      </div>
    </section>
  );
}
