// 3D scene for the water-flow view (three.js). World units are metres from the grid centre: x east, z south, y up;
// meshes are scaled in y by the display exaggeration k. Terrain, water and model cells share the 30 m grid of the flow
// model's ground, so water sits exactly on the terrain it was computed on.
import * as THREE from "three";
import { MapControls } from "three/addons/controls/MapControls.js";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import { OverlayLayer, type OverlayIcons, type OverlayShow, type Overlays } from "./overlays";
import { waterFragment, waterVertex } from "./shaders";

export type Dem = { w: number; h: number; cell: number; z: Float32Array };
export type Bld = { i: number; p: [number, number][]; z: number; h: number };
/** Planar uint8 frames [n, 3, h, w]: depth code, east velocity code, north velocity code (see backend engines/swe.py). */
export type Frames = { n: number; w: number; h: number; frameS: number; data: Uint8Array; velocity: boolean };
export type ColorMode = "depth" | "hazard";
export type WaterStyle = "real" | "cells";
export type Probe = { r: number; c: number; ground: number; building: Bld | null };

export const decDepth = (c: number) => (c ? 10 * (c / 255) ** 2 : 0);
export const decVel = (c: number) => { const s = (c - 128) / 127; return Math.sign(s) * s * s * 8; };
/** FD2321 flood hazard rating, as in the water shader. */
export const hazard = (h: number, v: number) => h * (v + 0.5) + (h > 0.25 ? 0.5 : 0);

export const RISK: [number, number, number][] = [[217, 48, 37], [242, 153, 0], [251, 188, 4], [232, 234, 237]];
export const DRY: [number, number, number] = [196, 199, 204];  // dry building (water colouring): grey, not glare-white
export const SHALLOW = "#9ecae1", DEEP = "#08519c";
export const HAZARD = ["#d7aefb", "#a142f4", "#681da8"];  // danger for some / most / all (purples: no clash with risk)
const SKY = "#bcd4f0", HORIZON = "#e4ecf5";
const SUN = new THREE.Vector3(-0.55, 0.8, -0.45).normalize();  // from the north-west, as the hillshade
const MAX_CELLS = 60000, N_LINES = 4500;

const col3 = (hex: string) => new THREE.Color(hex);

export class Scene3D {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(42, 1, 5, 200000);
  readonly controls: MapControls;
  private host: HTMLElement;
  private raf = 0;
  private last = performance.now();
  private ro: ResizeObserver;
  private dem: Dem | null = null;
  private k = 1.5;
  private terrain: THREE.Mesh | null = null;
  private terrainMat = new THREE.MeshStandardMaterial({ color: 0xb8c4a8, roughness: 1, metalness: 0 });
  private water: THREE.Mesh | null = null;
  private waterMat: THREE.ShaderMaterial;
  private tA: THREE.DataTexture;
  private tB: THREE.DataTexture;
  private tZ: THREE.DataTexture | null = null;
  private buf: Uint8Array = new Uint8Array(4);
  private frames: Frames | null = null;
  private fA = -1;
  private fB = -1;
  private bld: THREE.Mesh | null = null;
  private blds: Bld[] = [];
  private bIndex = new Map<string, number[]>();
  /** Per building: first vertex, grid cells under it (cells[off[i]..off[i+1]]), per-vertex wall/roof shade, last colour class. */
  private bv: { start: Int32Array; cells: Int32Array; off: Int32Array; shade: Float32Array; cls: Int8Array } | null = null;
  private bWaterK = -1;
  private aoiRing: [number, number][] | null = null;
  private ovl: OverlayLayer | null = null;
  private inside: Uint8Array | null = null;  // 1 for grid cells inside the simulated area

