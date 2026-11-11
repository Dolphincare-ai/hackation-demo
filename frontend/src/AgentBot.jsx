import { useEffect, useRef, useState } from "react";
import { api, ApprovalForm, ManualCheck, Packet } from "./Workflows.jsx";

// Floating chat. It shows two things in one stream: what you and the bot typed, and what the bot did on its own
// (the audit log in plain words). Tasks that need a person show up as cards you can answer right here.
// One chat per workflow: pick it in the header. "General" shows everything.

export default function AgentBot({ userId, runId }) {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState(0); // 0 = general, otherwise a run id
  const [runs, setRuns] = useState([]);
  const [msgs, setMsgs] = useState([]);
  const [events, setEvents] = useState([]);
  const [unread, setUnread] = useState(0);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const cursor = useRef(0);
  const first = useRef(true);
  const openRef = useRef(open);
  const end = useRef(null);
  openRef.current = open;

  // the Workflows tab selection opens that workflow's chat
  useEffect(() => { if (runId) setThread(runId); }, [runId]);

  // bot activity: one global poll, filtered per chat below
  useEffect(() => {
    setEvents([]); cursor.current = 0; first.current = true; setUnread(0);
    let stop = false;
    const poll = async () => {
      try {
        const d = await api(`/agent/activity?user_id=${userId}&after_id=${cursor.current}`, {}, userId);
        if (stop) return;
        cursor.current = d.cursor;
        if (d.events.length) {
          setEvents((e) => [...e, ...d.events]);
          if (!first.current) {
            if (d.events.some((x) => x.mine && x.task_id)) setOpen(true); // a task for me: pop up
            else if (!openRef.current) setUnread((u) => u + d.events.length);
          }
        }
        first.current = false;
      } catch { /* backend restarting: try again next tick */ }
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => { stop = true; clearInterval(t); };
  }, [userId]);

  useEffect(() => {
    const load = () => api("/runs", {}, userId).then(setRuns).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [userId]);

  useEffect(() => {
    setMsgs([]);
    api(`/agent/chat/history?user_id=${userId}&run_id=${thread}`, {}, userId).then(setMsgs).catch(() => {});
  }, [userId, thread]);

  useEffect(() => { if (open) setUnread(0); }, [open]);
  const shownEvents = events.filter((e) => thread === 0 || e.run_id === thread);
  const stream = [...msgs.map((m, i) => ({ ...m, type: "msg", key: `m${m.id ?? "x" + i}` })),
    ...shownEvents.map((e) => ({ ...e, type: "event", key: `e${e.id}` }))]
    .sort((a, b) => new Date(a.at || Date.now()) - new Date(b.at || Date.now()));
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [stream.length, busy, open]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: message, at: new Date().toISOString() }]);
    try {
      const d = await api("/agent/chat", { method: "POST", body: JSON.stringify({ user_id: userId, message, run_id: thread || null }) }, userId);
      setMsgs((m) => [...m, { role: "assistant", content: d.reply, at: new Date().toISOString() }]);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: `Sorry: ${e.message}`, at: new Date().toISOString() }]);
    } finally { setBusy(false); }
  }

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} aria-label="Open the agent chat"
          className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-sky-600 text-2xl shadow-lg hover:bg-sky-500">
          🤖
          {unread > 0 && <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-amber-500 px-1 text-xs font-bold text-slate-900">{unread}</span>}
        </button>
      )}
      {open && (
        <div className="fixed bottom-6 right-6 z-50 flex h-[640px] w-[420px] flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
          <div className="flex items-center gap-2 border-b border-slate-700 bg-slate-800 px-3 py-2">
            <select value={thread} onChange={(e) => setThread(Number(e.target.value))}
              className="min-w-0 flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm">
              <option value={0}>General (everything)</option>
              {runs.map((r) => <option key={r.id} value={r.id}>{r.title} · {r.state.replace(/_/g, " ").toLowerCase()}</option>)}
            </select>
            <button onClick={() => setThread(0)} className="rounded bg-sky-700 px-2 py-1 text-xs hover:bg-sky-600">New chat</button>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-white" aria-label="Minimize">—</button>
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto p-3 text-sm">
            {stream.length === 0 && (
              <p className="text-slate-400">Nothing yet. Ask me to "check the inbox now" and I will tell you everything I do, step by step. Tasks that need you appear here as cards.</p>
            )}
            {stream.map((s) => s.type === "msg" ? (
              <div key={s.key} className={s.role === "user" ? "flex justify-end" : "flex"}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 ${s.role === "user" ? "bg-sky-700" : "bg-slate-800"}`}>{s.content}</div>
              </div>
            ) : (
              <EventLine key={s.key} e={s} userId={userId} openThread={setThread} />
            ))}
            {busy && <div className="text-slate-400">Working…</div>}
            <div ref={end} />
          </div>
          <div className="border-t border-slate-700 p-2">
            <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder={thread ? "Ask about this workflow" : "Try: check the inbox now"} disabled={busy}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none" />
          </div>
        </div>
      )}
    </>
  );
}

function EventLine({ e, userId, openThread }) {
  return (
    <div className="text-xs text-slate-300">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-sky-400">●</span>
        <div className="min-w-0 flex-1">
          <span>{e.text}</span>
          {e.action === "run_started" && e.run_id && (
            <button onClick={() => openThread(e.run_id)} className="ml-2 rounded bg-slate-700 px-2 py-0.5 hover:bg-slate-600">Open this chat</button>
          )}
        </div>
      </div>
      {e.task_id && ["manual_check", "approval"].includes(e.kind) && <TaskCard e={e} userId={userId} />}
    </div>
  );
}

// A task that needs a person. Same endpoints as the Workflows tab; the server decides who may do what.
function TaskCard({ e, userId }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const load = () => api(`/runs/${e.run_id}`, {}, userId).then(setD).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [e.run_id, userId]);
  if (!d) return null;
  const task = d.tasks.find((t) => t.id === e.task_id);
  if (!task) return null;
  const act = (fn) => async (...a) => { setErr(""); try { await fn(...a); await load(); } catch (x) { setErr(x.message); } };
  const resolve = act((response, note) => api(`/tasks/${task.id}/resolve`, { method: "POST", body: JSON.stringify({ user_id: userId, response, note }) }, userId));
  const approve = act((decision, reason, lines) => api(`/runs/${e.run_id}/approval`, { method: "POST", body: JSON.stringify({ user_id: userId, decision, reason, lines }) }, userId));
  return (
    <div className={`mt-2 rounded-lg border p-3 ${e.mine ? "border-amber-500/60 bg-slate-800" : "border-slate-700 bg-slate-800/50"}`}>
      <div className="font-medium text-slate-100">{task.title}</div>
      <div className="text-slate-400">{e.mine ? "Waiting on you" : `Waiting on ${task.role.replace(/_/g, " ")}`} · {task.status === "done" ? "done" : task.late ? "late" : "open"}</div>
      {err && <p className="mt-1 rounded bg-red-900/50 p-1 text-red-200">{err}</p>}
      {task.status === "open" && task.kind === "manual_check" && <ManualCheck onResolve={resolve} />}
      {task.status === "open" && task.kind === "approval" && d.run.state === "PENDING_APPROVAL" && d.invoice && (
        <div className="mt-2 space-y-2">
          {d.packet && <Packet packet={d.packet} />}
          <ApprovalForm invoice={d.invoice} findings={d.findings} onSubmit={approve} />
        </div>
      )}
    </div>
  );
}
