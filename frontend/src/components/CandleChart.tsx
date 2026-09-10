import { useCallback, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type HistogramData,
  type UTCTimestamp,
} from "lightweight-charts";
import { api } from "../api/client";

const INTERVALS = ["1d", "1h", "15m"] as const;
type Interval = (typeof INTERVALS)[number];

// "Live" means refetch-on-a-timer for now. The Trigger/Executor pipeline
// (Phase 6) is what eventually pushes real updates over a WebSocket
// (wired up to the Dashboard in Phase 8) instead of this polling.
const POLL_INTERVAL_MS = 15_000;

interface CandleRow {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  rsi?: number | null;
  ema?: number | null;
  MACD_12_26_9?: number | null;
  MACDh_12_26_9?: number | null;
  MACDs_12_26_9?: number | null;
}

interface CandlesResponse {
  symbol: string;
  interval: string;
  start: string;
  end: string;
  indicators: string[];
  candles: CandleRow[];
}

function rangeFor(interval: Interval): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);
  // yfinance limits how far back intraday history goes, so intraday
  // windows are much shorter than the daily one.
  if (interval === "1d") {
    start.setFullYear(start.getFullYear() - 1);
  } else if (interval === "1h") {
    start.setDate(start.getDate() - 30);
  } else {
    start.setDate(start.getDate() - 5);
  }
  return { start: start.toISOString(), end: end.toISOString() };
}

function toUTCTimestamp(iso: string): UTCTimestamp {
  return Math.floor(new Date(iso).getTime() / 1000) as UTCTimestamp;
}

export default function CandleChart() {
  const [symbolInput, setSymbolInput] = useState("RELIANCE.NS");
  const [symbol, setSymbol] = useState("RELIANCE.NS");
  const [interval, setInterval_] = useState<Interval>("1d");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const emaSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Build the chart + its three panes once. Data is pushed into the
  // series by the fetch effect below, not recreated on every poll.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#94a3b8",
      },
      grid: {
        vertLines: { color: "#1e293b" },
        horzLines: { color: "#1e293b" },
      },
      autoSize: true,
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    // Pane 0: price + EMA overlay
    candleSeriesRef.current = chart.addSeries(
      CandlestickSeries,
      {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderVisible: false,
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      },
      0,
    );
    emaSeriesRef.current = chart.addSeries(
      LineSeries,
      { color: "#f59e0b", lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
      0,
    );

    // Pane 1: RSI
    rsiSeriesRef.current = chart.addSeries(
      LineSeries,
      { color: "#38bdf8", lineWidth: 2 },
      1,
    );

    // Pane 2: MACD (histogram + line + signal)
    macdHistRef.current = chart.addSeries(HistogramSeries, { color: "#64748b" }, 2);
    macdLineRef.current = chart.addSeries(
      LineSeries,
      { color: "#a78bfa", lineWidth: 1 },
      2,
    );
    macdSignalRef.current = chart.addSeries(
      LineSeries,
      { color: "#f472b6", lineWidth: 1 },
      2,
    );

    const panes = chart.panes();
    panes[0]?.setStretchFactor(4);
    panes[1]?.setStretchFactor(1.5);
    panes[2]?.setStretchFactor(1.5);

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { start, end } = rangeFor(interval);
      const qs = new URLSearchParams({
        symbol,
        interval,
        start,
        end,
        indicators: "rsi,macd,ema",
      });
      const data = await api.get<CandlesResponse>(`/api/candles?${qs.toString()}`);

      const candleData: CandlestickData[] = [];
      const emaData: LineData[] = [];
      const rsiData: LineData[] = [];
      const macdHistData: HistogramData[] = [];
      const macdLineData: LineData[] = [];
      const macdSignalData: LineData[] = [];

      for (const row of data.candles) {
        const time = toUTCTimestamp(row.ts);
        candleData.push({ time, open: row.open, high: row.high, low: row.low, close: row.close });
        if (row.ema != null) emaData.push({ time, value: row.ema });
        if (row.rsi != null) rsiData.push({ time, value: row.rsi });
        if (row.MACDh_12_26_9 != null) {
          macdHistData.push({
            time,
            value: row.MACDh_12_26_9,
            color: row.MACDh_12_26_9 >= 0 ? "#22c55e" : "#ef4444",
          });
        }
        if (row.MACD_12_26_9 != null) macdLineData.push({ time, value: row.MACD_12_26_9 });
        if (row.MACDs_12_26_9 != null) macdSignalData.push({ time, value: row.MACDs_12_26_9 });
      }

      candleSeriesRef.current?.setData(candleData);
      emaSeriesRef.current?.setData(emaData);
      rsiSeriesRef.current?.setData(rsiData);
      macdHistRef.current?.setData(macdHistData);
      macdLineRef.current?.setData(macdLineData);
      macdSignalRef.current?.setData(macdSignalData);

      setLastUpdated(new Date());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load candles");
    } finally {
      setLoading(false);
    }
  }, [symbol, interval]);

  useEffect(() => {
    fetchData();
    const id = window.setInterval(fetchData, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [fetchData]);

  return (
    <div className="p-6">
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setSymbol(symbolInput.trim().toUpperCase());
        }}
      >
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="symbol">
            Symbol
          </label>
          <input
            id="symbol"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value)}
            placeholder="RELIANCE.NS"
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-slate-400" htmlFor="interval">
            Interval
          </label>
          <select
            id="interval"
            value={interval}
            onChange={(e) => setInterval_(e.target.value as Interval)}
            className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            {INTERVALS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          className="rounded-md bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Load
        </button>
        <span className="text-xs text-slate-500">
          {loading
            ? "Loading…"
            : lastUpdated
              ? `Updated ${lastUpdated.toLocaleTimeString()}`
              : null}
        </span>
      </form>

      {error && (
        <div className="mb-4 rounded-md border border-red-800 bg-red-950 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div ref={containerRef} className="h-[600px] w-full" />
    </div>
  );
}
