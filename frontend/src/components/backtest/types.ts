// Mirrors backend/app/schemas/backtest.py.

export interface EquityPoint {
  ts: string;
  equity: number;
}

export interface BacktestTrade {
  ts: string;
  side: "BUY" | "SELL";
  price: number;
  qty: number;
}

export interface BacktestResponse {
  strategy_id: string;
  symbol: string;
  interval: string;
  sharpe: number | null;
  max_drawdown: number;
  win_rate: number;
  final_equity: number;
  equity_curve: EquityPoint[];
  trades: BacktestTrade[];
}
