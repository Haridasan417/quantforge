import { NavLink, Route, Routes } from "react-router-dom";
import Backtest from "./routes/Backtest";
import Chart from "./routes/Chart";
import Deploy from "./routes/Deploy";
import StrategyBuilder from "./routes/StrategyBuilder";
import Dashboard from "./routes/Dashboard";

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-3 py-2 text-sm font-medium ${
    isActive ? "bg-slate-800 text-white" : "text-slate-400 hover:text-white"
  }`;

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950">
      <nav className="flex items-center gap-2 border-b border-slate-800 px-6 py-4">
        <span className="mr-4 text-lg font-bold text-white">QuantForge</span>
        <NavLink to="/" end className={navLinkClass}>
          Dashboard
        </NavLink>
        <NavLink to="/chart" className={navLinkClass}>
          Chart
        </NavLink>
        <NavLink to="/strategy-builder" className={navLinkClass}>
          Strategy Builder
        </NavLink>
        <NavLink to="/backtest" className={navLinkClass}>
          Backtest
        </NavLink>
        <NavLink to="/deploy" className={navLinkClass}>
          Deploy
        </NavLink>
      </nav>

      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chart" element={<Chart />} />
        <Route path="/strategy-builder" element={<StrategyBuilder />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/deploy" element={<Deploy />} />
      </Routes>
    </div>
  );
}
