// "Fix before the rain": places where maintenance would most reduce flooding, each with the evidence it rests on.
// Evidence kinds are kept apart on purpose: web reports (cited), open satellite imagery checked by Gemini, and model
// estimates that need a site visit. Google satellite and Street View are only opened for a person to look at.
import SearchChip from "./SearchChip";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { apiUrl } from "../api/client";
import type { Improvement, ImprovementCategory, Improvements } from "../types/api";
import { markerUrl } from "../layers/factories";
import { Button, Chip, Icon, IconButton } from "./m3";

const BASIS: Record<Improvement["basis"], { icon: string; label: string; tip: string }> = {
  web: { icon: "newspaper", label: "Reported on the web", tip: "Named in news or municipal reports (links below); position from Google geocoding" },
  imagery: { icon: "satellite_alt", label: "Seen from space", tip: "Sentinel-2 / Dynamic World at 10 m, checked by Gemini" },
  model: { icon: "calculate", label: "Model estimate", tip: "Ranked by water arriving and people at risk; the model cannot see the site, so check it" },
};

export function basisLine(it: Improvement): string {
  if (it.basis === "imagery" && it.ai) return it.ai.verdict === "visible" ? "Seen from space · Gemini agrees" : "Seen from space · Gemini unsure";
  return BASIS[it.basis].label;
}

export default function ImprovementsPanel({ data, selected, onSelect, onClose, onLook, onStreetView, onField, cats, setCats }: {
  data: Improvements; selected: Improvement | null; onSelect: (it: Improvement | null) => void; onClose: () => void;
  onLook: (it: Improvement) => void; onStreetView: (it: Improvement) => void; onField: (it: Improvement) => void;
  cats: Set<ImprovementCategory> | null; setCats: (c: Set<ImprovementCategory> | null) => void;
}) {
  const items = data.items ?? [];
  const counts = data.counts ?? {};
  const shown = useMemo(() => items.filter((it) => !cats || cats.has(it.category)), [items, cats]);
  const toggle = (c: ImprovementCategory) => {
    const n = new Set(cats ?? []);
    if (n.has(c)) n.delete(c); else n.add(c);
    setCats(n.size ? n : null);
  };
  return (
    <section className="imp-panel surface-float" aria-label="Fix before the rain">
      {selected ? <Detail it={selected} data={data} onBack={() => onSelect(null)} onClose={onClose} onLook={onLook} onStreetView={onStreetView} onField={onField} /> : (
        <>
          <header className="imp-head">
            <div className="grow">
              <div className="title-m">Fix before the rain <span className="muted">· {items.length}</span></div>
              <div className="body-s muted">Places where maintenance would most reduce flooding, best first. Tap one for its evidence.</div>
            </div>
            <IconButton icon="close" label="Close" small onClick={onClose} />
          </header>
          <div className="imp-chips">
            {Object.entries(data.categories ?? {}).filter(([k]) => counts[k]).map(([k, label]) => (
              <Chip key={k} small label={`${shortCat(k as ImprovementCategory, label)} ${counts[k]}`} selected={!!cats?.has(k as ImprovementCategory)}
                onClick={() => toggle(k as ImprovementCategory)} />
            ))}
          </div>
          <ol className="imp-list">
            {shown.map((it) => (
              <li key={it.id}>
                <button className="imp-row sl" onClick={() => onSelect(it)}>
                  <span className="imp-n">{it.id.slice(1)}</span>
                  <span className="grow">
                    <span className="t">{it.title}</span>
                    <span className="s">{it.place || it.why[0]}</span>
                    <span className={`imp-basis ${it.basis}`}><Icon name={BASIS[it.basis].icon} className="sm" />{basisLine(it)}</span>
                  </span>
                  <Icon name="chevron_right" />
                </button>
              </li>
            ))}
            {!shown.length && <li className="body-s muted" style={{ padding: 16 }}>Nothing in these categories.</li>}
          </ol>
          <footer className="imp-foot body-s muted">
            {(data.notes ?? []).map((n) => <p key={n}>{n}</p>)}
            <details><summary>How this list is made</summary>
              <p>Drains, culverts, low spots and single-exit roads are ranked by our flood and road models; channels,
              new construction and bare ground come from 10 m open satellite data (Sentinel-2, Dynamic World), each checked by Gemini;
              reported spots come from Gemini with Google Search, kept only with a link that opens and names the place.
              10 m imagery cannot show a blocked drain or a rubbish pile, so those need a site visit: use <b>Check in the field</b>.</p>
              {data.attribution && <p>{data.attribution}</p>}
            </details>
            {data.search_entry_point && <SearchChip html={data.search_entry_point} />}
          </footer>
        </>
      )}
    </section>
  );
}

function shortCat(c: ImprovementCategory, label: string): string {
  return ({ reported: "Reported", culvert: "Culverts & bridges", low_spot: "Low spots", choked_channel: "Choked channels",
    single_exit: "Single exits", encroachment: "New construction", bare_ground: "Bare ground" } as Record<string, string>)[c] ?? label;
}

