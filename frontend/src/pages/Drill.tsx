// Tabletop drill: Gemini plays the control room on a stored scenario. Messages (injects) arrive hour by hour from the
// simulation; the team types its decision; Gemini scores it against the expected actions and the facts, and writes an
// after-action report at the end.
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { answerDrill, drillReport, getAoiStatus, getDrill, getRun, listDrills, startDrill } from "../api/client";
import { Button, Icon, Linear, useSnackbar } from "../components/m3";
import { clockAt } from "../time";
import type { Drill, DrillSummary, RunResult } from "../types/api";
import "./drill.css";

const SCORE = ["No useful action", "Weak", "Adequate", "Strong"];

export default function DrillPage() {
  const { aoiId = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const snack = useSnackbar();
  const [run, setRun] = useState<RunResult | null>(null);
  const [noRun, setNoRun] = useState(false);
  const [past, setPast] = useState<DrillSummary[] | null>(null);
  const [team, setTeam] = useState("");
  const [drill, setDrill] = useState<Drill | null>(null);
  const [busy, setBusy] = useState<"" | "start" | "answer" | "report">("");
  const [cur, setCur] = useState(0);
  const [text, setText] = useState("");
  const [showExpected, setShowExpected] = useState(false);
  const runParam = search.get("run");
  const drillParam = search.get("drill");

  useEffect(() => {
    getAoiStatus(aoiId).then((s) => {
      const rid = runParam || s.latest_run_id;
      if (!rid) { setNoRun(true); return; }
      getRun(rid).then(setRun).catch(() => setNoRun(true));
      listDrills(rid).then(setPast).catch(() => setPast([]));
    }).catch(() => setNoRun(true));
  }, [aoiId, runParam]);
  useEffect(() => {
    if (!drillParam) { setDrill(null); return; }
    getDrill(drillParam).then((d) => {
      setDrill(d);
      const next = d.plan.injects.findIndex((_, i) => !d.responses[String(i)]);
      setCur(next < 0 ? d.plan.injects.length - 1 : next);
    }).catch(() => snack("That drill could not be loaded"));
  }, [drillParam, snack]);

  async function start() {
    if (!run) return;
    setBusy("start");
    try {
      const d = await startDrill(run.run_id, team.trim());
      setSearch((s) => { s.set("drill", d.drill_id); if (runParam) s.set("run", runParam); return s; });
    } catch (e) { snack("The drill could not start: " + String((e as Error).message)); }
    finally { setBusy(""); }
  }
  async function submit() {
    if (!drill || !text.trim()) return;
    setBusy("answer");
    try {
      const ev = await answerDrill(drill.drill_id, cur, text.trim());
      setDrill({ ...drill, responses: { ...drill.responses, [String(cur)]: ev } });
      setText(""); setShowExpected(false);
    } catch (e) { snack("Could not score the decision: " + String((e as Error).message)); }
    finally { setBusy(""); }
  }
  async function finish() {
    if (!drill) return;
    setBusy("report");
    try { const rep = await drillReport(drill.drill_id); setDrill({ ...drill, report: rep }); }
    catch (e) { snack("Could not write the report: " + String((e as Error).message)); }
    finally { setBusy(""); }
  }

  const at = (h: number) => clockAt(drill?.start_local ?? run?.start_local, h) ?? `Hour ${h}`;

  if (noRun) return (
    <div className="doc-page"><div className="doc">
      <h1 className="headline-s">Tabletop drill</h1>
      <p className="body-m">Run a scenario first: the drill is built from its results.</p>
      <Link className="btn btn-filled sl" to={`/area/${aoiId}`}><Icon name="map" /> Open the map</Link>
    </div></div>
  );

  // ---------- setup ----------
  if (!drill) return (
    <div className="doc-page"><div className="doc drill">
      <div>
        <h1 className="headline-s" style={{ margin: 0 }}>Tabletop drill</h1>
        <p className="body-m muted" style={{ margin: "4px 0 0" }}>Rehearse this scenario with your team before the monsoon. Gemini plays the control room: messages arrive hour by hour, built from the simulation (roads and bridges closing, shelters filling, the deadline to move people), plus a few realistic complications. Type what you would order; each decision is scored against the plan, and you get an after-action report with changes for your SOP.</p>
      </div>
      <div className="card outlined stack">
        <div className="row"><Icon name="flood" /><span className="title-s grow">{run ? (run.title || run.rain_label) : "Loading the scenario…"}</span></div>
        <label className="stack-s"><span className="label-l">Team or participant (for the report)</span>
          <input className="dr-input" value={team} onChange={(e) => setTeam(e.target.value)} placeholder="e.g. DEOC Rudraprayag, shift A" maxLength={80} /></label>
        {busy === "start" ? (
          <div className="stack-s"><Linear indeterminate /><span className="body-s muted">Gemini is writing the exercise from the simulation. This takes about a minute.</span></div>
        ) : <Button icon="sports_score" disabled={!run} onClick={start}>Start the drill</Button>}
        <p className="body-s muted" style={{ margin: 0 }}>Exercise only. Messages marked “exercise inject” are invented to test the team; the rest come from the model results.</p>
      </div>
      {past && past.length > 0 && (
        <div className="stack-s">
          <span className="title-s">Earlier drills on this scenario</span>
          {past.map((d) => (
            <button key={d.drill_id} className="row-item sl dr-past" onClick={() => setSearch((s) => { s.set("drill", d.drill_id); return s; })}>
              <Icon name="history" /><span className="txt"><span className="t">{d.participant || "Drill"} · {new Date(d.created_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</span>
                <span className="s">{d.answered} of {d.injects} answered{d.score != null ? ` · score ${d.score}%` : ""}</span></span>
            </button>
          ))}
        </div>
      )}
    </div></div>
  );

  // ---------- running / report ----------
  const inj = drill.plan.injects;
  const ans = drill.responses[String(cur)];
  const answered = Object.keys(drill.responses).length;
  const i = inj[cur];
  return (
    <div className="doc-page"><div className="doc drill">
      <div className="row">
        <div className="grow">
          <h1 className="title-l" style={{ margin: 0 }}>{drill.plan.title}</h1>
          <p className="body-s muted" style={{ margin: "2px 0 0" }}>{drill.participant ? `${drill.participant} · ` : ""}{answered} of {inj.length} answered · {drill.source === "gemini" ? `written by ${drill.model}` : "rule-based (Gemini unavailable)"}</p>
        </div>
        <Button variant="text" icon="close" onClick={() => setSearch((s) => { s.delete("drill"); return s; })}>Leave</Button>
      </div>
      <div className="card tonal"><span className="label-l">Situation at the start</span><p className="body-m" style={{ margin: "4px 0 0" }}>{drill.plan.briefing}</p></div>

      <div className="dr-grid">
        <ol className="dr-steps" aria-label="Messages">
          {inj.map((x, k) => {
            const r = drill.responses[String(k)];
            return (
              <li key={k}>
                <button className={`dr-step sl ${k === cur ? "on" : ""}`} onClick={() => { setCur(k); setShowExpected(false); }}>
                  <span className={`dot s${r ? r.score : "x"}`}>{r ? r.score : k + 1}</span>
                  <span className="txt"><span className="t">{at(x.hour)} · {x.source}</span><span className="s">{x.kind === "fictional" ? "exercise inject" : "from the model"}{r ? ` · ${SCORE[r.score]}` : ""}</span></span>
                </button>
              </li>
            );
          })}
        </ol>

        <section className="stack">
          {drill.report ? (
            <div className="card outlined stack dr-report">
              <div className="row"><span className="title-l grow">After-action report</span><span className={`tag ${drill.report.score >= 67 ? "ok" : drill.report.score >= 40 ? "mod" : "crit"}`}>Score {drill.report.score}%</span></div>
              <p className="body-m">{drill.report.summary}</p>
              {([["What went well", drill.report.strengths, "check_circle"], ["Gaps", drill.report.gaps, "error"], ["Changes for the SOP / flood plan", drill.report.sop_changes, "edit_note"], ["Training needs", drill.report.training_needs, "school"]] as const).map(([t, xs, ic]) => xs.length ? (
                <div key={t}><span className="title-s row" style={{ gap: 6 }}><Icon name={ic} className="sm" />{t}</span><ul className="body-m">{xs.map((x, k) => <li key={k}>{x}</li>)}</ul></div>
              ) : null)}
              <div className="row no-print"><Button variant="tonal" icon="print" onClick={() => window.print()}>Print or save as PDF</Button></div>
            </div>
          ) : (
            <div className="card outlined stack dr-inject">
              <div className="row"><span className="label-l grow">{at(i.hour)} · {i.source}</span>{i.kind === "fictional" && <span className="tag info">exercise inject</span>}</div>
              <p className="title-m dr-msg">{i.message}</p>
              {!ans ? (
                <>
                  <textarea className="dr-text" rows={4} value={text} onChange={(e) => setText(e.target.value)} disabled={busy === "answer"}
                    placeholder="What do you order, who does it, and where? e.g. Tehsildar to evacuate the riverfront lanes in Gulabrai to the school shelter now; police to close the bypass bridge." />
                  <div className="row">
                    <span className="body-s muted grow">Answer within {i.decide_within_min} minutes in a real exercise.</span>
                    <Button icon={busy === "answer" ? undefined : "send"} disabled={!text.trim() || busy === "answer"} onClick={submit}>{busy === "answer" ? "Gemini is scoring…" : "Submit decision"}</Button>
                  </div>
                </>
              ) : (
                <div className="stack-s dr-eval">
                  <p className="body-m" style={{ margin: 0 }}><b>Your decision:</b> {ans.response}</p>
                  <div className="row"><span className={`dot s${ans.score}`}>{ans.score}</span><span className="title-s grow">{SCORE[ans.score]}</span></div>
                  <p className="body-m" style={{ margin: 0 }}>{ans.verdict}</p>
                  {ans.good.length > 0 && <ul className="body-s good">{ans.good.map((x, k) => <li key={k}>{x}</li>)}</ul>}
                  {ans.missed.length > 0 && <ul className="body-s missed">{ans.missed.map((x, k) => <li key={k}>{x}</li>)}</ul>}
                  {ans.risk && <p className="body-s" style={{ margin: 0 }}><b>Risk:</b> {ans.risk}</p>}
                  {ans.better && <p className="body-s" style={{ margin: 0 }}><b>Stronger:</b> {ans.better}</p>}
                </div>
              )}
              <button className="btn btn-text small sl" style={{ alignSelf: "flex-start" }} onClick={() => setShowExpected(!showExpected)}>
                <Icon name={showExpected ? "expand_less" : "expand_more"} /> {showExpected ? "Hide" : "Show"} what a strong response includes</button>
              {showExpected && <ul className="body-s">{i.expected_actions.map((x, k) => <li key={k}>{x}</li>)}</ul>}
              <div className="row">
                {cur > 0 && <Button variant="text" icon="arrow_back" onClick={() => { setCur(cur - 1); setShowExpected(false); }}>Previous</Button>}
                <span className="grow" />
                {cur < inj.length - 1 ? <Button variant={ans ? "filled" : "text"} icon="arrow_forward" iconRight onClick={() => { setCur(cur + 1); setShowExpected(false); }}>{ans ? "Next message" : "Skip"}</Button>
                  : <Button icon={busy === "report" ? undefined : "summarize"} disabled={!answered || busy === "report"} onClick={finish}>{busy === "report" ? "Writing the report…" : "Finish: after-action report"}</Button>}
              </div>
            </div>
          )}
          {!drill.report && answered > 0 && cur < inj.length - 1 && <Button variant="text" icon="summarize" onClick={finish} disabled={busy === "report"}>Finish early and get the report</Button>}
        </section>
      </div>
    </div></div>
  );
}
