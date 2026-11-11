import { useEffect, useRef, useState } from "react";

// Floating chat. Everything is typed: the bot proposes in text and the user answers in text.
export default function AgentBot({ userId, runId }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const [pending, setPending] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);

  useEffect(() => {
    setMsgs([]); setPending([]);
    fetch(`/api/agent/chat/history?user_id=${userId}`).then((r) => r.json()).then(setMsgs).catch(() => {});
  }, [userId]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);

  async function send() {
    const message = text.trim();
    if (!message || busy) return;
    setText(""); setBusy(true);
    setMsgs((m) => [...m, { role: "user", content: message }]);
    try {
      const r = await fetch("/api/agent/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId },
        body: JSON.stringify({ user_id: userId, message, run_id: runId || null }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Something went wrong");
      setMsgs((m) => [...m, { role: "assistant", content: d.reply }]);
      setPending(d.proposals || []);
    } catch (e) {
      setMsgs((m) => [...m, { role: "assistant", content: `Sorry: ${e.message}` }]);
    } finally { setBusy(false); }
  }

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} aria-label="Open the agent chat"
          className="fixed bottom-6 right-6 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-sky-600 text-2xl shadow-lg hover:bg-sky-500">
          🤖
          {pending.length > 0 && <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-xs font-bold text-slate-900">{pending.length}</span>}
        </button>
      )}
      {open && (
        <div className="fixed bottom-6 right-6 z-50 flex h-[560px] w-[380px] flex-col overflow-hidden rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
          <div className="flex items-center justify-between border-b border-slate-700 bg-slate-800 px-4 py-3">
            <span className="text-sm font-semibold">AP agent</span>
            <button onClick={() => setOpen(false)} className="text-slate-400 hover:text-white" aria-label="Minimize">—</button>
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto p-3 text-sm">
            {msgs.length === 0 && (
              <p className="text-slate-400">Ask me what is waiting, or tell me what to change. Try: "check the inbox now", "show me the current settings", or "give approvals 12h on this one".</p>
            )}
            {msgs.map((m, i) => (
              <div key={m.id ?? i} className={m.role === "user" ? "flex justify-end" : "flex"}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 ${m.role === "user" ? "bg-sky-700" : "bg-slate-800"}`}>{m.content}</div>
              </div>
            ))}
            {busy && <div className="text-slate-400">Typing…</div>}
            <div ref={end} />
          </div>
          <div className="border-t border-slate-700 p-2">
            <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Type a message and press Enter" disabled={busy}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none" />
          </div>
        </div>
      )}
    </>
  );
}
