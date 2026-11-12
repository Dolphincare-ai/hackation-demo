import { useEffect, useState } from "react";

const money = (n) => (n == null ? "–" : n.toLocaleString("en-US", { style: "currency", currency: "USD" }));
const when = (s) => (s ? new Date(s).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–");
const STEPS = ["RECEIVED", "EXTRACTED", "CHECKED", "NEEDS_INFO", "PENDING_APPROVAL", "FUNDS_CHECK", "AWAITING_PAYMENT", "PAID", "CLOSED"];
const TONE = {
  verified: "bg-emerald-900/60 text-emerald-300", manually_verified: "bg-emerald-900/60 text-emerald-300",
  failed: "bg-red-900/60 text-red-300", manually_rejected: "bg-red-900/60 text-red-300",
  unverified: "bg-amber-900/60 text-amber-300", skipped: "bg-slate-700 text-slate-300",
};
const CHECKS = ["price", "date", "delivery", "math", "duplicate", "bank_details"];

export async function api(path, opts = {}, userId) {
  const r = await fetch(`/api${path}`, { ...opts, headers: { "Content-Type": "application/json", "X-User-Id": userId, ...(opts.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `Request failed (${r.status})`);
  return d;
}

export default function Workflows({ userId, onSelect, focusId }) {
  const [runs, setRuns] = useState([]);
  const [sel, setSel] = useState(focusId || null);
  const [tab, setTab] = useState("all");

  useEffect(() => {
    const load = () => api("/runs", {}, userId).then(setRuns).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [userId]);
  useEffect(() => { onSelect?.(sel); }, [sel]);

  const types = [...new Set(runs.map((r) => r.type))];
  const shown = runs.filter((r) => tab === "all" || r.type === tab);

  return (
    <div className="grid grid-cols-[320px_1fr] gap-6">
      <div>
        <div className="mb-3 flex flex-wrap gap-2">
          {["all", ...types].map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded-full px-3 py-1 text-xs ${tab === t ? "bg-sky-600" : "bg-slate-800 text-slate-300"}`}>
              {t === "all" ? "All" : t.replace(/_/g, " ")} ({t === "all" ? runs.length : runs.filter((r) => r.type === t).length})
            </button>
          ))}
        </div>
        {shown.length === 0 && <p className="text-sm text-slate-400">No workflows yet. Use "send invoice email" in Their world, or ask the bot to check the inbox.</p>}
        <div className="space-y-2">
          {shown.map((r) => (
            <button key={r.id} onClick={() => setSel(r.id)}
              className={`w-full rounded-lg border p-3 text-left ${sel === r.id ? "border-sky-500 bg-slate-800" : "border-slate-800 bg-slate-900 hover:border-slate-600"}`}>
              <div className="text-sm font-medium">{r.title}</div>
              <div className="mt-1 text-xs text-slate-400">{r.state.replace(/_/g, " ")} · {money(r.total)}{r.at_risk > 0 && ` · ${money(r.at_risk)} at risk`}</div>
              {r.late_tasks > 0 && <div className="mt-1 text-xs font-semibold text-red-400">{r.late_tasks} late</div>}
            </button>
          ))}
        </div>
      </div>
      {sel ? <Detail id={sel} userId={userId} /> : <p className="text-slate-400">Pick a workflow to see its checks, packet and steps.</p>}
    </div>
  );
}

function Detail({ id, userId }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api(`/runs/${id}`, {}, userId).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { setD(null); load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [id, userId]);
  if (!d) return <p className="text-slate-400">{err || "Loading…"}</p>;

  const { run, invoice, findings, tasks, packet, payment, timeline } = d;
  const act = (fn) => async (...a) => { setErr(""); try { await fn(...a); await load(); } catch (e) { setErr(e.message); } };
  const resolve = act((tid, response, note) => api(`/tasks/${tid}/resolve`, { method: "POST", body: JSON.stringify({ user_id: userId, response, note }) }, userId));
  const approve = act((decision, reason, lines) => api(`/runs/${id}/approval`, { method: "POST", body: JSON.stringify({ user_id: userId, decision, reason, lines }) }, userId));
  const step = STEPS.indexOf(run.state);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold">{run.title}</h2>
        <div className="mt-3 flex flex-wrap gap-1">
          {STEPS.map((s, i) => (
            <span key={s} className={`rounded px-2 py-1 text-xs ${s === run.state ? "bg-sky-600" : i < step ? "bg-slate-700 text-slate-300" : "bg-slate-900 text-slate-500"}`}>{s.replace(/_/g, " ")}</span>
          ))}
          {["REJECTED", "MANUAL_ENTRY", "FUNDS_INSUFFICIENT"].includes(run.state) && <span className="rounded bg-red-700 px-2 py-1 text-xs">{run.state.replace(/_/g, " ")}</span>}
        </div>
        {err && <p className="mt-2 rounded bg-red-900/50 p-2 text-sm text-red-200">{err}</p>}
      </div>

      <Section title="Steps">
        {tasks.map((t) => (
          <div key={t.id} className="rounded border border-slate-800 p-3 text-sm">
            <div className="flex justify-between gap-2">
              <span>{t.title}</span>
              <span className={t.status === "done" ? "text-emerald-400" : t.late ? "text-red-400" : "text-slate-400"}>
                {t.status === "done" ? `done${t.completion_source === "system_observed" ? " (seen on bank feed)" : ""}` : t.late ? "late" : "open"}
              </span>
            </div>
            <div className="mt-1 text-xs text-slate-400">{t.role.replace(/_/g, " ")} · due {when(t.due_at)} · via {t.via}{t.escalation_level > 0 && ` · escalation ${t.escalation_level}`}</div>
            {t.status === "open" && t.kind === "manual_check" && <ManualCheck onResolve={(r, n) => resolve(t.id, r, n)} />}
            {t.status === "open" && !["manual_check", "approval"].includes(t.kind) && t.kind !== "payment" && (
              <button onClick={() => resolve(t.id, "verified", "")} className="mt-2 rounded bg-slate-700 px-3 py-1 text-xs">Mark done</button>
            )}
          </div>
        ))}
        {tasks.length === 0 && <p className="text-sm text-slate-400">No steps yet.</p>}
      </Section>

      {invoice && (
        <Section title="Checks by line">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-400"><th className="py-1">Line</th><th>Amount</th>{CHECKS.map((c) => <th key={c}>{c.replace("_", " ")}</th>)}</tr></thead>
            <tbody>
              {invoice.lines.map((l) => (
                <tr key={l.id} className="border-t border-slate-800">
                  <td className="py-1 pr-2">{l.description}</td><td>{money(l.amount)}</td>
                  {CHECKS.map((c) => {
                    const f = findings.find((x) => x.line_id === l.id && x.check === c);
                    return <td key={c}>{f ? <span title={f.message} className={`rounded px-1.5 py-0.5 ${TONE[f.status]}`}>{f.status.replace("_", " ")}</span> : "–"}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {findings.filter((f) => !f.line_id).map((f) => (
            <p key={f.id} className="mt-2 text-xs"><span className={`rounded px-1.5 py-0.5 ${TONE[f.status]}`}>{f.check.replace("_", " ")}: {f.status}</span> {f.message}</p>
          ))}
        </Section>
      )}

      {packet && <Packet packet={packet} />}

      {run.state === "PENDING_APPROVAL" && invoice && <ApprovalForm invoice={invoice} findings={findings} onSubmit={approve} />}

      {payment && (
        <Section title="Payment">
          <p className="text-sm">{money(payment.amount)} · reference {payment.expected_ref} · <b>{payment.status}</b>{payment.matched_txn_id && ` (bank transaction ${payment.matched_txn_id})`}</p>
          <p className="mt-1 text-xs text-slate-400">The platform never moves money. A person pays from their own bank and we watch the bank feed.</p>
        </Section>
      )}

      <Section title="Timeline">
        <ul className="space-y-1 text-xs text-slate-300">
          {timeline.map((a) => <li key={a.id}><span className="text-slate-500">{when(a.at)}</span> {a.actor} · {a.action.replace(/_/g, " ")}</li>)}
        </ul>
      </Section>
    </div>
  );
}

const Section = ({ title, children }) => (
  <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h3><div className="space-y-2">{children}</div></section>
);

export function ManualCheck({ onResolve }) {
  const [note, setNote] = useState("");
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (what you checked)" className="min-w-40 flex-1 rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs" />
      <button onClick={() => onResolve("verified", note)} className="rounded bg-emerald-700 px-3 py-1 text-xs">Verified</button>
      <button onClick={() => onResolve("not_verified", note)} className="rounded bg-amber-700 px-3 py-1 text-xs">Not verified</button>
      <button onClick={() => onResolve("dispute", note)} className="rounded bg-red-700 px-3 py-1 text-xs">Dispute</button>
    </div>
  );
}

export function Packet({ packet }) {
  const list = (items, render) => items?.length ? <ul className="space-y-1">{items.map(render)}</ul> : <p className="text-xs text-slate-500">None</p>;
  return (
    <Section title="Approval packet">
      <p className="rounded bg-slate-800 p-3 text-sm">{packet.summary || "No summary yet."}</p>
      <div className="grid grid-cols-3 gap-2 text-center text-xs">
        <div className="rounded bg-slate-800 p-2">Billed<br /><b className="text-sm">{money(packet.totals.billed)}</b></div>
        <div className="rounded bg-slate-800 p-2">Fully verified<br /><b className="text-sm text-emerald-300">{money(packet.totals.verified)}</b></div>
        <div className="rounded bg-slate-800 p-2">At risk<br /><b className="text-sm text-red-300">{money(packet.totals.at_risk)}</b></div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div><h4 className="mb-1 font-semibold text-emerald-300">Verified</h4>{list([...(packet.verified || []), ...(packet.manually_verified || [])], (v, i) => <li key={i}>{v.check}: {v.message || v.note} {v.source && <span className="text-slate-500">({v.source})</span>}{v.by && <span className="text-slate-500"> by {v.by}</span>}</li>)}</div>
        <div><h4 className="mb-1 font-semibold text-red-300">Flagged</h4>
          {list(packet.failed, (f, i) => <li key={i}>{f.check}: {f.message} {f.amount_at_risk > 0 && <b>({money(f.amount_at_risk)} at risk)</b>}</li>)}
          {list(packet.unverified, (u, i) => <li key={i} className="text-amber-300">{u.check}: {u.reason}</li>)}
          {packet.skipped?.length > 0 && list(packet.skipped, (s, i) => <li key={i} className="text-slate-400">{s.check}: not checked by request</li>)}
        </div>
      </div>
    </Section>
  );
}

export function ApprovalForm({ invoice, findings, onSubmit }) {
  const bad = (id) => findings.some((f) => f.line_id === id && ["failed", "manually_rejected"].includes(f.status));
  const [dec, setDec] = useState(() => Object.fromEntries(invoice.lines.map((l) => [l.id, bad(l.id) ? "exclude" : "approve"])));
  const [reason, setReason] = useState("");
  const lines = invoice.lines.map((l) => ({ line_id: l.id, decision: dec[l.id] }));
  return (
    <Section title="Your decision">
      {invoice.lines.map((l) => (
        <div key={l.id} className="flex items-center justify-between gap-2 text-sm">
          <span>{l.description} <span className="text-slate-400">{money(l.amount)}</span>{bad(l.id) && <span className="ml-2 rounded bg-red-900/60 px-1.5 text-xs text-red-300">flagged</span>}</span>
          <select value={dec[l.id]} onChange={(e) => setDec({ ...dec, [l.id]: e.target.value })} className="rounded border border-slate-700 bg-slate-800 px-2 py-1 text-xs">
            <option value="approve">Approve as billed</option><option value="approve_at_contract">Approve at contract rate</option><option value="exclude">Exclude (dispute)</option>
          </select>
        </div>
      ))}
      <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required to approve a flagged line as billed, or to reject)" className="w-full rounded border border-slate-700 bg-slate-800 px-2 py-1 text-sm" />
      <div className="flex gap-2">
        <button onClick={() => onSubmit("approve", reason, lines)} className="rounded bg-emerald-700 px-4 py-2 text-sm">Approve</button>
        <button onClick={() => onSubmit("reject", reason, lines)} className="rounded bg-red-700 px-4 py-2 text-sm">Reject</button>
      </div>
    </Section>
  );
}