function Detail({ it, data, onBack, onClose, onLook, onStreetView, onField }: {
  it: Improvement; data: Improvements; onBack: () => void; onClose: () => void;
  onLook: (it: Improvement) => void; onStreetView: (it: Improvement) => void; onField: (it: Improvement) => void;
}) {
  const [big, setBig] = useState<number | null>(null);
  const b = BASIS[it.basis];
  return (
    <div className="imp-detail">
      <header className="imp-head">
        <IconButton icon="arrow_back" label="Back to the list" small onClick={onBack} />
        <img src={markerUrl("fix")} alt="" width={22} height={22} />
        <div className="grow title-m">{it.id.slice(1)}. {it.title}</div>
        <IconButton icon="close" label="Close" small onClick={onClose} />
      </header>
      {it.place && <div className="body-m" style={{ margin: "-4px 0 8px 40px" }}>{it.place}</div>}
      <div className={`imp-basis big ${it.basis}`} title={b.tip}><Icon name={b.icon} className="sm" />{basisLine(it)}
        {it.confidence === "check" && <span className="muted"> · check on site</span>}</div>

      <h4 className="label-l">Why here</h4>
      <ul className="imp-why">{it.why.map((w) => <li key={w}>{w}</li>)}</ul>

      {it.images.length > 0 && (
        <>
          <h4 className="label-l">Satellite evidence</h4>
          <div className="imp-imgs">
            {it.images.map((im, i) => (
              <figure key={im.key} className={im.key.endsWith("_wide") ? "wide" : ""}>
                <button className="imp-img sl" onClick={() => setBig(i)} aria-label={`Enlarge: ${im.caption}`}>
                  <img src={apiUrl(im.url)} alt={im.caption} decoding="async" />
                  <Icon name="open_in_full" className="sm" />
                </button>
                <figcaption>{im.caption}</figcaption>
              </figure>
            ))}
          </div>
          <p className="body-s muted" style={{ margin: "4px 0 0" }}>Copernicus Sentinel-2, 10 m pixels; the ring marks the spot. Tap an image to enlarge.</p>
          {big != null && <Lightbox images={it.images} at={big} setAt={setBig} />}
        </>
      )}
      {it.ai && (
        <div className="imp-ai">
          <Icon name="auto_awesome" className="sm" />
          <div><b>Gemini looked at these images:</b> {it.ai.seen}
            <div className="body-s muted">{it.ai.verdict === "visible" ? "It agrees the images show this." : "It could not confirm this from 10 m images; check on site."} ({it.ai.model})</div></div>
        </div>
      )}
      {it.sources.length > 0 && (
        <>
          <h4 className="label-l">Sources</h4>
          <ol className="imp-src">{it.sources.map((s, i) => (
            <li key={s.uri}><a href={s.uri} target="_blank" rel="noreferrer" title={s.uri}><span className="n">{i + 1}</span>{s.title && !s.title.includes("/") ? s.title : host(s.uri)}</a></li>
          ))}</ol>
          {data.search_entry_point && <SearchChip html={data.search_entry_point} />}
        </>
      )}

      <h4 className="label-l">What to do</h4>
      <p className="body-m" style={{ margin: "0 0 4px" }}>{it.action}</p>
      <p className="body-s muted" style={{ margin: 0 }}>Suggested owner: {it.department}</p>

      <div className="imp-actions">
        <Button variant="tonal" size="small" icon="satellite" onClick={() => onLook(it)}>Look closer</Button>
        <Button variant="tonal" size="small" icon="streetview" onClick={() => onStreetView(it)}>Street View</Button>
        <Button variant="outlined" size="small" icon="photo_camera" onClick={() => onField(it)}>Check in the field</Button>
      </div>
      <p className="body-s muted" style={{ marginTop: 8 }}>Look closer and Street View open Google imagery for you to inspect; it is not analysed by Pravah.</p>
    </div>
  );
}

/** One image large, with the others a swipe or arrow key away. */
function Lightbox({ images, at, setAt }: { images: Improvement["images"]; at: number; setAt: (i: number | null) => void }) {
  const n = images.length, im = images[at];
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAt(null);
      else if (e.key === "ArrowRight") setAt((at + 1) % n);
      else if (e.key === "ArrowLeft") setAt((at + n - 1) % n);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [at, n, setAt]);
  return createPortal(
    <div className="lightbox" role="dialog" aria-modal="true" aria-label={im.caption} onClick={() => setAt(null)}>
      <figure onClick={(e) => e.stopPropagation()}>
        <img src={apiUrl(im.url)} alt={im.caption} />
        <figcaption><span className="grow">{im.caption} <span className="muted">· {at + 1} of {n}</span></span>
          <a href={apiUrl(im.url)} target="_blank" rel="noreferrer">Open full size</a></figcaption>
      </figure>
      {n > 1 && <>
        <div className="lb-prev"><IconButton icon="chevron_left" label="Previous image" variant="tonal" onClick={(e) => { e.stopPropagation(); setAt((at + n - 1) % n); }} /></div>
        <div className="lb-next"><IconButton icon="chevron_right" label="Next image" variant="tonal" onClick={(e) => { e.stopPropagation(); setAt((at + 1) % n); }} /></div>
      </>}
      <div className="lb-close"><IconButton icon="close" label="Close" variant="tonal" onClick={() => setAt(null)} /></div>
    </div>, document.body);
}

const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
