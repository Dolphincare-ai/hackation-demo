import { useEffect, useState } from "react";

const STATUS = {
  act_now: { label: "Act now", ring: "border-red-500", chip: "bg-red-500 text-white" },
  watch: { label: "Watch", ring: "border-amber-400", chip: "bg-amber-400 text-slate-900" },
  on_track: { label: "On track", ring: "border-emerald-500/50", chip: "bg-emerald-500/20 text-emerald-300" },
};
const money = (n) => "$" + Math.round(n).toLocaleString();

function Kpi({ label, value, danger }) {
  return (
    <div className="rounded-xl bg-slate-900 p-5">
      <div className="text-sm uppercase tracking-wide text-slate-400">{label}</div>
      <div className={"mt-1 text-5xl font-bold " + (danger ? "text-red-400" : "text-white")}>{value}</div>
    </div>
  );
}

export default function Portfolio() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = () =>
      fetch("/api/portfolio")
        .then((r) => r.json())
        .then((d) => {
          setData(d);
          setError(false);
        })
        .catch(() => setError(true));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  if (!data)
    return (
      <div className="p-10 text-slate-300">
        {error ? "Cannot reach the platform. Start the backend, then reload." : "Loading..."}
      </div>
    );

  const name = Object.fromEntries(data.buildings.map((b) => [b.id, b.name]));
  const { kpis } = data;

  return (
    <div className="min-h-screen p-6 text-slate-100">
      <h1 className="mb-4 text-2xl font-semibold">Portfolio: {data.buildings.length} buildings</h1>
      <div className="grid grid-cols-4 gap-4">
        <Kpi label="Open workflows" value={kpis.open_workflows} />
        <Kpi label="Late steps" value={kpis.late_steps} danger={kpis.late_steps > 0} />
        <Kpi label="Money at risk" value={money(kpis.dollars_at_risk)} danger />
        <Kpi label="Paid" value={money(kpis.dollars_paid)} />
      </div>

      <div className="mt-6 grid grid-cols-3 gap-6">
        <div className="col-span-2 grid grid-cols-2 content-start gap-4">
          {data.buildings.map((b) => {
            const s = STATUS[b.status];
            return (
              <div key={b.id} className={"rounded-xl border-2 bg-slate-900 p-4 " + s.ring}>
                <div className="flex items-center justify-between">
                  <div className="text-lg font-semibold">{b.name}</div>
                  <span className={"rounded-full px-3 py-1 text-xs font-bold " + s.chip}>{s.label}</span>
                </div>
                <div className="mt-3 grid grid-cols-4 gap-2 text-sm text-slate-400">
                  <div><div className="text-2xl font-bold text-white">{b.open_runs}</div>open</div>
                  <div>
                    <div className={"text-2xl font-bold " + (b.late_tasks ? "text-red-400" : "text-white")}>{b.late_tasks}</div>
                    late
                  </div>
                  <div><div className="text-2xl font-bold text-white">{money(b.at_risk)}</div>at risk</div>
                  <div><div className="text-2xl font-bold text-white">{money(b.held_back)}</div>held back</div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="space-y-6">
          <section className="rounded-xl bg-slate-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Needs the owner</h2>
            {data.needs_owner.length === 0 && <p className="text-slate-500">Nothing waiting on you.</p>}
            {data.needs_owner.map((n, i) => (
              <div key={i} className="mb-3 border-l-4 pl-3" style={{ borderColor: n.late ? "#ef4444" : "#fbbf24" }}>
                <div className="text-xs text-slate-400">
                  {name[n.building_id]} · {n.late ? `${-n.due_in_h}h late` : `due in ${n.due_in_h}h`}
                </div>
                <div>{n.title}</div>
              </div>
            ))}
          </section>
          <section className="rounded-xl bg-slate-900 p-4">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">Live feed</h2>
            {data.live_feed.map((f, i) => (
              <div key={i} className="mb-2 text-sm">
                <span className="text-slate-500">{f.at}</span>{" "}
                <span className="text-slate-300">{name[f.building_id]}:</span> {f.text}
              </div>
            ))}
          </section>
        </div>
      </div>
    </div>
  );
}
