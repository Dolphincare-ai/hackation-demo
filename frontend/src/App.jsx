import { useEffect, useState } from "react";
import Portfolio from "./Portfolio.jsx";
import BuildingBoard from "./BuildingBoard.jsx";

export default function App() {
  const [view, setView] = useState("all"); // "all" or a building id
  const [buildings, setBuildings] = useState([]);

  useEffect(() => {
    fetch("/api/portfolio").then((r) => r.json()).then((d) => setBuildings(d.buildings)).catch(() => {});
  }, []);

  return (
    <div className="min-h-screen p-6 text-slate-100">
      <div className="mb-6 flex items-center gap-3 border-b border-slate-800 pb-4">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">View</span>
        <select value={view} onChange={(e) => setView(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:border-sky-500 focus:outline-none">
          <option value="all">All buildings</option>
          {buildings.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </div>
      {view === "all" ? <Portfolio onOpen={setView} /> : <BuildingBoard id={view} />}
    </div>
  );
}
