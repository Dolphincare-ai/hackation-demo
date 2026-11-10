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
      <div className="mb-5 flex items-center gap-3">
        <span className="text-sm uppercase tracking-widest text-slate-500">View</span>
        <select value={view} onChange={(e) => setView(e.target.value)}
          className="rounded bg-slate-800 px-3 py-2 text-slate-100">
          <option value="all">All buildings</option>
          {buildings.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
      </div>
      {view === "all" ? <Portfolio onOpen={setView} /> : <BuildingBoard id={view} />}
    </div>
  );
}
