import { useEffect, useState } from "react";

// Muted status colors shown as a soft chip.
const STATUS = {
  act_now: { label: "Act now", chip: "bg-rose-500/15 text-rose-300 ring-rose-500/40" },
  watch: { label: "Watch", chip: "bg-amber-400/15 text-amber-200 ring-amber-400/40" },
  on_track: { label: "On track", chip: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40" },
};
const money = (n) => "$" + Math.round(n).toLocaleString();

function Kpi({ label, value, tone = "neutral" }) {
  const color = { neutral: "text-slate-50", bad: "text-rose-300", accent: "text-sky-300" }[tone];
  return (
    <div className="card p-5">
      <div className="section-title">{label}</div>
      <div className={"mt-2 text-4xl font-semibold tabular-nums " + color}>{value}</div>
    </div>
  );
}

function Stat({ value, label, tone }) {
  const color = { bad: "text-rose-300", warn: "text-amber-200" }[tone] || "text-slate-50";
  return (
    <div className="stat">
      <div className={"text-lg font-semibold tabular-nums " + color}>{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  );
}

export default function Portfolio({ onOpen }) {
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
    <div>
      <div className="mb-5 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-slate-50">Portfolio</h1>
        <span className="text-sm text-slate-400">{data.buildings.length} buildings</span>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Kpi label="Open workflows" value={kpis.open_workflows} tone="accent" />
        <Kpi label="Late steps" value={kpis.late_steps} tone={kpis.late_steps > 0 ? "bad" : "neutral"} />
        <Kpi label="Money at risk" value={money(kpis.dollars_at_risk)} tone={kpis.dollars_at_risk > 0 ? "bad" : "neutral"} />
        <Kpi label="Paid" value={money(kpis.dollars_paid)} />
      </div>

      <div className="mt-6 grid grid-cols-3 gap-6">
        <div className="col-span-2 grid grid-cols-2 content-start gap-4">
          {data.buildings.map((b) => {
            const s = STATUS[b.status];
            const shifts = b.summary.staffing.headline.replace(" open shifts", "").replace(" open shift", "");
            return (
              <div
                key={b.id}
                onClick={() => onOpen(b.id)}
                className="card card-hover cursor-pointer p-4"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="truncate text-base font-semibold text-slate-50">{b.name}</div>
                  <span className={"shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 " + s.chip}>
                    {s.label}
                  </span>
                </div>
                <div className="mt-3 grid grid-cols-4 gap-2">
                  <Stat value={b.summary.residents.headline} label="Residents" />
                  <Stat value={money(b.at_risk)} label="At risk" tone={b.at_risk ? "bad" : null} />
                  <Stat value={shifts} label="Open shifts" tone={b.summary.staffing.tone === "warn" ? "warn" : null} />
                  <Stat
                    value={
                      <>
                        {b.summary.todos.open}
                        {b.summary.todos.late > 0 && (
                          <span className="ml-1 text-xs font-medium text-rose-300">{b.summary.todos.late} late</span>
                        )}
                      </>
                    }
                    label="To-dos"
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="space-y-6">
          <section className="card p-4">
            <h2 className="section-title mb-3">Needs the owner</h2>
            {data.needs_owner.length === 0 && <p className="text-sm text-slate-400">Nothing waiting on you.</p>}
            <div className="space-y-2">
              {data.needs_owner.map((n, i) => (
                <div
                  key={i}
                  className={"rounded-lg border-l-4 bg-slate-900/60 px-3 py-2 " + (n.late ? "border-rose-500" : "border-amber-400")}
                >
                  <div className="text-xs text-slate-400">
                    {name[n.building_id]} ·{" "}
                    <span className={n.late ? "text-rose-300" : "text-amber-200"}>
                      {n.late ? `${-n.due_in_h}h late` : `due in ${n.due_in_h}h`}
                    </span>
                  </div>
                  <div className="text-sm text-slate-100">{n.title}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="card p-4">
            <h2 className="section-title mb-3">Live feed</h2>
            <div className="divide-y divide-slate-700/60">
              {data.live_feed.map((f, i) => (
                <div key={i} className="py-2 text-sm first:pt-0 last:pb-0">
                  <div className="text-xs text-slate-500">
                    {f.at} · <span className="text-slate-300">{name[f.building_id]}</span>
                  </div>
                  <div className="text-slate-200">{f.text}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
