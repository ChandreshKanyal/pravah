import { useEffect, useRef, useState, type ReactNode } from "react";
import { chat } from "../api/client";
import { Chip, Icon, IconButton } from "./m3";

type Msg = { role: "user" | "bot"; text: string; tools?: string[]; runId?: string | null };
const TOOL_LABEL: Record<string, string> = {
  run_scenario: "Ran a scenario", compare_runs: "Compared runs", list_bridges: "Checked bridges", list_shelters: "Checked shelters",
  list_closed_roads: "Checked roads", get_run_summary: "Read results", get_forecast_summary: "Read forecast", find_shelter_by_name: "Found shelter",
  get_historical_summary: "Read history",
};
const SUGGEST = ["Which bridge closes first?", "What if it rains 100 mm an hour for 3 hours?", "Which shelters are full?", "Which roads are closed at hour 3?"];

function sessionId(): string {
  try {
    let s = sessionStorage.getItem("pravah-chat");
    if (!s) { s = crypto.randomUUID(); sessionStorage.setItem("pravah-chat", s); }
    return s;
  } catch { return "tab-" + Math.random().toString(36).slice(2); }
}

/** Minimal Markdown: paragraphs, bullets and **bold**. */
function md(text: string): ReactNode {
  const bold = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p));
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={out.length}>{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>); list = []; } };
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*[*-]\s+(.*)/);
    if (m) list.push(m[1]);
    else if (line.trim()) { flush(); out.push(<p key={out.length}>{bold(line)}</p>); }
  }
  flush();
  return out;
}

export default function ChatPanel({ open, onClose, aoiId, runId, onNewRun }: {
  open: boolean; onClose: () => void; aoiId: string; runId: string | null; onNewRun: (id: string) => void;
}) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const sid = useRef(sessionId());
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight, behavior: "smooth" }); }, [msgs, busy]);
  if (!open) return null;

  async function send(q: string) {
    if (!q.trim() || busy) return;
    setMsgs((m) => [...m, { role: "user", text: q }]);
    setText("");
    setBusy(true);
    try {
      const r = await chat(sid.current, aoiId, runId, q);
      setMsgs((m) => [...m, { role: "bot", text: r.reply, tools: r.tools_called, runId: r.new_run_id }]);
      if (r.new_run_id) onNewRun(r.new_run_id);
    } catch (e) {
      setMsgs((m) => [...m, { role: "bot", text: `Sorry, the assistant is unavailable right now (${(e as Error).message}).` }]);
    } finally { setBusy(false); }
  }

  return (
    <aside className="side-sheet" aria-label="Ask Pravah">
      <div className="chat-head">
        <Icon name="auto_awesome" className="lg gemini-text" />
        <div className="grow"><div className="title-l">Ask Pravah</div><div className="body-s muted">Gemini answers using this area's models</div></div>
        <IconButton icon="close" label="Close" onClick={onClose} />
      </div>
      <div className="chat-body" ref={body}>
        {!msgs.length && (
          <div className="stack">
            <p className="headline-s"><span className="gemini-text">Hello.</span> What would you like to explore?</p>
            <p className="body-m muted">I can read the current results, run what-if scenarios and compare them. Every number comes from Pravah's engines.</p>
            <div className="suggest">{SUGGEST.map((s) => <button key={s} className="sl" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => m.role === "user" ? <div key={i} className="msg user">{m.text}</div> : (
          <div key={i} className="msg bot">
            <span className="avatar"><Icon name="auto_awesome" /></span>
            <div className="bubble">
              {md(m.text)}
              {m.tools && m.tools.length > 0 && <div className="tools">{[...new Set(m.tools)].map((t) => <Chip key={t} small icon="build" label={TOOL_LABEL[t] ?? t} />)}
                {m.runId && <Chip small icon="map" label="Showing new run on map" />}</div>}
            </div>
          </div>
        ))}
        {busy && <div className="msg bot"><span className="avatar"><Icon name="auto_awesome" /></span><div><span className="typing"><i /><i /><i /></span>
          <div className="body-s muted">Working — this can take a few seconds if a scenario is run…</div></div></div>}
      </div>
      <div className="chat-input">
        <textarea rows={1} value={text} placeholder="Ask about this area…" aria-label="Message" onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
        <IconButton icon="send" label="Send" variant={text.trim() ? "filled" : undefined} disabled={!text.trim() || busy} onClick={() => send(text)} />
      </div>
      <p className="body-s muted" style={{ padding: "0 20px 12px", textAlign: "center" }}>Decision-support draft for official review. Gemini can make mistakes; numbers come from tools.</p>
    </aside>
  );
}
