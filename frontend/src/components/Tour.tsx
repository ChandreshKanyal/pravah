// Guided tour (human request 18 Oct): starts on the first visit to the home page and walks through the two ways in
// (a new area or a prepared one), then the 2D map, 3D, the brief and the drill of a prepared area, moving between pages
// itself. Every card has Back, Next and Skip tour; skipping or finishing ends it for good, and the ? in the top bar
// replays it. A card whose target is not on screen (a phone layout, a list still loading) is shown in the middle.
import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getAoiStatus } from "../api/client";
import { Button } from "./m3";

type Page = "home" | "map" | "3d" | "brief" | "drill";
type Step = { page: Page; target?: string; title: string; body: string; next?: string };

const KEY = "pravah.tour.v1";
const SHOWCASE = "56f044f26351";  // Rudraprayag, the first prepared area on the home page (Explore DEMOS)
const START = "pravah:tour";

const STEPS: Step[] = [
  { page: "home", title: "Welcome to Pravah",
    body: "Pravah drafts a flood evacuation plan for any place in India: where the water goes, who has to move, and where they can go in time. This tour takes about a minute." },
  { page: "home", target: ".explore .search", title: "Start a new area",
    body: "Search for a town, district or river anywhere in India…" },
  { page: "home", target: '[data-tour="draw"]', title: "…and draw it",
    body: "Draw a box up to 10 km across. Pravah reads the terrain, rivers, rainfall history, roads, buildings and shelters for it in a few minutes, then you run scenarios on it." },
  { page: "home", target: '[data-tour="demos"]', title: "Or open a prepared area", next: "Open Rudraprayag",
    body: "Five areas are ready, each with a different storm: a cloudburst, the live forecast, a real past flood, a worst case and everything at once. The tour continues in Rudraprayag." },

  { page: "map", target: '[data-tour="scen-chip"]', title: "A simulated storm",
    body: "The map shows this area's saved scenario: flood depth in blue, roads closed by water in red, evacuation routes in green, shelters in use as blue markers. Live switches back to today's roads." },
  { page: "map", target: ".ws-map .bottom", title: "Play the storm",
    body: "Press play or drag the timeline to step through the storm hour by hour. Roads and bridges close as the water rises, and routes show when they are cut." },
  { page: "map", title: "Click a shelter or a route",
    body: "Click any shelter marker or green route on the map. A card shows the checks behind the choice (stays dry, height above nearby water, roads at the door, room inside) and Gemini's plain-words explanation." },
  { page: "map", target: ".ws-panel .tabs", title: "Scenario and results",
    body: "Scenario: the rain (live forecast, a past storm, record rain, a cloudburst), river level, visitors and evacuation hour. Results: who moves, to which shelters, by which routes. What-if: ask Gemini to set up a scenario. Compare and History: earlier runs." },
  { page: "map", target: ".ws-panel .panel-foot", title: "Run it",
    body: "After changing the scenario, press Run scenario (about a minute). Every run is saved and becomes the one the area opens on." },
  { page: "map", target: ".imp-chip", title: "Fixes before the monsoon",
    body: "Drains, culverts and low spots to clear, and waterlogging spots reported on the web with their sources. The brief includes the most important ones." },
  { page: "map", target: '.navpills a[href*="/3d"]', title: "Next: 3D", next: "Open 3D",
    body: "See the same storm over the real terrain." },

  { page: "3d", target: ".v3d-panel", title: "The storm in 3D",
    body: "The flow model every five minutes over the terrain and satellite imagery. Switch water flow or hourly map, depth or danger, and turn roads, routes, shelters and bridges on or off." },
  { page: "3d", target: ".v3d-time", title: "Timeline",
    body: "Play the storm here; the clock shows the local time and the rain at that moment." },
  { page: "3d", title: "Look around",
    body: "Drag to turn, right-drag to move, scroll to zoom. Click a shelter or route for its explanation card, or click the water to see its depth over the storm." },
  { page: "3d", target: '.navpills a[href*="/advisory"]', title: "Next: the brief", next: "Open the brief",
    body: "The plan for the District Magistrate." },

  { page: "brief", target: ".bottom-line", title: "The bottom line",
    body: "Gemini drafts the brief from this scenario's facts: who must move, from where and by when." },
  { page: "brief", target: ".deadline", title: "Move-by deadline",
    body: "When the first evacuation route closes and how many people must have moved by then." },
  { page: "brief", target: ".adv-grid .tabs", title: "Actions by horizon",
    body: "The incoming storm, before the monsoon, and long term, each with a department, priority and deadline. Every number is checked against the model, and the chips show the facts each action cites." },
  { page: "brief", target: '[data-tour="adv-actions"]', title: "Share and alert",
    body: "Share the brief (also in Hindi), draft a public alert in India's CAP alert format, or print it." },
  { page: "brief", target: ".review-panel", title: "Review and approval",
    body: "An official reviews, edits and approves the brief. Every version is kept." },
  { page: "brief", target: '.navpills a[href*="/drill"]', title: "Next: the drill", next: "Open the drill",
    body: "Rehearse this plan with your team." },

  { page: "drill", target: ".doc.drill .card.outlined", title: "Tabletop drill",
    body: "Gemini plays the control room: messages arrive hour by hour from the simulation, your team decides, and the answers are scored in a report." },
  { page: "drill", target: ".asst-fab", title: "Ask Pravah",
    body: "Ask in plain words at any time, for example \"What if the evacuation starts two hours later?\". Gemini reads the results and proposes a run; you decide whether to run it." },
  { page: "drill", target: '[data-tour="help"]', title: "That's the tour", next: "Done",
    body: "Replay it any time from here. Pravah's outputs are drafts for official review, never orders." },
];

