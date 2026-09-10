// Mirrors backend/app/schemas/dashboard.py, plus the shape of a message
// pushed over /api/ws/dashboard (see app/queue.py's publish_update and
// executor_service/executor.py's process_event).

export interface Holding {
  qty: number;
  avg_price: number;
}

export interface PnLSummary {
  initial_cash: number;
  current_equity: number;
  cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  holdings: Record<string, Holding>;
}

export interface LiveMetrics {
  sharpe: number | null;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  closed_trades: number;
}

export interface DashboardEquityPoint {
  ts: string;
  equity: number;
}

export interface DashboardOverview {
  pnl: PnLSummary;
  metrics: LiveMetrics;
  equity_curve: DashboardEquityPoint[];
}

export interface TradeLogEntry {
  id: number;
  strategy_id: number;
  symbol: string;
  side: "BUY" | "SELL";
  qty: number;
  price: number;
  executed_at: string;
}

export interface TradeLogResponse {
  trades: TradeLogEntry[];
}

export interface DashboardUpdateEvent {
  type: "execution";
  trade: TradeLogEntry;
  portfolio: {
    timestamp: string;
    cash: number;
    equity: number;
    holdings: Record<string, Holding>;
  };
}