  /** Cells whose centre lies inside the simulated area (x east, y north, as aoi_m). */
  private insideMask(): Uint8Array | null {
    const d = this.dem, ring = this.aoiRing;
    if (!d || !ring || ring.length < 4) return null;
    if (this.inside) return this.inside;
    const m = new Uint8Array(d.w * d.h);
    for (let r = 0; r < d.h; r++) {
      const y = -((r + 0.5) * d.cell - (d.h * d.cell) / 2);
      for (let c = 0; c < d.w; c++) {
        const x = (c + 0.5) * d.cell - (d.w * d.cell) / 2;
        let inn = false;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
          const [xi, yi] = ring[i], [xj, yj] = ring[j];
          if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inn = !inn;
        }
        m[r * d.w + c] = inn ? 1 : 0;
      }
    }
    return (this.inside = m);
  }
  /** Colour buildings by the water against them at the current time (true) or by the brief's risk (false). */
  bldByWater = true;
  private cells: THREE.InstancedMesh | null = null;
  private lines: THREE.LineSegments | null = null;
  private lp = { x: new Float32Array(N_LINES), z: new Float32Array(N_LINES), age: new Float32Array(N_LINES), life: new Float32Array(N_LINES) };
  private wetList: Int32Array = new Int32Array(0);
  private outline: THREE.Group | null = null;
  private fly: { p0: THREE.Vector3; p1: THREE.Vector3; t0: THREE.Vector3; t1: THREE.Vector3; s: number; d: number } | null = null;
  private cellsDirty = true;
  private lastCellT = -1;
  private lastEmit = 0;
  /** Model time in seconds. */
  time = 0;
  playing = false;
  /** Model seconds per real second. */
  rate = 720;
  duration = 3600;
  style: WaterStyle = "real";
  colorMode: ColorMode = "depth";
  showLines = true;
  onTime: ((t: number) => void) | null = null;
  isDisposed = false;

  constructor(host: HTMLElement) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = "block";
    this.scene.fog = new THREE.Fog(HORIZON, 8000, 60000);
    this.scene.add(new THREE.HemisphereLight(0xe8f0ff, 0x5a5a48, 1.25));
    const sun = new THREE.DirectionalLight(0xfff6e8, 1.9);
    sun.position.copy(SUN).multiplyScalar(10000);
    this.scene.add(sun);

    this.controls = new MapControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.maxPolarAngle = Math.PI * 0.46;
    this.controls.minDistance = 120;
    this.controls.maxDistance = 45000;
    this.controls.zoomToCursor = true;
    this.controls.addEventListener("start", () => { this.fly = null; });

    const mk = () => {
      const t = new THREE.DataTexture(new Uint8Array(4), 1, 1, THREE.RGBAFormat, THREE.UnsignedByteType);
      t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearFilter; t.generateMipmaps = false;
      t.needsUpdate = true;
      return t;
    };
    this.tA = mk();
    this.tB = mk();
    this.waterMat = new THREE.ShaderMaterial({
      uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, {
        tA: { value: null }, tB: { value: null }, tZ: { value: null }, uMix: { value: 0 }, uShow: { value: 0.03 }, uTime: { value: 0 }, uFlow: { value: 5 },
        uMode: { value: 0 }, uSun: { value: SUN.clone() }, uShallow: { value: col3(SHALLOW) }, uDeep: { value: col3(DEEP) },
        uSky: { value: col3(SKY) }, uHorizon: { value: col3(HORIZON) },
        uHz1: { value: col3(HAZARD[0]) }, uHz2: { value: col3(HAZARD[1]) }, uHz3: { value: col3(HAZARD[2]) },
      }]),
      vertexShader: waterVertex, fragmentShader: waterFragment, transparent: true, fog: true,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4,
    });
    this.waterMat.uniforms.tA.value = this.tA;
    this.waterMat.uniforms.tB.value = this.tB;

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.loop();
  }

  private resize() {
    const w = this.host.clientWidth || 1, h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.outline?.children.forEach((l) => ((l as Line2).material as LineMaterial).resolution.set(w, h));
    this.ovl?.setResolution(w, h);
  }

  /** Terrain mesh from the ground grid; the water mesh shares its vertices. */
  setTerrain(dem: Dem, k: number) {
    this.dem = dem;
    this.k = k;
    const { w, h, cell, z } = dem;
    const W = w * cell, H = h * cell;
    const pos = new Float32Array(w * h * 3), uv = new Float32Array(w * h * 2), cl = new Float32Array(w * h * 2);
    for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
      const i = r * w + c;
      pos[3 * i] = -W / 2 + (c + 0.5) * cell; pos[3 * i + 1] = z[i]; pos[3 * i + 2] = -H / 2 + (r + 0.5) * cell;
      uv[2 * i] = (c + 0.5) / w; uv[2 * i + 1] = (r + 0.5) / h;
      cl[2 * i] = c; cl[2 * i + 1] = r;
    }
    const idx = new Uint32Array((w - 1) * (h - 1) * 6);
    let j = 0;
    for (let r = 0; r < h - 1; r++) for (let c = 0; c < w - 1; c++) {
      const a = r * w + c, b = a + 1, e = a + w, f = e + 1;
      idx[j++] = a; idx[j++] = e; idx[j++] = b; idx[j++] = b; idx[j++] = e; idx[j++] = f;
    }
    const P = new THREE.BufferAttribute(pos, 3), U = new THREE.BufferAttribute(uv, 2), I = new THREE.BufferAttribute(idx, 1);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", P); g.setAttribute("uv", U); g.setIndex(I);
    g.computeVertexNormals();
    g.computeBoundingSphere();
    this.terrain && (this.scene.remove(this.terrain), this.terrain.geometry.dispose());
    this.terrain = new THREE.Mesh(g, this.terrainMat);
    this.terrain.scale.y = k;
    this.scene.add(this.terrain);

    const wg = new THREE.BufferGeometry();
    wg.setAttribute("position", P); wg.setAttribute("uv", U); wg.setAttribute("cell", new THREE.BufferAttribute(cl, 2)); wg.setIndex(I);
    wg.boundingSphere = g.boundingSphere!.clone();
    wg.boundingSphere.radius += 50;
    this.water && (this.scene.remove(this.water), this.water.geometry.dispose());
    this.tZ?.dispose();
    this.tZ = new THREE.DataTexture(z, w, h, THREE.RedFormat, THREE.FloatType);
    this.tZ.magFilter = THREE.NearestFilter; this.tZ.minFilter = THREE.NearestFilter; this.tZ.generateMipmaps = false;
    this.tZ.needsUpdate = true;
    this.waterMat.uniforms.tZ.value = this.tZ;
    this.water = new THREE.Mesh(wg, this.waterMat);
    this.water.scale.y = k;
    this.water.renderOrder = 2;
    this.water.visible = !!this.frames && this.style === "real";
    this.scene.add(this.water);
    this.buf = new Uint8Array(w * h * 4);
  }

  setTexture(img: HTMLImageElement | null) {
    const old = this.terrainMat.map;
    if (img) {
      const t = new THREE.Texture(img);
      t.flipY = false;  // image row 0 is the grid's north row, at v = 0 like the terrain's uv and the water's data textures
      t.colorSpace = THREE.SRGBColorSpace;
      t.anisotropy = Math.min(8, this.renderer.capabilities.getMaxAnisotropy());
      t.needsUpdate = true;
      this.terrainMat.map = t;
      this.terrainMat.color.set(0xffffff);
    } else {
      this.terrainMat.map = null;
    }
    this.terrainMat.needsUpdate = true;
    old?.dispose();
  }

  /** The simulated area outline draped on the ground: white dashes on a dark halo (as on the 2D map). */
  setOutline(ring: [number, number][] | null) {
    this.aoiRing = ring; this.inside = null;
    if (this.outline) { this.scene.remove(this.outline); this.outline.children.forEach((l) => { (l as Line2).geometry.dispose(); ((l as Line2).material as LineMaterial).dispose(); }); }
    this.outline = null;
    if (!ring || !this.dem) return;
    const pts: number[] = [];
    for (let i = 0; i < ring.length - 1; i++) {
      const [x0, y0] = ring[i], [x1, y1] = ring[i + 1];
      const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / this.dem.cell));
      for (let j = 0; j <= n; j++) {
        const x = x0 + ((x1 - x0) * j) / n, y = y0 + ((y1 - y0) * j) / n;
        pts.push(x, (this.groundAt(x, -y) + 6) * this.k, -y);
      }
    }
    const res = new THREE.Vector2(this.host.clientWidth, this.host.clientHeight);
    const mk = (color: number, width: number, dashed: boolean, opacity: number) => {
      const g = new LineGeometry(); g.setPositions(pts);
      const m = new LineMaterial({ color, linewidth: width, dashed, dashSize: 90, gapSize: 60, transparent: true, opacity, depthTest: false, resolution: res });
      const l = new Line2(g, m); l.computeLineDistances(); l.renderOrder = 5;
      return l;
    };
    this.outline = new THREE.Group();
    this.outline.add(mk(0x202124, 5, false, 0.55), mk(0xffffff, 2.5, true, 1));
    this.scene.add(this.outline);
  }

  /** Extruded buildings coloured by estimated risk (0 critical .. 3 low), merged into one mesh. */
  setBuildings(blds: Bld[], risk: Uint8Array | null) {
    this.blds = blds;
    this.bIndex.clear();
    if (this.bld) { this.scene.remove(this.bld); this.bld.geometry.dispose(); }
    this.bld = null;
    if (!blds.length) return;
    const P: number[] = [], N: number[] = [], C: number[] = [], S: number[] = [];
    const vStart: number[] = [], cellIdx: number[] = [], cellOff: number[] = [0];
    const d = this.dem;
    blds.forEach((b, bi) => {
      let ring = b.p;
      if (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring = ring.slice(0, -1);
      if (ring.length < 3) { vStart.push(P.length / 3); cellOff.push(cellIdx.length); return; }
      vStart.push(P.length / 3);
      if (d) {  // grid cells under the footprint, half a cell wider: water pools against walls, not under roofs
        let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
        for (const q of ring) { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); }
        const pad = d.cell / 2;
        const a = this.cellOf(x0 - pad, -(y1 + pad)), z = this.cellOf(x1 + pad, -(y0 - pad));
        if (a && z) for (let r = a[0]; r <= Math.min(z[0], a[0] + 3); r++) for (let c = a[1]; c <= Math.min(z[1], a[1] + 3); c++) cellIdx.push(r * d.w + c);
      }
      cellOff.push(cellIdx.length);
      const cx = ring.reduce((s, q) => s + q[0], 0) / ring.length, cy = ring.reduce((s, q) => s + q[1], 0) / ring.length;
      const key = `${Math.floor(cx / 100)},${Math.floor(cy / 100)}`;
      (this.bIndex.get(key) ?? this.bIndex.set(key, []).get(key)!).push(bi);
      const rk = risk && b.i < risk.length ? risk[b.i] : 3;
      const [r, g, bl] = RISK[Math.min(3, rk)].map((v) => v / 255);
      let area = 0;
      for (let i = 0; i < ring.length; i++) { const a = ring[i], c = ring[(i + 1) % ring.length]; area += a[0] * c[1] - c[0] * a[1]; }
      const ccw = area > 0;
      const y0 = b.z - 3, y1 = b.z + b.h;
      for (let i = 0; i < ring.length; i++) {
        const a = ring[i], c = ring[(i + 1) % ring.length];
        const dx = c[0] - a[0], dy = c[1] - a[1], L = Math.hypot(dx, dy) || 1;
        const nx = (ccw ? dy : -dy) / L, nz = (ccw ? dx : -dx) / L;
        const quad = [[a, y0], [c, y0], [c, y1], [a, y0], [c, y1], [a, y1]] as const;
        for (const [q, y] of quad) { P.push(q[0], y, -q[1]); N.push(nx, 0, nz); C.push(r * 0.82, g * 0.82, bl * 0.82); S.push(0.82); }
      }
      const tri = THREE.ShapeUtils.triangulateShape(ring.map((q) => new THREE.Vector2(q[0], q[1])), []);
      for (const t of tri) for (const vi of t) { const q = ring[vi]; P.push(q[0], y1, -q[1]); N.push(0, 1, 0); C.push(r, g, bl); S.push(1); }
    });
    vStart.push(P.length / 3);
    this.bv = { start: Int32Array.from(vStart), cells: Int32Array.from(cellIdx), off: Int32Array.from(cellOff), shade: Float32Array.from(S), cls: new Int8Array(blds.length).fill(-1) };
    this.bWaterK = -1;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(P, 3));
    geo.setAttribute("normal", new THREE.Float32BufferAttribute(N, 3));
    geo.setAttribute("color", new THREE.Float32BufferAttribute(C, 3));
    geo.computeBoundingSphere();
    this.bld = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide }));
    this.bld.scale.y = this.k;
    this.bld.renderOrder = 1;
    this.scene.add(this.bld);
    this.update();  // water colours for the current time, if frames are loaded
  }

  /** The run's roads, exit routes, shelters and bridges draped on the ground (null removes them). */
  setOverlays(data: Overlays | null, icons: OverlayIcons, show: OverlayShow, hour: number) {
    if (this.ovl) { this.scene.remove(this.ovl.group); this.ovl.dispose(); this.ovl = null; }
    if (!data || !this.dem) return;
    this.ovl = new OverlayLayer(data, this.dem, this.k, new THREE.Vector2(this.host.clientWidth, this.host.clientHeight), icons);
    this.ovl.setShow(show);
    this.ovl.setHour(hour);
    this.scene.add(this.ovl.group);
  }
  setOverlayHour(h: number) { this.ovl?.setHour(h); }
  setOverlayShow(s: OverlayShow) { this.ovl?.setShow(s); }

  setBuildingsVisible(v: boolean) { if (this.bld) this.bld.visible = v; }

  setFrames(f: Frames | null) {
    // water only inside the simulated area, as on the 2D map: outside it the ground is padding for the models, and the
    // hourly map there has no rivers traced to its edge (it drew false lakes across the Brahmaputra)
    const inside = f && this.dem && f.w === this.dem.w && f.h === this.dem.h ? this.insideMask() : null;
    if (f && inside) {
      const n = f.w * f.h, data = f.data.slice();
      for (let k = 0; k < f.n; k++) {
        const b = k * 3 * n;
        for (let i = 0; i < n; i++) if (!inside[i]) { data[b + i] = 0; data[b + n + i] = 128; data[b + 2 * n + i] = 128; }
      }
      f = { ...f, data };
    }
    this.frames = f;
    this.fA = this.fB = -1;
    this.cellsDirty = true;
    if (f && this.dem && (f.w !== this.dem.w || f.h !== this.dem.h)) { console.warn("frames do not match the ground grid"); this.frames = null; }
    this.applyStyle();
    this.update(true);
  }

  setStyle(style: WaterStyle, color: ColorMode, lines: boolean) {
    this.style = style; this.colorMode = color; this.showLines = lines;
    this.waterMat.uniforms.uMode.value = color === "hazard" ? 1 : 0;
    this.cellsDirty = true;
    this.applyStyle();
  }

  private applyStyle() {
    const on = !!this.frames;
    if (this.water) this.water.visible = on && this.style === "real";
    if (on && this.style === "cells" && !this.cells && this.dem) {
      const g = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0);
      this.cells = new THREE.InstancedMesh(g, new THREE.MeshLambertMaterial({ transparent: true, opacity: 0.92 }), MAX_CELLS);
      this.cells.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      this.cells.setColorAt(0, new THREE.Color());
      this.cells.count = 0;
      this.cells.scale.y = this.k;
      this.cells.frustumCulled = false;
      this.cells.renderOrder = 2;
      this.scene.add(this.cells);
    }
    if (this.cells) this.cells.visible = on && this.style === "cells";
    if (on && this.frames!.velocity && !this.lines) {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(N_LINES * 6), 3).setUsage(THREE.DynamicDrawUsage));
      g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(N_LINES * 8), 4).setUsage(THREE.DynamicDrawUsage));
      this.lines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false }));
      this.lines.frustumCulled = false;
      this.lines.renderOrder = 4;
      this.lines.scale.y = this.k;
      this.scene.add(this.lines);
      this.lp.age.fill(1e9);
    }
    if (this.lines) this.lines.visible = on && this.showLines && !!this.frames?.velocity;
  }

  /** Frame indices and blend for the current time; uploads frame textures when they change. */
  private update(force = false) {
    const f = this.frames;
    if (!f || !this.dem) return;
    const x = Math.max(0, Math.min(this.time / f.frameS, f.n - 1));
    const a = Math.floor(x), b = Math.min(a + 1, f.n - 1);
    if (a !== this.fA || force) { this.upload(this.tA, a); this.fA = a; this.rebuildWetList(a); }
    if (b !== this.fB || force) { this.upload(this.tB, b); this.fB = b; }
    this.waterMat.uniforms.uMix.value = x - a;
    const k = Math.round(x);
    if (k !== this.bWaterK || force) { this.bWaterK = k; this.colourBuildings(k); }
  }

  /** Buildings turn yellow, orange, red as water against them passes 15 cm, 50 cm, 1 m in frame k (grey when dry). */
  private colourBuildings(k: number) {
    const f = this.frames, bv = this.bv, m = this.bld;
    if (!f || !bv || !m || !this.bldByWater) return;
    const n = f.w * f.h, base = k * 3 * n, d = f.data;
    const col = m.geometry.getAttribute("color") as THREE.BufferAttribute, arr = col.array as Float32Array;
    let dirty = false;
    for (let i = 0; i < this.blds.length; i++) {
      let h = 0;
      for (let j = bv.off[i]; j < bv.off[i + 1]; j++) { const c = d[base + bv.cells[j]]; if (c > h) h = c; }
      const dm = decDepth(h), cls = dm >= 1 ? 0 : dm >= 0.5 ? 1 : dm >= 0.15 ? 2 : 3;
      if (cls === bv.cls[i]) continue;
      bv.cls[i] = cls; dirty = true;
      const [r, g, b] = cls === 3 ? DRY : RISK[cls];
      for (let v = bv.start[i]; v < bv.start[i + 1]; v++) { const s = bv.shade[v] / 255; arr[3 * v] = r * s; arr[3 * v + 1] = g * s; arr[3 * v + 2] = b * s; }
    }
    if (dirty) col.needsUpdate = true;
  }

  private upload(t: THREE.DataTexture, k: number) {
    const f = this.frames!, n = f.w * f.h, base = k * 3 * n, d = f.data;
    const out = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) { out[4 * i] = d[base + i]; out[4 * i + 1] = d[base + n + i]; out[4 * i + 2] = d[base + 2 * n + i]; out[4 * i + 3] = 255; }
    t.image = { data: out, width: f.w, height: f.h } as any;
    t.needsUpdate = true;
  }

  private rebuildWetList(k: number) {
    const f = this.frames!;
    if (!f.velocity) { this.wetList = new Int32Array(0); return; }
    const n = f.w * f.h, base = k * 3 * n, d = f.data, out: number[] = [];
    for (let i = 0; i < n; i++) {
      const c = d[base + i];
      if (c >= 26 && Math.abs(d[base + n + i] - 128) + Math.abs(d[base + 2 * n + i] - 128) > 10) out.push(i);  // >= ~10 cm, moving
    }
    this.wetList = Int32Array.from(out);
  }

  /** Depth (m) and velocity (m/s east, north) at a cell for the current time. */
  sample(i: number): [number, number, number] {
    const f = this.frames;
    if (!f) return [0, 0, 0];
    const n = f.w * f.h, d = f.data, m = this.waterMat.uniforms.uMix.value as number;
    const A = Math.max(0, this.fA) * 3 * n, B = Math.max(0, this.fB) * 3 * n;
    const mix = (o: number, dec: (c: number) => number) => dec(d[A + o + i]) * (1 - m) + dec(d[B + o + i]) * m;
    return [mix(0, decDepth), f.velocity ? mix(n, decVel) : 0, f.velocity ? mix(2 * n, decVel) : 0];
  }

  /** Depth series (m) of a cell over all frames. */
  series(i: number): number[] {
    const f = this.frames;
    if (!f) return [];
    const n = f.w * f.h;
    return Array.from({ length: f.n }, (_, k) => decDepth(f.data[k * 3 * n + i]));
  }

  groundAt(x: number, z: number): number {
    const d = this.dem;
    if (!d) return 0;
    const c = Math.min(d.w - 1, Math.max(0, Math.floor((x + (d.w * d.cell) / 2) / d.cell)));
    const r = Math.min(d.h - 1, Math.max(0, Math.floor((z + (d.h * d.cell) / 2) / d.cell)));
    return d.z[r * d.w + c];
  }

  cellOf(x: number, z: number): [number, number] | null {
    const d = this.dem;
    if (!d) return null;
    const c = Math.floor((x + (d.w * d.cell) / 2) / d.cell), r = Math.floor((z + (d.h * d.cell) / 2) / d.cell);
    return r >= 0 && c >= 0 && r < d.h && c < d.w ? [r, c] : null;
  }

  private updateCells() {
    const f = this.frames, d = this.dem, m = this.cells;
    if (!f || !d || !m) return;
    const n = f.w * f.h, W = d.w * d.cell, H = d.h * d.cell, s = d.cell * 0.9;
    const M = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), sc = new THREE.Vector3(), col = new THREE.Color();
    const sh = col3(SHALLOW), dp = col3(DEEP), hz = HAZARD.map(col3);
    const A = Math.max(0, this.fA) * 3 * n, B = Math.max(0, this.fB) * 3 * n, t = this.waterMat.uniforms.uMix.value as number;
    let cnt = 0;
    const minC = 18;  // code for ~5 cm
    for (let i = 0; i < n && cnt < MAX_CELLS; i++) {
      const ca = f.data[A + i], cb = f.data[B + i];
      if (ca < minC && cb < minC) continue;
      const h = decDepth(ca) * (1 - t) + decDepth(cb) * t;
      if (h < 0.05) continue;
      const r = (i / d.w) | 0, c = i - r * d.w;
      const g = d.z[i];
      p.set(-W / 2 + (c + 0.5) * d.cell, g - 0.5, -H / 2 + (r + 0.5) * d.cell);
      sc.set(s, h + 0.5, s);
      M.compose(p, q, sc);
      m.setMatrixAt(cnt, M);
      if (this.colorMode === "hazard" && f.velocity) {
        const u = decVel(f.data[A + n + i]) * (1 - t) + decVel(f.data[B + n + i]) * t;
        const v = decVel(f.data[A + 2 * n + i]) * (1 - t) + decVel(f.data[B + 2 * n + i]) * t;
        const hr = hazard(h, Math.hypot(u, v));
        col.copy(hr < 0.75 ? sh.clone().lerp(dp, 1 - Math.exp(-h / 1.1)) : hr < 1.25 ? hz[0] : hr < 2 ? hz[1] : hz[2]);
      } else col.copy(sh).lerp(dp, 1 - Math.exp(-h / 1.1));
      m.setColorAt(cnt, col);
      cnt++;
    }
    m.count = cnt;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
  }

  private updateLines(dt: number) {
    const f = this.frames, d = this.dem, L = this.lines;
    if (!f || !d || !L || !L.visible) return;
    const pos = L.geometry.getAttribute("position") as THREE.BufferAttribute, colA = L.geometry.getAttribute("color") as THREE.BufferAttribute;
    const P = pos.array as Float32Array, C = colA.array as Float32Array;
    const W = d.w * d.cell, H = d.h * d.cell;
    const dist = this.camera.position.distanceTo(this.controls.target);
    const S = Math.min(140, Math.max(6, dist / 55));  // on-screen metres per second per m/s of flow
    const wl = this.wetList, lp = this.lp;
    for (let k = 0; k < N_LINES; k++) {
      let x = lp.x[k], z = lp.z[k];
      let cell = this.cellOf(x, z);
      let s = cell ? this.sample(cell[0] * d.w + cell[1]) : [0, 0, 0];
      lp.age[k] += dt;
      if (!cell || s[0] < 0.05 || lp.age[k] > lp.life[k]) {
        if (!wl.length) { P.fill(0, 6 * k, 6 * k + 6); C.fill(0, 8 * k, 8 * k + 8); continue; }
        const i = wl[(Math.random() * wl.length) | 0];
        const r = (i / d.w) | 0, c = i - r * d.w;
        x = -W / 2 + (c + Math.random()) * d.cell; z = -H / 2 + (r + Math.random()) * d.cell;
        lp.age[k] = 0; lp.life[k] = 1.5 + Math.random() * 2.5;
        cell = [r, c]; s = this.sample(i);
      }
      const [h, u, v] = s;
      x += u * S * dt; z -= v * S * dt;
      lp.x[k] = x; lp.z[k] = z;
      const y = this.groundAt(x, z) + h + 0.4;
      const sp = Math.hypot(u, v);
      const tail = Math.min(0.45, 25 / (sp * S + 1e-6));
      P[6 * k] = x; P[6 * k + 1] = y; P[6 * k + 2] = z;
      P[6 * k + 3] = x - u * S * tail; P[6 * k + 4] = y; P[6 * k + 5] = z + v * S * tail;
      const fade = Math.min(1, lp.age[k] / 0.3, (lp.life[k] - lp.age[k]) / 0.5);
      const a = Math.max(0, fade) * Math.min(1, sp / 1.2) * 0.95;
      C.set([1, 1, 1, a, 1, 1, 1, 0], 8 * k);
    }
    pos.needsUpdate = true; colA.needsUpdate = true;
  }

  /** Ground or water point under a screen position (march along the ray over the height grid). */
  pick(clientX: number, clientY: number): Probe | null {
    const d = this.dem;
    if (!d) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, this.camera);
    const o = ray.ray.origin, dir = ray.ray.direction;
    const step = d.cell / 3, maxT = this.camera.far;
    let prevAbove = true;
    for (let t = 0; t < maxT; t += step * (1 + t / 4000)) {
      const x = o.x + dir.x * t, y = o.y + dir.y * t, z = o.z + dir.z * t;
      const cell = this.cellOf(x, z);
      if (!cell) { if (t > 1000 && y < this.k * -1000) break; continue; }
      const i = cell[0] * d.w + cell[1];
      const top = (d.z[i] + this.sample(i)[0]) * this.k;
      const above = y > top;
      if (!above && prevAbove) {
        const key = `${Math.floor(x / 100)},${Math.floor(-z / 100)}`;
        let building: Bld | null = null;
        for (const bi of this.bIndex.get(key) ?? []) if (inside(this.blds[bi].p, x, -z)) { building = this.blds[bi]; break; }
        return { r: cell[0], c: cell[1], ground: d.z[i], building };
      }
      prevAbove = above;
    }
    return null;
  }

  /** Camera to look at (x, z) from `dist` metres, `pitch` degrees above the horizon, `bearing` degrees from north. */
  flyTo(x: number, z: number, dist: number, pitch = 50, bearing = -20, instant = false) {
    const y = this.groundAt(x, z) * this.k;
    const t1 = new THREE.Vector3(x, y, z);
    const el = (pitch * Math.PI) / 180, az = (bearing * Math.PI) / 180;
    const p1 = new THREE.Vector3(x - Math.sin(az) * Math.cos(el) * dist, y + Math.sin(el) * dist, z + Math.cos(az) * Math.cos(el) * dist);
    p1.y = Math.max(p1.y, (this.groundAt(p1.x, p1.z) + 60) * this.k);
    if (instant) { this.camera.position.copy(p1); this.controls.target.copy(t1); this.controls.update(); return; }
    this.fly = { p0: this.camera.position.clone(), p1, t0: this.controls.target.clone(), t1, s: performance.now(), d: 1100 };
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const now = performance.now(), dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    if (this.fly) {
      const u = Math.min(1, (now - this.fly.s) / this.fly.d), e = u < 0.5 ? 4 * u * u * u : 1 - (-2 * u + 2) ** 3 / 2;
      this.camera.position.lerpVectors(this.fly.p0, this.fly.p1, e);
      this.controls.target.lerpVectors(this.fly.t0, this.fly.t1, e);
      if (u >= 1) this.fly = null;
    }
    this.controls.update();
    if (this.dem) {  // never inside a hillside: keep the camera 40 m above the ground under it
      const floor = (this.groundAt(this.camera.position.x, this.camera.position.z) + 40) * this.k;
      if (this.camera.position.y < floor) this.camera.position.y = floor;
    }
    const dist = this.camera.position.distanceTo(this.controls.target);
    const near = Math.max(2, dist * 0.015), far = dist * 12 + 40000;
    if (Math.abs(this.camera.near - near) / near > 0.2 || this.camera.far !== far) { this.camera.near = near; this.camera.far = far; this.camera.updateProjectionMatrix(); }
    const fog = this.scene.fog as THREE.Fog;
    fog.near = dist * 1.6 + 2000; fog.far = dist * 7 + 25000;
    if (this.playing && this.frames) {
      this.time += dt * this.rate;
      const end = this.time >= this.duration;
      if (end) { this.time = this.duration; this.playing = false; }
      if (end || now - this.lastEmit > 120) { this.lastEmit = now; this.onTime?.(this.time); }  // UI at ~8 Hz
    }
    this.update();
    if (this.cells?.visible && (this.cellsDirty || Math.abs(this.time - this.lastCellT) > 20)) { this.updateCells(); this.cellsDirty = false; this.lastCellT = this.time; }
    this.waterMat.uniforms.uTime.value = now / 1000;
    this.updateLines(dt);
    this.renderer.render(this.scene, this.camera);
  };

  setTime(t: number) { this.time = Math.max(0, Math.min(this.duration, t)); this.cellsDirty = true; this.update(); }

  dispose() {
    this.isDisposed = true;
    this.ovl?.dispose();
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.controls.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      m.geometry?.dispose?.();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((x) => x.dispose());
    });
    this.terrainMat.map?.dispose();
    this.tA.dispose(); this.tB.dispose(); this.tZ?.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

function inside(ring: [number, number][], x: number, y: number) {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
