import { useEffect, useState } from "react";

const TONE = { good: "text-emerald-300", warn: "text-amber-300", bad: "text-red-400", neutral: "text-white" };
const BUCKETS = [["today", "Today"], ["week", "Week"], ["month", "Month"]];

function Quadrant({ q, n }) {
  return (
    <section className="rounded-xl bg-slate-900 p-5">
      <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">{n} · {q.title}</div>
      <div className={"mt-2 text-5xl font-bold " + TONE[q.tone]}>{q.headline}</div>
      <div className="mt-3 space-y-1 text-slate-300">
        {q.lines.map((l, i) => <div key={i}>{l}</div>)}
      </div>
      <div className="mt-4 text-xs text-slate-500">
        <span className={"mr-1 inline-block h-2 w-2 rounded-full " + (q.live ? "bg-emerald-400" : "bg-slate-600")} />
        {q.live ? "Live" : "Demo data"} · {q.source}
      </div>
    </section>
  );
}

export default function BuildingBoard({ id }) {
  const [data, setData] = useState(null);
  const [bucket, setBucket] = useState("today");

  useEffect(() => {
    setData(null);
    const load = () => fetch(`/api/buildings/${id}/board`).then((r) => r.json()).then(setData).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [id]);

  if (!data) return <div className="p-10 text-slate-300">Loading...</div>;

  const todos = data.todos.filter((t) => t.bucket === bucket || (bucket !== "today" && t.late));
  return (
    <div>
      <div className="mb-4 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">{data.building.name} · Today</h1>
        <span className="font-mono text-xs text-slate-500">DEMO DATA · {data.as_of}</span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {data.quadrants.map((q, i) => <Quadrant key={q.key} q={q} n={i + 1} />)}
        <section className="rounded-xl bg-slate-900 p-5">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold uppercase tracking-widest text-slate-400">4 · To-dos</div>
            <div className="flex gap-1">
              {BUCKETS.map(([k, label]) => (
                <button key={k} onClick={() => setBucket(k)}
                  className={"rounded px-2 py-1 text-xs " + (bucket === k ? "bg-slate-600 text-white" : "text-slate-400 hover:text-white")}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="mt-3 space-y-2">
            {todos.length === 0 && <p className="text-slate-500">Nothing due {bucket === "today" ? "today" : "in this range"}.</p>}
            {todos.map((t, i) => (
              <div key={i} className="flex items-center gap-3">
                <span className={"rounded-full px-2 py-0.5 text-xs font-bold " + (t.late ? "bg-red-900 text-red-200" : "bg-amber-900 text-amber-200")}>
                  {t.late ? "Late" : t.bucket}
                </span>
                <span className="flex-1">{t.title}</span>
                <span className="text-xs text-slate-500">{t.owner.replaceAll("_", " ")}{t.source === "agent" ? " · agent" : ""}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