function pageOf(path: string): Page | null {
  if (path === "/") return "home";
  if (!path.startsWith("/area/")) return null;
  if (path.endsWith("/3d")) return "3d";
  if (path.endsWith("/advisory")) return "brief";
  if (path.endsWith("/drill")) return "drill";
  return /^\/area\/[^/]+(\/run\/[^/]+)?$/.test(path) ? "map" : null;
}

function seen(): boolean {
  try { return localStorage.getItem(KEY) === "done"; } catch { return false; }
}
function markSeen() {
  try { localStorage.setItem(KEY, "done"); } catch { /* private window: the tour may show again */ }
}

/** Replay the tour (the ? button in the top bar). */
export function startTour() { window.dispatchEvent(new Event(START)); }

export default function Tour({ aoiId, runId }: { aoiId?: string; runId: string | null }) {
  const loc = useLocation();
  const nav = useNavigate();
  const page = pageOf(loc.pathname);
  const [i, setI] = useState<number | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [vw, setVw] = useState({ w: window.innerWidth, h: window.innerHeight });
  const step = i == null ? null : STEPS[i];

  // the tour's own pages for the area it is showing
  const pathFor = useCallback((p: Page, area = aoiId, run = runId) => {
    if (!area) return "/";
    const q = run ? `?run=${run}` : "";
    return { home: "/", map: `/area/${area}${q}`, "3d": `/area/${area}/3d${q}`, drill: `/area/${area}/drill${q}`,
      brief: run ? `/area/${area}/run/${run}/advisory` : `/area/${area}/advisory` }[p];
  }, [aoiId, runId]);

  const end = useCallback(() => { markSeen(); setI(null); }, []);

  // first visit to the home page; the ? button replays from where the user is
  useEffect(() => { if (page === "home" && !seen() && i == null) setI(0); }, [page]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const go = () => {
      const first = page && page !== "home" && aoiId ? STEPS.findIndex((s) => s.page === "map") : 0;
      if (first > 0 && page !== "map") nav(pathFor("map"));
      else if (first === 0 && page !== "home") nav("/");
      setI(first);
    };
    window.addEventListener(START, go);
    return () => window.removeEventListener(START, go);
  }, [page, aoiId, nav, pathFor]);

  // the user went elsewhere on their own: carry on from that page's first card, or stop where the tour has none
  useEffect(() => {
    if (!step || step.page === page) return;
    const t = window.setTimeout(() => {
      const j = page ? STEPS.findIndex((s) => s.page === page) : -1;
      if (j >= 0 && (page !== "home" || i === 0)) setI(j); else setI(null);
    }, 400);  // our own navigation lands first
    return () => clearTimeout(t);
  }, [page]);  // eslint-disable-line react-hooks/exhaustive-deps

  // follow the target as the page loads and moves
  useLayoutEffect(() => {
    if (!step) return;
    let gone = 0;
    const find = () => {
      const el = step.target ? document.querySelector<HTMLElement>(step.target) : null;
      const r = el?.getBoundingClientRect();
      if (r && r.width > 0 && r.height > 0) {
        setRect((old) => (old && old.x === r.x && old.y === r.y && old.width === r.width && old.height === r.height ? old : r));
        if (gone === 0) el!.scrollIntoView({ block: "nearest", inline: "nearest" });
        gone = 1;
      } else setRect(null);
      setVw({ w: window.innerWidth, h: window.innerHeight });
    };
    find();
    const t = window.setInterval(find, 250);
    window.addEventListener("resize", find);
    return () => { clearInterval(t); window.removeEventListener("resize", find); };
  }, [step]);

  const go = useCallback(async (j: number) => {
    if (j < 0) return;
    if (j >= STEPS.length) { end(); return; }
    const to = STEPS[j];
    if (to.page !== page) {
      if (to.page === "map" && page === "home") {  // into the prepared area, on its saved scenario
        const s = await getAoiStatus(SHOWCASE).catch(() => null);
        nav(pathFor("map", SHOWCASE, s?.latest_run_id ?? null));
      } else if (to.page === "home") nav("/");
      else nav(pathFor(to.page));
    }
    setI(j);
  }, [page, nav, pathFor, end]);

  useEffect(() => {
    if (i == null) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") end();
      else if (e.key === "ArrowRight") go(i + 1);
      else if (e.key === "ArrowLeft") go(i - 1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [i, go, end]);

  if (!step || i == null || step.page !== page) return null;

  // the card goes below the target, else above, else beside it; in the middle when there is no target
  const W = Math.min(360, vw.w - 32), PAD = 8, GAP = 14, CARD_H = 230;
  let pos: React.CSSProperties = { left: (vw.w - W) / 2, top: Math.max(16, vw.h / 2 - CARD_H / 2) };
  if (rect) {
    const left = Math.min(Math.max(16, rect.left + rect.width / 2 - W / 2), vw.w - W - 16);
    if (rect.bottom + GAP + CARD_H < vw.h) pos = { left, top: rect.bottom + PAD + GAP };
    else if (rect.top - GAP - CARD_H > 0) pos = { left, bottom: vw.h - rect.top + PAD + GAP };
    else if (rect.right + GAP + W < vw.w) pos = { left: rect.right + PAD + GAP, top: Math.min(Math.max(16, rect.top), vw.h - CARD_H - 16) };
    else if (rect.left - GAP - W > 0) pos = { left: rect.left - PAD - GAP - W, top: Math.min(Math.max(16, rect.top), vw.h - CARD_H - 16) };
  }
  const last = i === STEPS.length - 1;
  return (
    <div className="tour" role="dialog" aria-modal="true" aria-label={`Guided tour: ${step.title}`}>
      {rect ? <div className="tour-spot" style={{ left: rect.left - PAD, top: rect.top - PAD, width: rect.width + 2 * PAD, height: rect.height + 2 * PAD }} />
        : <div className="tour-dim" />}
      <div className="card elevated tour-card" style={{ ...pos, width: W }}>
        <div className="tour-top">
          <span className="label-m muted">{i + 1} of {STEPS.length}</span>
          {!last && <button className="btn btn-text small sl" onClick={end}>Skip tour</button>}
        </div>
        <div className="title-m">{step.title}</div>
        <p className="body-m">{step.body}</p>
        <div className="tour-actions">
          {i > 0 ? <Button variant="text" icon="arrow_back" onClick={() => go(i - 1)}>Back</Button> : <span />}
          <Button icon={last ? "check" : "arrow_forward"} iconRight={!last} onClick={() => go(i + 1)}>
            {step.next ?? (i === 0 ? "Start the tour" : "Next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
