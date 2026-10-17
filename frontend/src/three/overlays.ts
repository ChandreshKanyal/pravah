// The 2D map's scenario layers in 3D: roads (open grey; orange where they close later, red once closed, only on the
// blocked pieces), exit routes to shelters (teal, faded and dashed once a road on them closes), shelter zones (blue
// ring with a labelled pin) and closing bridges. Lines are draped on the flow model's ground and follow the hour.
import * as THREE from "three";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { LineSegments2 } from "three/addons/lines/LineSegments2.js";
import { LineSegmentsGeometry } from "three/addons/lines/LineSegmentsGeometry.js";
import type { Dem } from "./scene";

type XY = [number, number];
export type Overlays = {
  roads: { p: XY[]; c: number | null; r: string | null; h: number[] | null; k: number; n: string }[];
  routes: { p: XY[]; until: number | null; people: number; to: string; eta: number }[];
  shelters: { id: string; name: string; x: number; y: number; people: number; capacity: number }[];
  bridges: { id: string; name: string; x: number; y: number; c: number; r: string | null }[];
};
export type OverlayShow = { roads: boolean; routes: boolean; shelters: boolean; bridges: boolean };
export type OverlayIcons = { shelter: string; bridgeClosed: string; bridgeLater: string };

const C_OPEN = new THREE.Color("#e8eaed"), C_LATER = new THREE.Color("#f29900"), C_CLOSED = new THREE.Color("#d93025");
const ROUTE = 0x00897b, SHELTER = 0x1a73e8;

export class OverlayLayer {
  readonly group = new THREE.Group();
  private mats: LineMaterial[] = [];
  private hot: LineSegments2 | null = null;
  private hotMat: LineMaterial | null = null;
  private hotSegs: { a: number[]; b: number[]; c: number }[] = [];
  private routes: { line: Line2; casing: Line2; until: number | null }[] = [];
  private bridges: { s: THREE.Sprite; c: number }[] = [];
  private roadsG = new THREE.Group();
  private routesG = new THREE.Group();
  private sheltersG = new THREE.Group();
  private bridgesG = new THREE.Group();
  private tex: Record<string, THREE.Texture> = {};
  private hour = -1;

  constructor(private data: Overlays, private dem: Dem, private k: number, private res: THREE.Vector2, private icons: OverlayIcons) {
    this.group.add(this.roadsG, this.routesG, this.sheltersG, this.bridgesG);
    this.buildRoads();
    this.buildRoutes();
    this.buildShelters();
    this.buildBridges();
  }

  /** Ground height (m) at x east, y north, bilinear between cell centres like the terrain mesh. */
  private ground(x: number, y: number): number {
    const d = this.dem;
    const fc = (x + (d.w * d.cell) / 2) / d.cell - 0.5, fr = (-y + (d.h * d.cell) / 2) / d.cell - 0.5;
    const c0 = Math.max(0, Math.min(d.w - 1, Math.floor(fc))), r0 = Math.max(0, Math.min(d.h - 1, Math.floor(fr)));
    const c1 = Math.min(d.w - 1, c0 + 1), r1 = Math.min(d.h - 1, r0 + 1);
    const tx = Math.max(0, Math.min(1, fc - c0)), ty = Math.max(0, Math.min(1, fr - r0));
    const z = (r: number, c: number) => d.z[r * d.w + c];
    return (z(r0, c0) * (1 - tx) + z(r0, c1) * tx) * (1 - ty) + (z(r1, c0) * (1 - tx) + z(r1, c1) * tx) * ty;
  }

  /** Polyline densified to half a cell and lifted `lift` m above the ground; with each vertex's share of the length. */
  private drape(p: XY[], lift: number): { pts: number[][]; f: number[] } {
    const step = this.dem.cell / 2, pts: number[][] = [], dist: number[] = [];
    let L = 0;
    for (let i = 0; i < p.length - 1; i++) {
      const [x0, y0] = p[i], [x1, y1] = p[i + 1], len = Math.hypot(x1 - x0, y1 - y0), n = Math.max(1, Math.ceil(len / step));
      for (let j = i === 0 ? 0 : 1; j <= n; j++) {
        const x = x0 + ((x1 - x0) * j) / n, y = y0 + ((y1 - y0) * j) / n;
        pts.push([x, (this.ground(x, y) + lift) * this.k, -y]);
        dist.push(L + (len * j) / n);
      }
      L += len;
    }
    return { pts, f: dist.map((d) => (L ? d / L : 0)) };
  }

