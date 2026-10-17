// Water surface shaders. Frames are RGBA8 textures: R depth code (h = 10 m x (R)^2, 0 = dry), G/B east/north velocity
// codes (signed sqrt, 8 m/s range). The vertex shader reads the exact cell value (texelFetch) to place the surface at
// ground + depth (dry cells sink under the terrain so shorelines are cut by the depth test); the fragment shader reads
// the linearly filtered value so depth, colour and shoreline vary smoothly inside a cell. Ripples are gradient noise
// advected along the local velocity (two-phase flow map), so still ponds look calm and fast water streams.

const DECODE = /* glsl */ `
  float decD(float c) { return 10.0 * c * c; }
  float decV(float c) { float s = (c * 255.0 - 128.0) / 127.0; return sign(s) * s * s * 8.0; }
`;

export const waterVertex = /* glsl */ `
  uniform sampler2D tA;
  uniform sampler2D tB;
  uniform sampler2D tZ;
  uniform float uMix;
  uniform float uShow;
  attribute vec2 cell;
  varying vec2 vUv;
  varying vec3 vWorld;
  ${DECODE}
  #include <fog_pars_vertex>
  float hAt(ivec2 q) { return mix(decD(texelFetch(tA, q, 0).r), decD(texelFetch(tB, q, 0).r), uMix); }
  void main() {
    ivec2 ij = ivec2(cell);
    ivec2 mx = textureSize(tZ, 0) - 1;
    float h = hAt(ij);
    vec3 p = position;
    if (h >= uShow) {
      p.y += h;
    } else {
      // dry: carry the neighbours' water level over this vertex so the terrain cuts the surface along a contour
      // (no saw-teeth); with no wet neighbour, sink it out of sight
      float eta = -1e9;
      for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
        ivec2 q = clamp(ij + ivec2(dx, dy), ivec2(0), mx);
        float hn = hAt(q);
        if (hn >= uShow) eta = max(eta, texelFetch(tZ, q, 0).r + hn);
      }
      p.y = eta > -1e8 ? min(eta, p.y + 0.5) : p.y - 1.5;
    }
    vUv = uv;
    vec4 wp = modelMatrix * vec4(p, 1.0);
    vWorld = wp.xyz;
    vec4 mvPosition = viewMatrix * wp;
    gl_Position = projectionMatrix * mvPosition;
    #include <fog_vertex>
  }
`;

export const waterFragment = /* glsl */ `
  uniform sampler2D tA;
  uniform sampler2D tB;
  uniform float uMix;
  uniform float uShow;
  uniform float uTime;
  uniform float uFlow;
  uniform int uMode;
  uniform vec3 uSun;
  uniform vec3 uShallow;
  uniform vec3 uDeep;
  uniform vec3 uSky;
  uniform vec3 uHorizon;
  uniform vec3 uHz1;
  uniform vec3 uHz2;
  uniform vec3 uHz3;
  varying vec2 vUv;
  varying vec3 vWorld;
  ${DECODE}
  #include <fog_pars_fragment>

  vec2 hash2(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
  }
  // gradient noise with analytic derivatives (value, d/dx, d/dy), after Inigo Quilez
  vec3 noised(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
    vec2 du = 30.0 * f * f * (f * (f - 2.0) + 1.0);
    vec2 ga = hash2(i), gb = hash2(i + vec2(1.0, 0.0)), gc = hash2(i + vec2(0.0, 1.0)), gd = hash2(i + vec2(1.0, 1.0));
    float va = dot(ga, f), vb = dot(gb, f - vec2(1.0, 0.0)), vc = dot(gc, f - vec2(0.0, 1.0)), vd = dot(gd, f - vec2(1.0, 1.0));
    return vec3(va + u.x * (vb - va) + u.y * (vc - va) + u.x * u.y * (va - vb - vc + vd),
                ga + u.x * (gb - ga) + u.y * (gc - ga) + u.x * u.y * (ga - gb - gc + gd)
                + du * (u.yx * (va - vb - vc + vd) + vec2(vb, vc) - va));
  }
  // three ripple octaves (16, 5.5 and 2.2 m), each faded out once it is smaller than about two pixels (no speckle)
  vec3 ripples(vec2 p, float px) {
    return noised(p / 16.0) * (1.0 - smoothstep(4.0, 9.0, px))
         + 0.55 * noised(p / 5.5 + 7.31) * (1.0 - smoothstep(1.4, 3.2, px))
         + 0.25 * noised(p / 2.2 + 3.7) * (1.0 - smoothstep(0.55, 1.3, px));
  }

  void main() {
    vec4 a = texture2D(tA, vUv), b = texture2D(tB, vUv);
    float h = mix(decD(a.r), decD(b.r), uMix);
    if (h < uShow) discard;
    vec2 vel = mix(vec2(decV(a.g), decV(a.b)), vec2(decV(b.g), decV(b.b)), uMix);  // east, north (m/s)
    float speed = length(vel);
    vec2 dir = vec2(vel.x, -vel.y);  // world x east, z south

    float ph0 = fract(uTime * 0.45), ph1 = fract(uTime * 0.45 + 0.5);
    float w0 = 1.0 - abs(1.0 - 2.0 * ph0);
    float px = length(fwidth(vWorld.xz));
    vec3 n0 = ripples(vWorld.xz - dir * uFlow * ph0, px);
    vec3 n1 = ripples(vWorld.xz - dir * uFlow * ph1 + vec2(13.7, 4.1), px);
    vec3 n = n0 * w0 + n1 * (1.0 - w0);
    float amp = 0.18 + 0.75 * clamp(speed / 2.5, 0.0, 1.0);
    vec3 N = normalize(vec3(-n.y * amp, 1.0, -n.z * amp));

    vec3 V = normalize(cameraPosition - vWorld);
    vec3 L = normalize(uSun);
    float diff = max(dot(N, L), 0.0);
    float spec = pow(max(dot(N, normalize(L + V)), 0.0), 140.0);
    float fres = 0.04 + 0.96 * pow(1.0 - max(dot(N, V), 0.0), 5.0);
    vec3 R = reflect(-V, N);
    vec3 sky = mix(uHorizon, uSky, clamp(R.y * 1.6, 0.0, 1.0));

    vec3 body = mix(uShallow, uDeep, 1.0 - exp(-h / 1.1));
    if (uMode == 1) {  // danger to people, flood hazard rating HR = d (v + 0.5) + DF (DEFRA/EA FD2321)
      float hr = h * (speed + 0.5) + (h > 0.25 ? 0.5 : 0.0);
      body = hr < 0.75 ? body : hr < 1.25 ? uHz1 : hr < 2.0 ? uHz2 : uHz3;
    }
    vec3 col = body * (0.6 + 0.4 * diff);
    col = mix(col, sky, fres * 0.5) + spec * vec3(1.0, 0.98, 0.92);
    float foam = smoothstep(1.4, 3.6, speed) * smoothstep(0.25, 0.8, n.x * 0.5 + 0.5);
    col = mix(col, vec3(0.93, 0.95, 0.97), foam * 0.65);
    float alpha = mix(0.62, 0.94, smoothstep(0.03, 1.2, h));
    alpha = max(alpha, fres) * smoothstep(uShow, uShow + 0.05, h);
    gl_FragColor = vec4(col, alpha);
    #include <fog_fragment>
  }
`;
