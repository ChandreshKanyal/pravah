// The Pravah assistant: a Gemini button at the bottom right of every page opening a small chat. It answers general
// questions from Google Search (with sources), knows the open area, and drives the app through actions it proposes
// and you confirm (move the map, open an area or view, prepare a new area, run a scenario, switch layers).
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation, useMatch, useNavigate } from "react-router-dom";
import { askAssistantStream, createAoi, type AssistantAction } from "../api/client";
import { Icon, IconButton, useSnackbar } from "./m3";

type Msg = { role: "user" | "bot"; text: string; actions?: AssistantAction[]; sources?: { title: string; uri: string }[]; entry?: string;
  steps?: string[]; thoughts?: string; pending?: boolean; secs?: number };
export type AppCommand = { type: "run"; patch: Record<string, any> } | { type: "layers"; on?: string[]; off?: string[]; fixes?: boolean };
const PENDING = "pravah-pending-command";

/** Send a command to the open area's map; if it is not open yet, it runs when the map finishes loading. */
export function sendCommand(cmd: AppCommand) {
  window.dispatchEvent(new CustomEvent<AppCommand>("pravah:command", { detail: cmd }));
}
export function takePendingCommand(aoiId: string): AppCommand | null {
  try {
    const raw = sessionStorage.getItem(PENDING);
    if (!raw) return null;
    const { aoi, cmd } = JSON.parse(raw);
    if (aoi !== aoiId) return null;
    sessionStorage.removeItem(PENDING);
    return cmd;
  } catch { return null; }
}
/** The map page reports the run it shows, so questions about "this run" use it. */
export function reportRun(runId: string | null) { (window as any).__pravahRun = runId; }

function sessionId(): string {
  try {
    let s = sessionStorage.getItem("pravah-assistant");
    if (!s) { s = crypto.randomUUID(); sessionStorage.setItem("pravah-assistant", s); }
    return s;
  } catch { return "tab-" + Math.random().toString(36).slice(2); }
}

function md(text: string): ReactNode {
  const bold = (s: string) => s.replace(/`([^`]+)`/g, "$1").split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : p.replace(/^\*(.*)\*$/, "$1")));
  const out: ReactNode[] = [];
  let list: string[] = [];
  const flush = () => { if (list.length) { out.push(<ul key={out.length}>{list.map((l, i) => <li key={i}>{bold(l)}</li>)}</ul>); list = []; } };
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*[*-]\s+(.*)/), h = line.match(/^\s*#{1,6}\s+(.*)/);
    if (/^\s*```/.test(line)) continue;  // fence markers: keep the lines, drop the backticks
    if (h) { flush(); out.push(<p key={out.length}><b>{bold(h[1])}</b></p>); }
    else if (m) list.push(m[1]);
    else if (line.trim()) { flush(); out.push(<p key={out.length}>{bold(line)}</p>); }
  }
  flush();
  return out;
}

