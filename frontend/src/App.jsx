import { useEffect, useState } from "react";
import Portfolio from "./Portfolio.jsx";
import BuildingBoard from "./BuildingBoard.jsx";
import Workflows from "./Workflows.jsx";
import AgentBot from "./AgentBot.jsx";

const USERS = [["u_owner", "Owner"], ["u_admin_rc", "Administrator"], ["u_bom_rc", "Business office manager"], ["u_don_rc", "Director of nursing"], ["u_cfo", "CFO"]];

export default function App() {
  const [tab, setTab] = useState("boards");
  const [userId, setUserId] = useState("u_admin_rc");
  const [runId, setRunId] = useState(null);
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
        <button onClick={() => setTab(tab === "workflows" ? "boards" : "workflows")}
          className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700">{tab === "workflows" ? "Boards" : "Workflows"}</button>
        <span className="ml-auto text-xs font-semibold uppercase tracking-wider text-slate-400">Acting as</span>
        <select value={userId} onChange={(e) => setUserId(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-100">
          {USERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      {tab === "workflows"
        ? <Workflows userId={userId} onSelect={setRunId} focusId={runId} />
        : view === "all" ? <Portfolio onOpen={setView} /> : <BuildingBoard id={view} />}
      <AgentBot userId={userId} runId={tab === "workflows" ? runId : null} onOpenWorkflow={(id) => { setRunId(id); setTab("workflows"); }} />
    </div>
  );
}