  private mat(width: number, color = 0xffffff, opts: Partial<LineMaterial> = {}): LineMaterial {
    const m = new LineMaterial({ color, linewidth: width, transparent: true, resolution: this.res, ...opts } as any);
    this.mats.push(m);
    return m;
  }

  private buildRoads() {
    const major: number[] = [], minor: number[] = [];
    for (const r of this.data.roads) {
      const { pts, f } = this.drape(r.p, 2.5);
      const out = r.k === 0 ? major : minor;
      for (let i = 0; i < pts.length - 1; i++) {
        out.push(...pts[i], ...pts[i + 1]);
        if (r.c == null) continue;
        const mid = (f[i] + f[i + 1]) / 2;
        // the blocked pieces only (as on the 2D map); a road closed for another reason (bridge, your block) closes whole
        let hot = !r.h;
        if (r.h) for (let j = 0; j + 1 < r.h.length; j += 2) if (mid >= r.h[j] && mid <= r.h[j + 1]) { hot = true; break; }
        if (hot) this.hotSegs.push({ a: pts[i], b: pts[i + 1], c: r.c });
      }
    }
    const add = (pos: number[], width: number, opacity: number) => {
      if (!pos.length) return;
      const g = new LineSegmentsGeometry(); g.setPositions(pos);
      const l = new LineSegments2(g, this.mat(width, 0xe8eaed, { opacity, depthWrite: false } as any));
      l.renderOrder = 3;
      this.roadsG.add(l);
    };
    add(major, 2.2, 0.85);
    add(minor, 1.2, 0.55);
  }

  private buildRoutes() {
    for (const rt of this.data.routes) {
      const { pts } = this.drape(rt.p, 5);
      if (pts.length < 2) continue;
      const pos = pts.flat();
      const w = 4 + Math.min(6, Math.sqrt(rt.people || 1));
      const mk = (width: number, color: number, under = false) => {
        const g = new LineGeometry(); g.setPositions(pos);
        // opaque: a transparent wide line draws twice where its segments meet and looks beaded
        const l = new Line2(g, this.mat(width, color, { transparent: false, dashSize: 40, gapSize: 30, depthWrite: !under } as any));
        l.computeLineDistances();
        l.renderOrder = under ? 4 : 5;  // the casing writes no depth, so the line on top never fights it
        return l;
      };
      const casing = mk(w + 4, 0x0b3d36, true), line = mk(w, ROUTE);
      this.routesG.add(casing, line);
      this.routes.push({ line, casing, until: rt.until });
    }
  }

  private texture(url: string): THREE.Texture {
    if (!this.tex[url]) { const t = new THREE.TextureLoader().load(url); t.colorSpace = THREE.SRGBColorSpace; this.tex[url] = t; }
    return this.tex[url];
  }

