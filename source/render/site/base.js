/* মোশন গ্রাফিক্স স্টেজ (ভাগ ১): সহায়ক ফাংশন, থিম, লেআউট, হিরো ইমেজ।
   সবকিছু শুধু সময় t থেকে হিসাব হয় (window.renderFrame(t)), তাই প্রতিটি ফ্রেম ঠিকঠাক একই রকম আসে।
   ক্যানভাসের মাপ (D.W x D.H) রেশিও অনুযায়ী বদলায়; রেজোলিউশন শুধু device scale factor দিয়ে আসে। */
window.RT = {};
(function (RT) {
  const D = window.DATA;
  const CFG = D.config || {};
  const TH = D.theme;
  const C = TH.c;
  const S = TH.style;
  const FN = TH.font;
  const W = D.W, H = D.H;
  const NS = "http://www.w3.org/2000/svg";

  // ---------- ছোট সহায়ক ----------
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const E = {
    lin: (x) => x,
    outCubic: (x) => 1 - Math.pow(1 - x, 3),
    outQuart: (x) => 1 - Math.pow(1 - x, 4),
    inCubic: (x) => x * x * x,
    inOutCubic: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    inOutSine: (x) => -(Math.cos(Math.PI * x) - 1) / 2,
    outBack: (x) => { const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
    outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  };
  const prog = (t, s, d, e = E.outCubic) => e(clamp((t - s) / d));
  function el(tag, cls, parent, css) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (css) Object.assign(e.style, css);
    if (parent) parent.appendChild(e);
    return e;
  }
  function sv(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function svgRoot(parent, w = W, h = H, css) {
    const s = sv("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}` }, parent);
    s.style.position = "absolute"; s.style.left = "0"; s.style.top = "0"; s.style.overflow = "visible";
    if (css) Object.assign(s.style, css);
    return s;
  }
  function rng(seed) {
    let a = seed >>> 0;
    return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  }
  const css = (n, o) => Object.assign(n.style, o);
  function setT(n, dx, dy, s = 1, rot = 0) {
    n.style.transform = `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px) scale(${s.toFixed(4)}) rotate(${rot.toFixed(3)}deg)`;
  }
  function appear(n, p, dx = 0, dy = 24, s0 = 1) {
    n.style.opacity = clamp(p * 1.5).toFixed(3);
    setT(n, dx * (1 - p), dy * (1 - p), lerp(s0, 1, p));
  }
  // গতির ধরন: smooth = নরম, snappy = ঝটপট
  const MOT = S.motion === "snappy" ? { pop: E.outBack, dur: 0.82, text: E.outExpo } : { pop: E.outBack, dur: 1.0, text: E.outCubic };
  const dsp = (d) => d * MOT.dur;
  function fitW(node, maxW, base) {
    // লেখা বেশি চওড়া হলে ফন্ট ছোট করে বসায়
    let w = node.scrollWidth;
    try { const r = document.createRange(); r.selectNodeContents(node); const bw = r.getBoundingClientRect().width; if (bw > 0) w = bw; } catch (e) {}
    if (w > maxW) node.style.fontSize = Math.max(10, Math.floor(base * maxW / w)) + "px";
  }
  function pathLen(p) { try { return p.getTotalLength(); } catch (e) { return 2000; } }
  function drawOn(p, k, len) {
    const L = len || p.__len || (p.__len = pathLen(p));
    p.setAttribute("stroke-dasharray", L);
    p.setAttribute("stroke-dashoffset", (1 - k) * L);
  }

  // ---------- থিম: CSS ভ্যারিয়েবল ----------
  const root = document.documentElement.style;
  root.setProperty("--ink", C.ink);
  root.setProperty("--sub", C.sub);
  root.setProperty("--accent", C.accent);
  root.setProperty("--accentL", C.accentL);
  root.setProperty("--accentD", C.accentD);
  root.setProperty("--accent2", C.accent2);
  root.setProperty("--onAccent", C.onAccent);
  root.setProperty("--chip", C.chip);
  root.setProperty("--halo", C.halo);
  root.setProperty("--serif", `"${FN.display}", "Noto Serif", "FreeSerif", serif`);
  root.setProperty("--sans", `"${FN.body}", "Noto Sans", "FreeSans", sans-serif`);
  root.setProperty("--bn", `"${FN.bn}", "Noto Sans Bengali", "Hind Siliguri", "Lohit Bengali", "FreeSans", sans-serif`);
  root.setProperty("--dw", FN.dw);
  root.setProperty("--bw", FN.bw);
  document.body.setAttribute("data-chip", S.chip);
  document.body.setAttribute("data-dark", TH.dark ? "1" : "0");
  document.getElementById("stage").style.width = W + "px";
  document.getElementById("stage").style.height = H + "px";
  const GOLD = C.accent, GOLD_L = C.accentL, GOLD_D = C.accentD, INK = C.ink, SUB = C.sub;
  const NF = 0.889;   // মূল ডিজাইনে শিরোনামের কার্যকর আকার (960/1080)
  const DC = "serif" + (S.upper ? " upper" : "");   // হেডিং ক্লাস
  const LS = (px) => (px * S.ls).toFixed(1) + "px"; // লেটার-স্পেসিং

  // ---------- আকার (ornament) ----------
  function starPath(cx, cy, R, r, n = 8) {
    let d = "";
    for (let i = 0; i < n * 2; i++) {
      const a = (Math.PI / n) * i - Math.PI / 2;
      const rad = i % 2 === 0 ? R : r;
      d += (i ? "L" : "M") + (cx + rad * Math.cos(a)).toFixed(2) + " " + (cy + rad * Math.sin(a)).toFixed(2);
    }
    return d + "Z";
  }
  function sparkPath(cx, cy, R) {
    const r = R * 0.18;
    return `M${cx} ${cy - R} Q${cx + r} ${cy - r} ${cx + R} ${cy} Q${cx + r} ${cy + r} ${cx} ${cy + R} Q${cx - r} ${cy + r} ${cx - R} ${cy} Q${cx - r} ${cy - r} ${cx} ${cy - R}Z`;
  }
  function polyPath(pts) { return pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join("") + "Z"; }
  function ornPath(kind, cx, cy, R) {
    const rot = (x, y, a) => [cx + x * Math.cos(a) - y * Math.sin(a), cy + x * Math.sin(a) + y * Math.cos(a)];
    switch (kind) {
      case "hex": return polyPath(Array.from({ length: 6 }, (_, i) => { const a = (Math.PI / 3) * i - Math.PI / 2; return [cx + R * Math.cos(a), cy + R * Math.sin(a)]; }));
      case "leaf": {
        const a = 0.7, t = rot(0, -R, a), b = rot(0, R, a), c1 = rot(R * 1.05, 0, a), c2 = rot(-R * 1.05, 0, a);
        return `M${t[0]} ${t[1]} Q${c1[0]} ${c1[1]} ${b[0]} ${b[1]} Q${c2[0]} ${c2[1]} ${t[0]} ${t[1]}Z`;
      }
      case "sun": return starPath(cx, cy, R, R * 0.7, 12);
      case "circle": return `M${cx - R} ${cy}A${R} ${R} 0 1 0 ${cx + R} ${cy}A${R} ${R} 0 1 0 ${cx - R} ${cy}Z`;
      case "spark": return sparkPath(cx, cy, R);
      case "drop": return `M${cx} ${cy - R}C${cx + R * 0.15} ${cy - R * 0.55} ${cx + R * 0.8} ${cy - R * 0.1} ${cx + R * 0.8} ${cy + R * 0.3}A${R * 0.8} ${R * 0.8} 0 1 1 ${cx - R * 0.8} ${cy + R * 0.3}C${cx - R * 0.8} ${cy - R * 0.1} ${cx - R * 0.15} ${cy - R * 0.55} ${cx} ${cy - R}Z`;
      case "tri": return polyPath([[cx, cy - R], [cx + R * 0.92, cy + R * 0.7], [cx - R * 0.92, cy + R * 0.7]]);
      case "plus": { const w = R * 0.34; return polyPath([[cx - w, cy - R], [cx + w, cy - R], [cx + w, cy - w], [cx + R, cy - w], [cx + R, cy + w], [cx + w, cy + w], [cx + w, cy + R], [cx - w, cy + R], [cx - w, cy + w], [cx - R, cy + w], [cx - R, cy - w], [cx - w, cy - w]]); }
      case "square": return polyPath([[cx - R * 0.78, cy - R * 0.78], [cx + R * 0.78, cy - R * 0.78], [cx + R * 0.78, cy + R * 0.78], [cx - R * 0.78, cy + R * 0.78]]);
      case "moon": return `M${cx + R * 0.25} ${cy - R}A${R} ${R} 0 1 0 ${cx + R * 0.25} ${cy + R}A${R * 0.78} ${R * 0.78} 0 1 1 ${cx + R * 0.25} ${cy - R}Z`;
      case "diamond": return polyPath([[cx, cy - R], [cx + R * 0.72, cy], [cx, cy + R], [cx - R * 0.72, cy]]);
      default: return starPath(cx, cy, R, R * 0.55, 8);
    }
  }
  const orn = (cx, cy, R) => ornPath(S.orn, cx, cy, R);

  // ---------- লেআউট (রেশিও অনুযায়ী মাপ) ----------
  const WIDE = W / H > 1.12;
  const k = WIDE ? clamp((W / H - 1.3333) / (1.7778 - 1.3333)) : clamp((H - 1080) / 840);
  const lk = (sq, tall) => lerp(sq, tall, k);
  const G = { W, H, wide: WIDE, k, lk };
  if (!WIDE) {
    Object.assign(G, {
      ts: lk(0.9, 1), hs: lk(0.54, 1), hdr: lk(66, 215), cTop: lk(305, 600), cBot: lk(700, 1330), cy: lk(520, 905),
      capTop: lk(742, 1380), capH: lk(150, 200), capFont: lk(50, 56), capW: W - 120, brandY: lk(990, 1668),
      compact: H < 1300,
    });
  } else {
    Object.assign(G, {
      ts: lk(1.1, 1.2), hs: 0.74, hdr: 60, cTop: 290, cBot: 800, cy: 552,
      // Landscape captions are bottom-anchored inside the canvas, never outside it.
      // Keep a responsive footer-safe margin and scale the caption box with output height.
      capH: Math.min(156, Math.max(92, H * 0.125)),
      capTop: H - Math.min(156, Math.max(92, H * 0.125)) - Math.max(118, H * 0.155),
      capFont: Math.min(lk(46, 54), H * 0.042),
      capW: Math.min(W * 0.84, 1640), brandY: H - Math.max(112, H * 0.155),
      compact: true,
    });
  }
  G.textW = Math.min(W - 120, WIDE ? 1500 : 960);   // লেখার সর্বোচ্চ প্রস্থ
  G.cx = W / 2;
  G.yv = (sq, tall) => lk(sq, tall);

  // ---------- হিরো (প্রোডাক্ট / টপিক ছবি) অবস্থা, সিন অনুযায়ী ----------
  // fx, fy = ক্যানভাসের অনুপাত; s = আকার (hero unit দিয়ে গুণ হবে)
  const HS = {
    intro: [0.5, 0.405, 0.76], title: [0.5, 0.547, 0.78], blend: [0.5, 0.471, 0.72], traits: [0.5, 0.471, 0.86], notes: [0.5, 0.471, 0.86],
    family: [0.5, 0.471, 0.5], character: [0.5, 0.609, 0.5], occasions: [0.79, 0.417, 0.6], cta: [0.5, 0.435, 0.8], statement: [0.5, 0.521, 0.7],
    headline: [0.5, 0.64, 0.62], stat: [0.5, 0.64, 0.36], quote: [0.5, 0.66, 0.5], steps: [0.5, 0.66, 0.5], compare: [0.5, 0.66, 0.5],
  };
  // স্কয়ার/ল্যান্ডস্কেপে কিছু সিনে হিরোর অবস্থান আলাদা করে বসাই
  const HS_SQ = {
    intro: [0.5, 0.5, 0.95], title: [0.5, 0.64, 0.62], blend: [0.5, 0.55, 0.78], character: [0.5, 0.6, 0.4], cta: [0.5, 0.47, 0.6],
    statement: [0.5, 0.62, 0.62], headline: [0.5, 0.7, 0.5], stat: [0.5, 0.7, 0.42], quote: [0.5, 0.7, 0.42], steps: [0.5, 0.7, 0.42], compare: [0.5, 0.7, 0.42],
  };
  const HS_WIDE = {
    intro: [0.50, 0.385, 0.48], title: [0.27, 0.46, 0.78], blend: [0.74, 0.46, 0.82], traits: [0.5, 0.52, 0.95], notes: [0.5, 0.52, 0.95], family: [0.72, 0.46, 0.72],
    character: [0.19, 0.46, 0.95], occasions: [0.76, 0.46, 0.95], cta: [0.27, 0.46, 1.0], statement: [0.2, 0.46, 0.95],
    headline: [0.2, 0.46, 0.95], stat: [0.2, 0.46, 0.9], quote: [0.2, 0.46, 0.9], steps: [0.5, 0.74, 0.5], compare: [0.5, 0.86, 0.3],
  };
  G.heroState = function (type) {
    let a = HS[type] || [0.5, 0.5, 0.78];
    if (WIDE) a = HS_WIDE[type] || a;
    else if (H < 1500) {
      const b = HS_SQ[type];
      if (b) { a = [lerp(b[0], a[0], k), lerp(b[1], a[1], k), lerp(b[2], a[2], k)]; }
      else a = [a[0], a[1], a[2]];
    }
    // ফ্র্যাকশনকে বাস্তব পিক্সেলে নিই
    return { x: a[0] * W, y: a[1] * H, s: a[2] * G.hs };
  };
  RT.hasHero = true;

  // ---------- স্তর ----------
  const stage = document.getElementById("stage");
  stage.style.background = TH.bgCss || `radial-gradient(ellipse at 50% 40%, ${C.bg[0]} 0%, ${C.bg[1]} 55%, ${C.bg[2]} 100%)`;
  const bgL = el("div", "layer", stage);
  const fx = el("canvas", "layer", stage);
  const DPR = window.devicePixelRatio || 1;
  fx.width = Math.round(W * DPR); fx.height = Math.round(H * DPR);
  fx.style.width = W + "px"; fx.style.height = H + "px";
  const backL = el("div", "layer", stage);
  const spotEl = el("div", "spot", stage);
  const heroEls = [];
  const frontL = el("div", "layer", stage);
  const capL = el("div", "layer", stage);
  const chromeL = el("div", "layer", stage);
  Object.assign(RT, { D, CFG, TH, C, S, FN, W, H, G, clamp, lerp, E, prog, el, sv, svgRoot, rng, css, setT, appear, MOT, dsp, fitW, pathLen, drawOn,
    GOLD, GOLD_L, GOLD_D, INK, SUB, DC, LS, NF, starPath, sparkPath, ornPath, orn, stage, bgL, fx, backL, frontL, capL, chromeL, spotEl, heroEls, DPR, NS, polyPath });
  document.querySelectorAll(".layer").forEach((n) => { n.style.width = W + "px"; n.style.height = H + "px"; });

  // ---------- হিরো ছবি তৈরি ----------
  const heroes = D.heroes || [];
  RT.hasHero = heroes.length > 0;
  heroes.forEach((h, i) => {
    const wrap = el("div", "hero hero-" + h.mode, stage);
    stage.insertBefore(wrap, frontL);
    const img = el("img", "", wrap);
    img.src = h.src;
    if (h.mode === "card") {
      const m = 860, ar = h.w / h.h;
      const cw = ar >= 1 ? m : m * ar, ch = ar >= 1 ? m / ar : m;
      css(img, { position: "absolute", width: cw + "px", height: ch + "px", left: (1000 - cw) / 2 + "px", top: (1000 - ch) / 2 + "px" });
    }
    heroEls.push({ wrap, img, h });
  });
  RT.heroImgsReady = () => Promise.all(heroEls.map(({ img }) => new Promise((r) => { if (img.complete) r(); else { img.onload = r; img.onerror = r; } })));
  // ছবি না থাকলে থিমের নকশায় একটা প্রতীক (emblem)
  let emblem = null;
  if (!heroes.length) {
    const wrap = el("div", "hero hero-emblem", stage);
    stage.insertBefore(wrap, frontL);
    const s = svgRoot(wrap, 1000, 1000);
    const defs = sv("defs", {}, s);
    const g = sv("radialGradient", { id: "emg", cx: "50%", cy: "45%", r: "60%" }, defs);
    sv("stop", { offset: "0%", "stop-color": C.accentL }, g); sv("stop", { offset: "100%", "stop-color": C.accent }, g);
    sv("circle", { cx: 500, cy: 500, r: 330, fill: "url(#emg)", opacity: 0.22 }, s);
    const rings = [300, 372, 440].map((r, i) => sv("circle", { cx: 500, cy: 500, r, fill: "none", stroke: C.accent, "stroke-width": 4 - i, "stroke-dasharray": i === 1 ? "6 16" : "none", opacity: 0.85 - i * 0.2 }, s));
    sv("path", { d: orn(500, 500, 190), fill: "url(#emg)", stroke: C.accentD, "stroke-width": 5, "stroke-linejoin": "round" }, s);
    sv("path", { d: orn(500, 500, 100), fill: C.bg[0], opacity: 0.9 }, s);
    for (let i = 0; i < 12; i++) { const a = (Math.PI * 2 / 12) * i; sv("path", { d: orn(500 + 372 * Math.cos(a), 500 + 372 * Math.sin(a), 20), fill: C.accent }, s); }
    emblem = { wrap, rings };
    heroEls.push({ wrap, img: null, h: { mode: "emblem" } });
  }
  RT.emblem = emblem;
})(window.RT);