const host = (u: string, t: string) => t || (() => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } })();
const SUGGEST_HOME = ["Flood-prone areas in Mumbai", "Where did Kerala flood in 2018?", "Open my last area", "Analyse Guwahati for floods"];
const SUGGEST_AREA = ["Which bridge closes first?", "What if 150 mm falls in 3 hours?", "Run IMD very heavy for 6 hours", "Show fixes before the rain"];

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Record<string, "done" | "cancelled">>({});
  const body = useRef<HTMLDivElement>(null);
  const sid = useRef(sessionId());
  const nav = useNavigate();
  const loc = useLocation();
  const snack = useSnackbar();
  const area = useMatch("/area/:aoiId/*");
  const aoiId = area?.params.aoiId ?? null;
  const page = loc.pathname === "/" ? "home" : aoiId ? (loc.pathname.split("/")[3] || "map") : loc.pathname.slice(1);
  useEffect(() => { body.current?.scrollTo({ top: body.current.scrollHeight, behavior: "smooth" }); }, [msgs, busy, open]);

  async function send(q: string) {
    if (!q.trim() || busy) return;
    const t0 = Date.now();
    setMsgs((m) => [...m, { role: "user", text: q }, { role: "bot", text: "", steps: [], thoughts: "", pending: true }]);
    setText("");
    setBusy(true);
    // the reply being written is always the last message
    const upd = (f: (b: Msg) => Msg) => setMsgs((m) => [...m.slice(0, -1), f(m[m.length - 1])]);
    try {
      await askAssistantStream({ session_id: sid.current, message: q, page, aoi_id: aoiId, run_id: aoiId ? (window as any).__pravahRun ?? null : null }, (e) => {
        if (e.type === "step") upd((b) => ({ ...b, steps: [...(b.steps ?? []), e.label], text: "" }));  // text before a tool call was a preamble
        else if (e.type === "thought") upd((b) => ({ ...b, thoughts: (b.thoughts ?? "") + e.text }));
        else if (e.type === "delta") upd((b) => ({ ...b, text: b.text + e.text }));
        else if (e.type === "final") upd((b) => ({ ...b, text: e.reply, actions: e.proposals, sources: e.sources, entry: e.search_entry_point, pending: false, secs: Math.round((Date.now() - t0) / 1000) }));
        else if (e.type === "error") upd((b) => ({ ...b, text: `Sorry, ${e.message}.`, pending: false }));
      });
      upd((b) => (b.pending ? { ...b, pending: false, text: b.text || "Sorry, no answer came back. Please try again." } : b));
    } catch (e) {
      upd((b) => ({ ...b, pending: false, text: `Sorry, the assistant is unavailable right now (${(e as Error).message}).` }));
    } finally { setBusy(false); }
  }

  async function run(a: AssistantAction, key: string) {
    const x = a.args ?? {};
    try {
      switch (a.kind) {
        case "go_to_place":
          nav(`/?lat=${x.lat}&lng=${x.lng}&zoom=${x.zoom ?? 14}&label=${encodeURIComponent(x.label ?? a.label)}`);
          break;
        case "open_area": {
          const v = String(x.view ?? "map");
          nav(v === "projects" ? `/projects?area=${x.aoi_id}` : `/area/${x.aoi_id}${({ brief: "/advisory", "3d": "/3d", drill: "/drill", field: "/verify" } as Record<string, string>)[v] ?? ""}`);
          break;
        }
        case "prepare_area": {
          const r = await createAoi([x.west, x.south, x.east, x.north], String(x.name ?? "New area"));
          snack(`Preparing ${r.aoi.name}: a few minutes`);
          nav(`/area/${r.aoi.aoi_id}`);
          break;
        }
        case "run_scenario":
        case "set_layers": {
          const cmd: AppCommand = a.kind === "run_scenario" ? { type: "run", patch: x } : { type: "layers", on: x.on, off: x.off, fixes: x.fixes };
          if (aoiId && page === "map") sendCommand(cmd);
          else if (aoiId) { sessionStorage.setItem(PENDING, JSON.stringify({ aoi: aoiId, cmd })); nav(`/area/${aoiId}`); }
          break;
        }
        case "open_page":
          nav(x.page === "home" ? "/" : `/${x.page}`);
          break;
      }
      setDone((d) => ({ ...d, [key]: "done" }));
    } catch (e) {
      snack("Could not do that: " + String((e as Error).message));
    }
  }

  return (
    <>
      {!open && (
        <button className="asst-fab sl" onClick={() => setOpen(true)} aria-label="Ask Pravah" title="Ask Pravah (Gemini)">
          <Icon name="auto_awesome" />
        </button>
      )}
      {open && (
        <section className="asst surface-float" role="dialog" aria-label="Ask Pravah">
          <header className="asst-head">
            <Icon name="auto_awesome" className="gem" />
            <div className="grow"><div className="title-s">Ask Pravah</div><div className="body-s muted">{aoiId ? "About this area, or anything else" : "Places, past floods, or the app"}</div></div>
            {msgs.length > 0 && <IconButton icon="restart_alt" label="New chat" small onClick={() => { setMsgs([]); setDone({}); try { sessionStorage.removeItem("pravah-assistant"); } catch { /* ignore */ } sid.current = sessionId(); }} />}
            <IconButton icon="close" label="Close" small onClick={() => setOpen(false)} />
          </header>
          <div className="asst-body" ref={body}>
            {msgs.length === 0 && (
              <div className="asst-empty">
                <p className="body-m">Ask about flood-prone places, past events or this area. I can also take you somewhere, prepare an area or run a scenario; you confirm each step.</p>
                <div className="asst-sugg">{(aoiId ? SUGGEST_AREA : SUGGEST_HOME).map((s) => <button key={s} className="chip sl" onClick={() => send(s)}>{s}</button>)}</div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`asst-msg ${m.role}`}>
                {m.role === "bot" && <Thinking m={m} />}
                {m.role === "bot" ? md(m.text) : m.text}
                {m.actions?.map((a, k) => {
                  const key = `${i}-${k}`, st = done[key];
                  return (
                    <div key={key} className={`asst-action ${st ?? ""}`}>
                      <Icon name={({ go_to_place: "travel_explore", open_area: "map", prepare_area: "add_location_alt", run_scenario: "play_arrow", set_layers: "layers", open_page: "open_in_new" } as Record<string, string>)[a.kind]} className="sm" />
                      <span className="grow">{a.label}</span>
                      {st ? <span className="body-s muted">{st === "done" ? "Done" : "Cancelled"}</span> : <>
                        <button className="btn btn-text small sl" onClick={() => setDone((d) => ({ ...d, [key]: "cancelled" }))}>Cancel</button>
                        <button className="btn btn-filled small sl" onClick={() => run(a, key)}>Confirm</button>
                      </>}
                    </div>
                  );
                })}
                {m.sources && m.sources.length > 0 && (
                  <div className="asst-src">Sources: {m.sources.slice(0, 5).map((s, k) => <a key={k} href={s.uri} target="_blank" rel="noreferrer">{host(s.uri, s.title)}</a>)}</div>
                )}
                {m.entry && <div className="web-entry asst-entry" dangerouslySetInnerHTML={{ __html: m.entry }} />}
              </div>
            ))}
          </div>
          <form className="asst-input" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask anything…" aria-label="Message" maxLength={2000} />
            <IconButton icon="send" label="Send" small disabled={!text.trim() || busy} />
          </form>
        </section>
      )}
    </>
  );
}

