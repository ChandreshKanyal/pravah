// Public alert draft (CAP 1.2) for a run: Gemini text in English and Hindi checked against the facts, the flooded area
// as alert polygons, CAP severity/urgency/certainty, and the XML for SACHET. Always a draft for an officer to issue.
import { useEffect, useState } from "react";
import { capUrl, draftAlert, getAlert } from "../api/client";
import type { AlertDraft } from "../types/api";
import { Button, Dialog, Icon, Linear, Segmented, useSnackbar } from "./m3";

export default function AlertDialog({ runId, open, onClose }: { runId: string | null; open: boolean; onClose: () => void }) {
  const snack = useSnackbar();
  const [a, setA] = useState<AlertDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [lang, setLang] = useState<"en" | "hi">("en");
  useEffect(() => { if (open && runId) getAlert(runId).then(setA).catch(() => setA(null)); }, [open, runId]);
  const make = () => {
    if (!runId) return;
    setBusy(true);
    draftAlert(runId).then(setA).catch((e) => snack("Could not draft the alert: " + String(e.message))).finally(() => setBusy(false));
  };
  const t = a?.texts[lang];
  const copy = (s: string) => navigator.clipboard?.writeText(s).then(() => snack("Copied")).catch(() => undefined);
  return (
    <Dialog open={open} title="Public alert (draft)" icon="campaign" onClose={onClose}
      actions={<Button variant="text" onClick={onClose}>Close</Button>}>
      <div className="stack alert-dlg">
        <p className="body-s muted" style={{ margin: 0 }}>A ready-to-review alert in CAP 1.2, the format of NDMA's SACHET alert system: SMS and full text in English and Hindi, with the flooded area as the alert polygon. It stays a draft until an authorised officer issues it through SACHET or the state channel.</p>
        {!a && !busy && <Button icon="auto_awesome" onClick={make} disabled={!runId}>Draft the alert with Gemini</Button>}
        {busy && <div className="stack-s"><Linear indeterminate /><span className="body-s muted">Writing the alert from this scenario's facts (about 15 seconds)…</span></div>}
        {a && t && !busy && (
          <>
            <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
              <span className="tag crit">Severity: {a.severity}</span><span className="tag high">Urgency: {a.urgency}</span><span className="tag info">Certainty: {a.certainty}</span>
              <span className="tag">{a.polygons.length} area polygon{a.polygons.length === 1 ? "" : "s"}</span>
            </div>
            <Segmented label="Language" value={lang} onChange={setLang} options={[{ value: "en", label: "English" }, { value: "hi", label: "हिन्दी" }]} />
            <div className="card outlined stack-s">
              <div className="row"><span className="label-l grow">SMS ({t.sms.length}/160)</span><Button variant="text" size="small" icon="content_copy" onClick={() => copy(t.sms)}>Copy</Button></div>
              <p className="body-m" style={{ margin: 0 }}>{t.sms}</p>
            </div>
            <div className="stack-s">
              <span className="title-s">{t.headline}</span>
              <p className="body-s" style={{ margin: 0 }}>{t.description}</p>
              <p className="body-s" style={{ margin: 0 }}><b>{lang === "hi" ? "क्या करें:" : "What to do:"}</b> {t.instruction}</p>
              <p className="body-s muted" style={{ margin: 0 }}>Area: {a.area_desc}</p>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <a className="btn btn-filled sl" href={capUrl(a.run_id)} download><Icon name="download" /> CAP XML</a>
              <Button variant="text" icon="refresh" onClick={make}>Redraft</Button>
            </div>
            <p className="body-s muted" style={{ margin: 0 }}>{a.by === "gemini" ? `Written by ${a.model}; every number checked against the scenario.` : "Template text (Gemini unavailable or its numbers did not match the facts)."}</p>
          </>
        )}
      </div>
    </Dialog>
  );
}
