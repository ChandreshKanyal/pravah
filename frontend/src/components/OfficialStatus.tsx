import { useState } from "react";
import { setOfficial } from "../api/client";
import type { Official } from "../types/api";
import { Button, Dialog, Field, Icon, Segmented, useSnackbar } from "./m3";

// Official sources are linked, not scraped: IMD has no public district API and CWC publishes bulletins. Staff type in
// the current IMD colour code and CWC gauge reading so the model can be read against them.
const IMD = { green: "No warning", yellow: "Watch (be updated)", orange: "Alert (be prepared)", red: "Warning (take action)" } as const;
const IMD_URL = "https://mausam.imd.gov.in/";
const CWC_URL = "https://ffs.india-water.gov.in/";
const floodHub = (lat: number, lng: number) => `https://sites.research.google/floods/l/${lat.toFixed(3)}/${lng.toFixed(3)}/11`;

export function cwcText(o: Official | null | undefined): string | null {
  if (!o || o.cwc_level_m == null) return null;
  const st = o.cwc_station ? `${o.cwc_station}: ` : "";
  if (o.cwc_danger_m != null) {
    const d = o.cwc_level_m - o.cwc_danger_m;
    return `${st}${Math.abs(d).toFixed(2)} m ${d >= 0 ? "ABOVE" : "below"} danger level`;
  }
  if (o.cwc_warning_m != null) {
    const d = o.cwc_level_m - o.cwc_warning_m;
    return `${st}${Math.abs(d).toFixed(2)} m ${d >= 0 ? "above" : "below"} warning level`;
  }
  return `${st}${o.cwc_level_m.toFixed(2)} m`;
}

export default function OfficialStatus({ aoiId, official, centre, onChange, compact }: {
  aoiId: string; official: Official | null | undefined; centre: [number, number] | null; onChange: (o: Official) => void; compact?: boolean;
}) {
  const snack = useSnackbar();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState<Partial<Official>>({});
  const o = official;
  const cwc = cwcText(o);
  const edit = () => { setF({ imd_warning: o?.imd_warning ?? null, imd_valid_for: o?.imd_valid_for ?? "", cwc_station: o?.cwc_station ?? "", cwc_level_m: o?.cwc_level_m ?? null,
    cwc_warning_m: o?.cwc_warning_m ?? null, cwc_danger_m: o?.cwc_danger_m ?? null, cwc_hfl_m: o?.cwc_hfl_m ?? null, note: o?.note ?? "" }); setOpen(true); };
  const num = (k: keyof Official) => (
    <input type="number" step="0.01" value={(f[k] as number | null) ?? ""} placeholder=" " onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? null : Number(e.target.value) })} />
  );

  return (
    <section className={`official ${compact ? "compact" : ""}`} aria-label="Official warnings">
      <div className="row nowrap" style={{ gap: 8 }}>
        <Icon name="verified" className="sm" />
        <span className="title-s grow">Official warnings</span>
        <Button variant="text" size="small" icon="edit" onClick={edit}>{o ? "Update" : "Enter"}</Button>
      </div>
      <div className="official-row">
        <span className={`imd-badge ${o?.imd_warning ?? "none"}`}>
          IMD: {o?.imd_warning ? `${o.imd_warning[0].toUpperCase() + o.imd_warning.slice(1)} · ${IMD[o.imd_warning]}` : "not entered"}
        </span>
        <span className="cwc">{cwc ? `CWC ${cwc}` : "CWC gauge: not entered"}</span>
      </div>
      {o?.at && <span className="body-s muted">Entered by {o.entered_by}{o.verified ? "" : " (unverified)"}, {new Date(o.at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}{o.imd_valid_for ? ` · valid for ${o.imd_valid_for}` : ""}</span>}
      <div className="row body-s" style={{ gap: 12 }}>
        <a href={IMD_URL} target="_blank" rel="noreferrer">IMD district warnings <Icon name="open_in_new" className="xs" /></a>
        <a href={CWC_URL} target="_blank" rel="noreferrer">CWC flood forecast <Icon name="open_in_new" className="xs" /></a>
        {centre && <a href={floodHub(centre[1], centre[0])} target="_blank" rel="noreferrer">Google Flood Hub <Icon name="open_in_new" className="xs" /></a>}
      </div>

      <Dialog open={open} title="Official warnings" icon="verified" onClose={() => setOpen(false)}
        actions={<>
          <Button variant="text" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={async () => {
            try { const r = await setOfficial(aoiId, f); onChange(r); setOpen(false); snack("Official warnings saved"); }
            catch (e) { snack(String((e as Error).message)); }
          }}>Save</Button>
        </>}>
        <div className="stack">
          <p className="body-s muted">Copy the current values from the IMD and CWC websites. They are shown next to the model and recorded with your name.</p>
          <span className="label-l">IMD district colour code</span>
          <Segmented label="IMD colour" block value={(f.imd_warning ?? "none") as string} onChange={(v) => setF({ ...f, imd_warning: v === "none" ? null : (v as Official["imd_warning"]) })}
            options={[{ value: "none", label: "None" }, { value: "green", label: "Green" }, { value: "yellow", label: "Yellow" }, { value: "orange", label: "Orange" }, { value: "red", label: "Red" }]} />
          <Field label="Valid for" support="e.g. 17 Oct, heavy rain"><input value={f.imd_valid_for ?? ""} placeholder=" " onChange={(e) => setF({ ...f, imd_valid_for: e.target.value })} /></Field>
          <Field label="CWC gauge station" support="e.g. Rudraprayag (Alaknanda)"><input value={f.cwc_station ?? ""} placeholder=" " onChange={(e) => setF({ ...f, cwc_station: e.target.value })} /></Field>
          <div className="grid-2">
            <Field label="Current level (m)">{num("cwc_level_m")}</Field>
            <Field label="Warning level (m)">{num("cwc_warning_m")}</Field>
            <Field label="Danger level (m)">{num("cwc_danger_m")}</Field>
            <Field label="Highest flood level (m)">{num("cwc_hfl_m")}</Field>
          </div>
          <Field label="Note"><input value={f.note ?? ""} placeholder=" " onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
        </div>
      </Dialog>
    </section>
  );
}