/** Gemini-style thinking: an animated sparkle and the current step while working; afterwards a collapsed
 *  "Show thinking" with every step (tool calls) and Gemini's thinking summaries when it sends them. */
function Thinking({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false);
  const steps = m.steps ?? [];
  const has = steps.length > 0 || !!m.thoughts;
  if (!m.pending && !has) return null;
  const now = m.pending ? (steps[steps.length - 1] ?? (m.thoughts ? "Thinking" : "Thinking")) : null;
  return (
    <div className="asst-think">
      <button className="asst-think-head sl" onClick={() => setOpen(!open)} disabled={!has} aria-expanded={open}>
        <span className={`asst-spark ${m.pending ? "on" : ""}`} aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18"><defs><linearGradient id="gspark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#4285f4" /><stop offset=".55" stopColor="#9b72cb" /><stop offset="1" stopColor="#d96570" /></linearGradient></defs>
            <path fill="url(#gspark)" d="M12 2c.6 4.8 4.4 9.4 10 10-5.6.6-9.4 5.2-10 10-.6-4.8-4.4-9.4-10-10 5.6-.6 9.4-5.2 10-10z" /></svg>
        </span>
        {m.pending ? <span className="asst-shimmer">{now}…</span> : <span>{open ? "Hide thinking" : "Show thinking"}{m.secs ? <span className="muted"> · {m.secs} s</span> : null}</span>}
        {has && <Icon name={open ? "expand_less" : "expand_more"} className="sm" />}
      </button>
      {open && (
        <div className="asst-think-body">
          {steps.map((s, k) => <div key={k} className="st"><Icon name={k === steps.length - 1 && m.pending ? "progress_activity" : "check"} className="sm" />{s}</div>)}
          {m.thoughts && <div className="th">{md(m.thoughts)}</div>}
        </div>
      )}
    </div>
  );
}