  /** A label sprite: the marker icon and a line of text on a white pill, constant size on screen. */
  private label(icon: string, text: string): THREE.Sprite {
    const cv = document.createElement("canvas"), W = 512, H = 96;
    cv.width = W; cv.height = H;
    const g = cv.getContext("2d")!;
    g.font = "500 34px 'Google Sans', Roboto, Arial, sans-serif";
    const tw = Math.min(W - 110, g.measureText(text).width);
    const draw = (img?: HTMLImageElement) => {
      g.clearRect(0, 0, W, H);
      g.fillStyle = "rgba(255,255,255,0.94)"; g.strokeStyle = "rgba(32,33,36,0.25)"; g.lineWidth = 2;
      g.beginPath(); g.roundRect(4, 12, tw + 104, 72, 36); g.fill(); g.stroke();
      if (img) g.drawImage(img, 12, 16, 64, 64);
      g.fillStyle = "#202124"; g.fillText(text, 88, 60, W - 110);
      t.needsUpdate = true;
    };
    const t = new THREE.CanvasTexture(cv);
    t.colorSpace = THREE.SRGBColorSpace;
    draw();
    const img = new Image(); img.onload = () => draw(img); img.src = icon;
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, sizeAttenuation: false, transparent: true }));
    s.scale.set(0.16, 0.03, 1);
    s.center.set(0.02, 0.5);
    s.renderOrder = 7;
    return s;
  }

  private pin(x: number, y: number, h: number, color: number): { top: THREE.Vector3; line: THREE.Line } {
    const z0 = this.ground(x, y);
    const top = new THREE.Vector3(x, (z0 + h) * this.k, -y);
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(x, z0 * this.k, -y), top]);
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.9, depthTest: false }));
    line.renderOrder = 6;
    return { top, line };
  }

  private buildShelters() {
    for (const s of this.data.shelters) {
      // the zone: a blue ring on the ground (80 m), lifted over the highest ground under it so slopes do not hide it
      let zmax = -Infinity;
      for (let a = 0; a < 8; a++) for (const rr of [0, 40, 80]) zmax = Math.max(zmax, this.ground(s.x + rr * Math.cos(a * Math.PI / 4), s.y + rr * Math.sin(a * Math.PI / 4)));
      const disc = new THREE.Mesh(new THREE.CircleGeometry(80, 48), new THREE.MeshBasicMaterial({ color: SHELTER, transparent: true, opacity: 0.18, depthWrite: false }));
      const ring = new THREE.Mesh(new THREE.RingGeometry(68, 80, 48), new THREE.MeshBasicMaterial({ color: SHELTER, transparent: true, opacity: 0.8, depthWrite: false }));
      for (const m of [disc, ring]) { m.rotation.x = -Math.PI / 2; m.position.set(s.x, (zmax + 2) * this.k, -s.y); m.renderOrder = 4; this.sheltersG.add(m); }
      const { top, line } = this.pin(s.x, s.y, 70, SHELTER);
      const lab = this.label(this.icons.shelter, `${s.id} · ${s.people.toLocaleString("en-IN")} people`);
      lab.position.copy(top);
      this.sheltersG.add(line, lab);
    }
  }

  private buildBridges() {
    for (const b of this.data.bridges) {
      const { top, line } = this.pin(b.x, b.y, 45, 0x5f6368);
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.texture(this.icons.bridgeLater), depthTest: false, sizeAttenuation: false, transparent: true }));
      s.scale.set(0.032, 0.032, 1);
      s.position.copy(top);
      s.renderOrder = 7;
      this.bridgesG.add(line, s);
      this.bridges.push({ s, c: b.c });
    }
  }

  /** Road, route and bridge states for model hour `h` (1-based; closed from first_closed_hour on, as in 2D). */
  setHour(h: number) {
    if (h === this.hour) return;
    this.hour = h;
    if (this.hot) { this.roadsG.remove(this.hot); this.hot.geometry.dispose(); }
    this.hot = null;
    const pos: number[] = [], col: number[] = [];
    for (const s of this.hotSegs) {
      const c = s.c <= h ? C_CLOSED : C_LATER;
      pos.push(...s.a, ...s.b);
      col.push(c.r, c.g, c.b, c.r, c.g, c.b);
    }
    if (pos.length) {
      const g = new LineSegmentsGeometry(); g.setPositions(pos); g.setColors(col);
      this.hotMat ??= this.mat(4, 0xffffff, { vertexColors: true, transparent: false } as any);
      this.hot = new LineSegments2(g, this.hotMat);
      this.hot.renderOrder = 6;
      this.roadsG.add(this.hot);
    }
    for (const r of this.routes) {
      const gone = r.until != null && r.until <= h;  // a road on it has closed: faded and dashed, as in 2D
      for (const l of [r.line, r.casing]) {
        const m = l.material as LineMaterial;
        if (m.dashed !== gone) { m.dashed = gone; m.needsUpdate = true; }
      }
      (r.line.material as LineMaterial).color.set(gone ? 0x80cbc4 : ROUTE);
      r.casing.visible = !gone;
    }
    for (const b of this.bridges) b.s.material.map = this.texture(b.c <= h ? this.icons.bridgeClosed : this.icons.bridgeLater);
  }

  setShow(s: OverlayShow) {
    this.roadsG.visible = s.roads; this.routesG.visible = s.routes; this.sheltersG.visible = s.shelters; this.bridgesG.visible = s.bridges;
  }

  setResolution(w: number, h: number) { this.res.set(w, h); for (const m of this.mats) m.resolution.set(w, h); }

  dispose() {
    this.group.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose();
      const mm = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mm)) mm.forEach((x) => x.dispose()); else mm?.dispose();
    });
    Object.values(this.tex).forEach((t) => t.dispose());
  }
}
