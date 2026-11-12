import { useEffect, useRef, useState } from "react";
import { api } from "./Workflows.jsx";

// Floating chat: a plain conversation with the bot. Full workflow detail lives in the Workflows tab.

export default function AgentBot({ userId, runId, onOpenWorkflow }) {
  const [open, setOpen] = useState(false);
  const [thread, setThread] = useState(0); // 0 = general, otherwise a run id
  const [runs, setRuns] = useState([]);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);

  // the Workflows tab selection opens that workflow's chat
  useEffect(() => { if (runId) setThread(runId); }, [runId]);

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

  const stream = msgs.map((m, i) => ({ ...m, key: `m${m.id ?? "x" + i}` }));
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
              <p className="text-slate-400">Hi! Ask me anything about your invoices, or say "check the inbox" and I will look for new ones and talk you through them.</p>
            )}
            {stream.map((s) => (
              <div key={s.key} className={s.role === "user" ? "flex justify-end" : "flex"}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 ${s.role === "user" ? "bg-sky-700" : "bg-slate-800"}`}>{s.content}</div>
              </div>
            ))}
            {busy && <div className="text-slate-400">Typing…</div>}
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
