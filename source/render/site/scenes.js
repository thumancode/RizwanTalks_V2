/* মোশন গ্রাফিক্স স্টেজ (ভাগ ৩): সিন তৈরির ফাংশন।
   পুরনো সিন: intro, title, blend, traits, notes, family, character, occasions, cta, statement
   নতুন সিন: headline, stat, quote, steps, compare
   লেআউট (পোর্ট্রেট / স্কয়ার / ল্যান্ডস্কেপ) G দিয়ে নিজে থেকে মানিয়ে নেয়। */
(function (RT) {
  const { W, H, C, S, G, CFG, el, sv, svgRoot, rng, css, clamp, lerp, prog, E, appear, MOT, dsp, fitW, drawOn,
    GOLD, GOLD_L, GOLD_D, INK, SUB, DC, LS, NF, starPath, sparkPath, orn, ornPath, rgba } = RT;
  const B = {};
  RT.B = B;
  const BN = /[\u0980-\u09FF]/;
  const isBn = (s) => BN.test(s || "");
  const lk = G.lk;
  const TXT = RT.TH.dark ? C.sub : GOLD_D;   // গৌণ লেখার রং

  // ---------- জোন (লেখা কোথায় বসবে) ----------
  const RIGHT_T = ["title", "character", "statement", "headline", "stat", "quote", "cta"];
  const LEFT_T = ["intro", "blend", "family", "occasions"];
  function zoneOf(type) {
    if (G.wide) {
      if (RIGHT_T.includes(type)) return { x: W * 0.5, w: W * 0.47, cx: W * 0.735 };
      if (LEFT_T.includes(type)) return { x: W * 0.03, w: W * 0.47, cx: W * 0.265 };
    }
    return { x: 0, w: W, cx: W / 2 };
  }
  RT.zoneOf = zoneOf;
  const Y = (sq, tall, wide) => (G.wide && wide != null ? wide : lk(sq, tall));

  // ---------- লেখার স্টাইল ----------
  function headingStyle(node, text, size, ls, weight) {
    const bn = isBn(text);
    node.className = (bn ? "bn" : DC) + " nowrap";
    css(node, { fontSize: (bn ? size * 0.78 : size) + "px", letterSpacing: bn ? "0px" : LS(ls), lineHeight: bn ? "1.3" : "1.05", color: INK });
    if (bn) node.style.fontWeight = weight || 700;
    node.textContent = text;
  }
  function units(text) {
    // বাংলা হলে শব্দ ধরে, নাহলে অক্ষর ধরে ভাঙি (যুক্তাক্ষর যেন না ভাঙে)
    if (isBn(text)) return text.split(/(\s+)/).filter((x) => x.length);
    return [...text];
  }
  function splitLetters(parent, text, css0) {
    const wrap = el("div", "nowrap", parent, Object.assign({ display: "inline-block" }, css0 || {}));
    const spans = units(text).map((ch) => { const s = el("span", "", wrap, { display: "inline-block", whiteSpace: "pre" }); s.textContent = ch; return s; });
    return { wrap, spans };
  }
  function place(node, z) { css(node, { left: z.x + "px", width: z.w + "px" }); }

  // ---------- সাজানো রেখা (rule) ----------
  function makeRule(parent, w) {
    const h = 22, mid = w / 2, y = 11;
    const box = el("div", "", parent, { margin: "14px auto 0", width: w + "px", height: h + "px", position: "relative" });
    const s = svgRoot(box, w, h);
    const lines = [], bits = [];
    const ln = (x1, x2, col, sw) => { const l = sv("line", { x1, y1: y, x2, y2: y, stroke: col || GOLD, "stroke-width": sw || 2 }, s); lines.push({ l, len: Math.abs(x2 - x1) }); return l; };
    const kind = S.rule;
    if (kind === "bar") {
      bits.push(sv("rect", { x: mid - 70, y: y - 4, width: 140, height: 8, rx: 4, fill: C.accent }, s));
      bits.push(sv("rect", { x: mid + 82, y: y - 4, width: 16, height: 8, rx: 4, fill: C.accent2 }, s));
    } else if (kind === "dots") {
      ln(24, mid - 36); ln(mid + 36, w - 24);
      [-16, 0, 16].forEach((d, i) => bits.push(sv("circle", { cx: mid + d, cy: y, r: i === 1 ? 6 : 4, fill: i === 1 ? C.accent2 : GOLD }, s)));
    } else if (kind === "line") {
      s.style.filter = `drop-shadow(0 0 6px ${C.accent})`;
      ln(14, w - 14, C.accent, 3);
    } else {
      ln(mid, 20); ln(mid, w - 20);
      bits.push(sv("path", { d: orn(mid, y, 11), fill: GOLD }, s));
    }
    return (q) => {
      lines.forEach(({ l, len }) => { l.setAttribute("stroke-dasharray", len + 4); l.setAttribute("stroke-dashoffset", (1 - q) * (len + 4)); });
      bits.forEach((b) => { b.style.opacity = q; });
      box.style.opacity = q;
    };
  }

  // ---------- হেডার (শিরোনাম + রেখা + উপশিরোনাম) ----------
  function header(front, sc, opts = {}) {
    const ts = G.ts;
    const zone = opts.zone || { x: 0, w: W, cx: W / 2 };
    const size0 = (opts.size || 96) * ts * (opts.k || 1) * NF;
    const wrap = el("div", "abs", front, { top: (opts.y != null ? opts.y : G.hdr) + "px", textAlign: "center" });
    place(wrap, zone);
    const t1 = el("div", "", wrap);
    const head = sc.heading || sc.title || "";
    headingStyle(t1, head, size0, 10);
    const rule = makeRule(wrap, 420 * Math.min(1, ts));
    const subText = sc.sub || sc.subheading || sc.bn || "";
    const t2 = el("div", "bn nowrap", wrap, { fontSize: 38 * ts + "px", fontWeight: 600, color: TXT, marginTop: "8px", letterSpacing: "1px" });
    t2.textContent = subText;
    const mw = Math.min(zone.w - 60, G.textW);
    fitW(t1, mw, parseFloat(t1.style.fontSize));
    fitW(t2, mw, 38 * ts);
    if (!subText) t2.style.display = "none";
    const f = (t, s) => {
      const p = prog(t, s + 0.15, dsp(0.7), MOT.text);
      css(t1, { opacity: clamp(p * 1.6), transform: `translateY(${(1 - p) * 30}px)`, filter: `blur(${(1 - p) * 8}px)` });
      rule(prog(t, s + 0.45, dsp(0.7)));
      const r = prog(t, s + 0.6, dsp(0.6));
      css(t2, { opacity: clamp(r * 1.5), transform: `translateY(${(1 - r) * 16}px)` });
    };
    f.bottom = wrap.offsetTop + wrap.offsetHeight;
    return f;
  }

  function pyramid(front, level, x, y, sc0) {
    const g = svgRoot(front, 150, 130, { left: x - 75 + "px", top: y + "px", transformOrigin: "50% 0%" });
    const tiers = { top: "M75 6 L50 44 L100 44 Z", heart: "M46 50 L104 50 L122 88 L28 88 Z", base: "M24 94 L126 94 L148 128 L2 128 Z" };
    const els = {};
    for (const key in tiers) {
      const on = key === level;
      els[key] = sv("path", { d: tiers[key], fill: on ? GOLD : "none", stroke: GOLD, "stroke-width": 2.5, "stroke-linejoin": "round", opacity: on ? 1 : 0.5 }, g);
    }
    return (t, s) => {
      const p = prog(t, s + 0.1, 0.6, E.outBack);
      g.style.opacity = clamp(p * 2);
      g.style.transform = `scale(${lerp(0.7, 1, p) * sc0})`;
      els[level].setAttribute("opacity", 0.75 + 0.25 * Math.sin(t * 5));
    };
  }

  // ---------- চিপ ----------
  function makeChip(front, it, kind) {
    const chip = el("div", "chip", front);
    chip.style.fontSize = 38 * G.ts + "px";
    let dot;
    if (kind === "traits") {
      dot = el("div", "", chip, { width: "34px", height: "34px", flex: "none" });
      const ds = svgRoot(dot, 34, 34);
      sv("path", { d: orn(17, 17, 16), fill: GOLD }, ds);
      sv("circle", { cx: 17, cy: 17, r: 4, fill: C.bg[0] }, ds);
    } else {
      dot = el("div", "dot", chip);
      dot.style.background = `radial-gradient(circle at 35% 30%, #ffffffaa 0%, ${it.color || GOLD} 55%)`;
      dot.style.backgroundColor = it.color || GOLD;
    }
    const lab = el("span", isBn(it.label) ? "bn" : "", chip); lab.textContent = it.label;
    return chip;
  }

  function orbitChips(front, back, sc, kind) {
    const items = sc.items || [];
    const n = items.length;
    const hs = G.heroState(sc.type);
    const hasHero = RT.heroVisible(sc.type);
    const halfW = (hasHero ? 155 : 60) * hs.s;
    const cx = W / 2;
    const lineSvg = svgRoot(back);
    const nodes = items.map((it) => { const chip = makeChip(front, it, kind); return { chip, it, w: chip.offsetWidth, h: chip.offsetHeight }; });
    const chipH = nodes[0] ? nodes[0].h : 76;
    const gapL = (n <= 4 ? 310 : 262) * (G.wide ? 0.9 : 1);
    const avail = G.cBot - G.cTop;
    const gap = Math.min(gapL, (avail - chipH) / Math.max(0.5, (n - 1) / 2));
    const span = ((n - 1) / 2) * gap;
    const yMid = Math.min(hs.y - lk(0, 72), (G.cTop + G.cBot) / 2 + lk(0, 60));
    const y0 = yMid - span / 2 - chipH / 2;
    const inner = Math.max(168 * G.ts, halfW + 38 * G.ts);
    const maxW = Math.min(336 * G.ts, cx - inner - 40);
    nodes.forEach((o, k) => {
      const left = k % 2 === 0;
      const row = Math.floor(k / 2);
      const y = y0 + row * gap + (left ? 0 : gap / 2);
      o.left = left; o.y = y;
      o.fit = o.w > maxW ? maxW / o.w : 1;
      o.chip.style.top = y + "px";
      if (left) { o.chip.style.right = W - (cx - inner) + "px"; o.chip.style.transformOrigin = "100% 50%"; }
      else { o.chip.style.left = cx + inner + "px"; o.chip.style.transformOrigin = "0% 50%"; }
      const ex = left ? cx - inner : cx + inner;
      const bx = left ? cx - halfW : cx + halfW;
      const cy = y + chipH / 2;
      o.line = sv("line", { x1: ex, y1: cy, x2: bx, y2: cy, stroke: GOLD, "stroke-width": 2.5 }, lineSvg);
      o.node = sv("circle", { cx: bx, cy, r: 8, fill: GOLD }, lineSvg);
      o.ring = sv("circle", { cx: ex, cy, r: 10, fill: "none", stroke: GOLD, "stroke-width": 2.5 }, lineSvg);
      o.ex = ex; o.bx = bx;
    });
    return (t) => {
      nodes.forEach((o) => {
        const p = prog(t, o.it.t, dsp(0.65), MOT.pop);
        const dir = o.left ? -1 : 1;
        o.chip.style.opacity = clamp(p * 2).toFixed(3);
        o.chip.style.transform = `translate(${dir * 70 * (1 - p)}px, 0) scale(${o.fit * lerp(0.85, 1, clamp(p, 0, 1.2))})`;
        const q = prog(t, o.it.t + 0.12, 0.5);
        const len = Math.abs(o.bx - o.ex);
        o.line.setAttribute("stroke-dasharray", len);
        o.line.setAttribute("stroke-dashoffset", (1 - q) * len);
        o.line.style.opacity = q > 0 ? 0.9 : 0;
        o.node.setAttribute("r", 8 * clamp(q * 1.2));
        o.node.style.opacity = q;
        const rp = clamp((t - o.it.t) / 0.7);
        o.ring.setAttribute("r", 10 + 34 * E.outCubic(rp));
        o.ring.style.opacity = t < o.it.t ? 0 : (1 - rp) * 0.8;
      });
    };
  }

  // ======================================================== intro
  B.intro = (sc, L) => {
    const z = zoneOf("intro");
    const hs = G.heroState("intro");
    const size = Math.min(1500, Math.max(W, H) * 1.3);
    const rays = el("div", "abs", L.b, { width: size + "px", height: size + "px", left: hs.x - size / 2 + "px", top: hs.y - size / 2 + "px", borderRadius: "50%",
      background: `repeating-conic-gradient(from 0deg, ${rgba(C.accent, 0.30)} 0deg 5deg, ${rgba(C.accent, 0)} 5deg 12deg)`,
      WebkitMaskImage: "radial-gradient(circle, #000 12%, rgba(0,0,0,0.55) 40%, transparent 68%)", maskImage: "radial-gradient(circle, #000 12%, rgba(0,0,0,0.55) 40%, transparent 68%)" });
    if (S.rays === "none") rays.style.display = "none";
    const rs = svgRoot(L.b);
    const rings = [0, 1, 2].map(() => sv("circle", { cx: hs.x, cy: hs.y, r: 100, fill: "none", stroke: GOLD, "stroke-width": 3 }, rs));
    const top = Y(52, 170, H * 0.3);
    const ts = G.ts;
    const wrap = el("div", "abs", L.f, { top: top + "px", textAlign: "center" });
    place(wrap, z);
    const w1 = el("div", "sans upper nowrap", wrap, { fontSize: 30 * ts + "px", letterSpacing: "14px", color: TXT });
    w1.textContent = sc.welcome != null ? sc.welcome : (CFG.welcome != null ? CFG.welcome : "Welcome to");
    const w2 = el("div", "", wrap, { marginTop: "6px" });
    headingStyle(w2, sc.title || CFG.presenter || "", 104 * ts * lk(0.86, 1) * NF, 8);
    fitW(w2, z.w - 40, parseFloat(w2.style.fontSize));
    const ln = makeRule(wrap, 320);
    const sub = sc.subtitle || "";
    const w3 = el("div", "bn nowrap", wrap, { fontSize: 36 * ts + "px", color: TXT, marginTop: "10px", fontWeight: 600 });
    w3.textContent = sub;
    return (t) => {
      const lt = t - sc.start;
      rays.style.opacity = prog(lt, 0.2, 1.4) * 0.9;
      rays.style.transform = `rotate(${lt * 6}deg)`;
      rings.forEach((c, i) => {
        const p = ((lt - 0.2 - i * 0.55) % 1.65 + 1.65) % 1.65 / 1.65;
        const on = lt > 0.2 + i * 0.55;
        c.setAttribute("r", (120 + 520 * E.outCubic(p)) * lk(0.6, 1) * (G.wide ? 0.9 : 1));
        c.style.opacity = on && S.rays !== "none" ? (1 - p) * 0.7 : 0;
      });
      appear(w1, prog(lt, 0.25, dsp(0.8)), 0, 18);
      const p2 = prog(lt, 0.45, dsp(0.9), MOT.text);
      css(w2, { opacity: clamp(p2 * 1.5), transform: `translateY(${(1 - p2) * 30}px)`, filter: `blur(${(1 - p2) * 10}px)` });
      ln(prog(lt, 0.9, dsp(0.8)));
      appear(w3, prog(lt, 1.2, dsp(0.7)), 0, 14);
    };
  };

  // ---------- হিরোর পেছনের আকৃতি (arch/hex/oval/circle/rect/diamond) ----------
  function archPath(kind) {
    switch (kind) {
      case "hex": return "M0 -370L300 -200V200L0 370L-300 200V-200Z";
      case "oval": return "M-300 0A300 370 0 1 1 300 0A300 370 0 1 1 -300 0Z";
      case "circle": return "M-340 0A340 340 0 1 1 340 0A340 340 0 1 1 -340 0Z";
      case "rect": return "M-276 -370H276Q300 -370 300 -346V346Q300 370 276 370H-276Q-300 370 -300 346V-346Q-300 -370 -276 -370Z";
      case "diamond": return "M0 -400L330 0L0 400L-330 0Z";
      default: return "M-300 340V-60C-300 -200 -150 -290 0 -370C150 -290 300 -200 300 -60V340Z";
    }
  }
  function arch(back, cx, cy, sc = 1) {
    const g = svgRoot(back);
    const d = archPath(S.arch);
    const grp = sv("g", { transform: `translate(${cx} ${cy}) scale(${sc})` }, g);
    const fill = sv("path", { d, fill: rgba(C.accent, 0.10) }, grp);
    const s1 = sv("path", { d, fill: "none", stroke: GOLD, "stroke-width": 4, "stroke-linejoin": "round" }, grp);
    const s2 = sv("path", { d, fill: "none", stroke: GOLD, "stroke-width": 1.6, transform: "scale(0.9)" }, grp);
    const len = RT.pathLen(s1) || 2600;
    const len2 = len * 0.9;
    s1.setAttribute("stroke-dasharray", len); s2.setAttribute("stroke-dasharray", len);
    return (p) => {
      fill.style.opacity = p;
      s1.setAttribute("stroke-dashoffset", (1 - p) * len);
      s2.setAttribute("stroke-dashoffset", (1 - p) * len);
    };
  }
  const archScale = () => (G.wide ? 1.0 : lk(0.47, 1.05));

  // ======================================================== title
  B.title = (sc, L) => {
    const z = zoneOf("title");
    const hs = G.heroState("title");
    const u = G.wide ? 0.92 : lk(0.72, 1);
    const off = G.wide ? 44 : 0;
    const drawArch = arch(L.b, hs.x, G.wide ? hs.y : lk(hs.y + 20, 1010), archScale());
    const kick = el("div", "abs", L.f, { textAlign: "center", top: (250 * u + off) + "px" });
    place(kick, z);
    const k1 = el("div", "", kick);
    headingStyle(k1, CFG.brand || CFG.presenter || "", 82 * u * NF, 10);
    fitW(k1, z.w - 60, parseFloat(k1.style.fontSize));
    const k2 = el("div", "sans upper nowrap", kick, { fontSize: 28 * u + "px", letterSpacing: "12px", color: TXT, marginTop: "16px" });
    const tag = sc.tagline != null ? sc.tagline : (CFG.tagline != null ? CFG.tagline : "presents a premium creation");
    k2.textContent = tag;
    fitW(k2, z.w - 60, 28 * u);
    const name = (sc.name || CFG.productName || "");
    const parts = name.split(" ");
    const line1 = parts.slice(0, 1).join(" "), line2 = parts.slice(1).join(" ");
    const tw = el("div", "abs", L.f, { top: (290 * u + off) + "px", textAlign: "center" });
    place(tw, z);
    const nm = (txt, size, ls, wt, col, mt) => {
      const bn = isBn(txt);
      const o = splitLetters(tw, bn ? txt : txt.toUpperCase(), { fontFamily: bn ? "var(--bn)" : "var(--serif)", fontWeight: bn ? 700 : wt, fontSize: (bn ? size * 0.8 : size) + "px", letterSpacing: bn ? "0px" : LS(ls), lineHeight: bn ? "1.3" : "1.0", color: col, display: "block", textAlign: "center", marginTop: mt });
      return o;
    };
    const l1 = nm(line1, 132 * u, 8, RT.FN.dw, INK, "0px");
    const l2 = nm(line2, 84 * u, 14, Math.min(600, RT.FN.dw), TXT, "-4px");
    [l1, l2].forEach((l) => { const mw = z.w - 50; const w = l.wrap.scrollWidth; l._fit = w > mw ? mw / w : 1; });
    const sub = el("div", "abs", L.f, { top: (590 * u + off) + "px", textAlign: "center" });
    place(sub, z);
    const sRule = makeRule(sub, 380);
    const sT = el("div", "sans upper nowrap", sub, { fontSize: 40 * u + "px", letterSpacing: "16px", color: INK, marginTop: "12px", paddingLeft: "16px" });
    sT.textContent = sc.subtitle || CFG.productSubtitle || "";
    fitW(sT, z.w - 40, 40 * u);
    return (t) => {
      const lt = t - sc.start;
      const rv = sc.times.reveal;
      drawArch(prog(lt, 0.2, dsp(1.8), E.inOutCubic));
      const pk = prog(lt, 0.3, dsp(0.9));
      const move = E.inOutCubic(clamp((t - rv) / 0.9));
      css(kick, { opacity: clamp(pk * 1.5), top: lerp(430 * u + off, 150 * u + off, move) + "px", transform: `scale(${lerp(1.0, 0.6, move)}) translateY(${(1 - pk) * 20}px)` });
      k2.style.opacity = 1 - move;
      [l1, l2].forEach((l, li) => {
        l.spans.forEach((s, i) => {
          const p = prog(t, rv + 0.04 * i + li * 0.35, dsp(0.55), E.outBack);
          css(s, { opacity: clamp(p * 2), transform: `translateY(${(1 - p) * 60}px)`, filter: `blur(${(1 - clamp(p)) * 10}px)` });
        });
        l.wrap.style.transform = l._fit < 1 ? `scale(${l._fit})` : "";
      });
      const q = prog(t, rv + 1.1, 0.7);
      sRule(q);
      sub.style.opacity = q > 0 ? 1 : 0;
      const ps = prog(t, rv + 1.25, 0.7);
      css(sT, { opacity: clamp(ps * 1.5), transform: `translateY(${(1 - ps) * 16}px)` });
    };
  };

  // ======================================================== blend
  B.blend = (sc, L) => {
    const z = zoneOf("blend");
    const hs = G.heroState("blend");
    const cols = C.palette;
    const g = svgRoot(L.b);
    const bu = G.wide ? 0.8 : lk(0.62, 1);
    const circles = cols.map((c) => sv("circle", { r: 150 * bu, fill: c, "fill-opacity": 0.34, stroke: c, "stroke-opacity": 0.7, "stroke-width": 2.5 }, g));
    const u = G.wide ? 0.95 : lk(0.7, 1);
    const t1 = el("div", "abs", L.f, { top: Y(60, 215, 150) + "px", textAlign: "center" });
    place(t1, z);
    headingStyle(t1, sc.title || "", 132 * u, 10);
    t1.className = (isBn(sc.title) ? "bn" : DC) + " nowrap abs";
    t1.style.position = "absolute";
    fitW(t1, z.w - 50, parseFloat(t1.style.fontSize));
    const t2 = el("div", "serif nowrap abs", L.f, { top: Y(190, 370, 330) + "px", fontSize: 62 * u + "px", fontStyle: "italic", fontWeight: 600, color: TXT, textAlign: "center" });
    t2.textContent = "= " + (sc.meaning || "");
    place(t2, z);
    if (isBn(sc.meaning)) { t2.className = "bn nowrap abs"; t2.style.fontStyle = "normal"; }
    fitW(t2, z.w - 50, 62 * u);
    const t3 = el("div", "sans upper nowrap abs", L.f, { top: Y(270, 468, 440) + "px", fontSize: 32 * u + "px", letterSpacing: "8px", color: INK, textAlign: "center" });
    t3.textContent = sc.accords || "";
    place(t3, z);
    fitW(t3, z.w - 50, 32 * u);
    const cy = hs.y;
    return (t) => {
      const lt = t - sc.start;
      const e = E.outCubic(clamp((lt - 0.3) / 2.3));
      circles.forEach((c, i) => {
        const a = ((i * 60 - 90) + (1 - e) * 140 + lt * 4) * Math.PI / 180;
        const R = lerp(620, 150, e) * bu;
        c.setAttribute("cx", hs.x + R * Math.cos(a));
        c.setAttribute("cy", cy + R * Math.sin(a));
        c.style.opacity = clamp(lt / 0.4);
        c.setAttribute("r", lerp(110, 150, e) * bu);
      });
      const p1 = prog(lt, 0.15, dsp(0.8));
      css(t1, { opacity: clamp(p1 * 1.5), transform: `translateY(${(1 - p1) * 30}px)`, filter: `blur(${(1 - p1) * 8}px)` });
      const p2 = prog(t, sc.times.meaning, 0.8);
      css(t2, { opacity: clamp(p2 * 1.5), transform: `translateY(${(1 - p2) * 22}px)` });
      const p3 = prog(t, sc.times.accords, 0.8);
      css(t3, { opacity: clamp(p3 * 1.5), transform: `translateY(${(1 - p3) * 18}px)` });
    };
  };

  // ======================================================== traits / notes (চিপ-অরবিট)
  B.traits = (sc, L) => {
    const h = header(L.f, sc);
    const o = orbitChips(L.f, L.b, sc, "traits");
    return (t) => { h(t, sc.start); o(t); };
  };
  B.notes = (sc, L) => {
    const hy = G.wide ? G.hdr : lk(120, 252);
    const h = header(L.f, sc, { y: hy, size: 92 });
    const py = G.wide
      ? pyramid(L.f, sc.level || "top", W * 0.14, 70, 1)
      : pyramid(L.f, sc.level || "top", W / 2, lk(26, 95), lk(0.62, 1));
    const o = orbitChips(L.f, L.b, sc, "notes");
    return (t) => { h(t, sc.start); py(t, sc.start); o(t); };
  };

  // ======================================================== family (গোলাকার তালিকা)
  B.family = (sc, L) => {
    const z = zoneOf("family");
    const hs = G.heroState("family");
    const h = header(L.f, sc, { zone: z, y: G.wide ? H * 0.12 : G.hdr });
    const cx = hs.x, cy = G.wide ? hs.y : lk(560, 905);
    const rx = G.wide ? Math.min(W * 0.21, 400) : 372;
    const ry = G.wide ? 235 : lk(185, 372);
    const fi = G.wide ? 0.66 : lk(0.62, 1);
    const g = svgRoot(L.b);
    const ring = sv("ellipse", { cx, cy, rx, ry, fill: "none", stroke: GOLD, "stroke-width": 2, "stroke-dasharray": "4 14", "stroke-linecap": "round", opacity: 0.8 }, g);
    const items = sc.items || [];
    const N = items.length;
    const nodes = items.map((it, k) => {
      const ang = (-90 + k * (360 / N)) * Math.PI / 180;
      const x = cx + rx * Math.cos(ang), y = cy + ry * Math.sin(ang);
      const wrap = el("div", "abs", L.f, { left: x - 120 + "px", top: y - 86 * fi + "px", width: "240px", height: "230px", textAlign: "center", transformOrigin: "50% " + 86 * fi + "px" });
      const s = svgRoot(wrap, 240, 172, { left: "0px", top: "0px", transform: `scale(${fi})`, transformOrigin: "50% 0%" });
      const c = it.color || GOLD;
      sv("circle", { cx: 120, cy: 86, r: 78, fill: C.bg[0], stroke: GOLD, "stroke-width": 3 }, s);
      sv("circle", { cx: 120, cy: 86, r: 68, fill: c, "fill-opacity": 0.2 }, s);
      sv("path", { d: orn(120, 86, 56), fill: c, "fill-opacity": 0.95, stroke: C.bg[0], "stroke-width": 2.5, "stroke-linejoin": "round" }, s);
      sv("circle", { cx: 120, cy: 86, r: 15, fill: C.bg[0], stroke: GOLD, "stroke-width": 2.5 }, s);
      const lab = el("div", "sans nowrap", wrap, { position: "absolute", left: "0px", top: 176 * fi + "px", width: "240px", fontSize: 36 * fi * G.ts + "px", fontWeight: 600, letterSpacing: "1px", color: INK });
      lab.textContent = it.label;
      const spoke = sv("line", { x1: cx + (rx - 90) * Math.cos(ang), y1: cy + (ry - 90 * fi) * Math.sin(ang), x2: cx + 112 * fi * Math.cos(ang), y2: cy + 112 * fi * Math.sin(ang), stroke: GOLD, "stroke-width": 2, opacity: 0.7 }, g);
      return { wrap, spoke, it };
    });
    return (t) => {
      h(t, sc.start);
      const lt = t - sc.start;
      ring.setAttribute("stroke-dashoffset", -lt * 8);
      ring.style.opacity = prog(lt, 0.3, 0.8) * 0.8;
      nodes.forEach((n) => {
        const p = prog(t, n.it.t, dsp(0.7), MOT.pop);
        n.wrap.style.opacity = clamp(p * 2);
        n.wrap.style.transform = `scale(${lerp(0.4, 1, clamp(p, 0, 1.15))}) rotate(${(1 - clamp(p)) * -40}deg)`;
        n.spoke.style.opacity = prog(t, n.it.t + 0.1, 0.5) * 0.8;
      });
    };
  };

  // ======================================================== character (বড় শব্দের সারি)
  B.character = (sc, L) => {
    const z = zoneOf("character");
    const bu = G.wide ? 0.95 : lk(0.78, 1);
    const hy = G.wide ? 70 : lk(60, 190);
    const h = header(L.f, sc, { zone: z, y: hy, size: 78 });
    const items = sc.items || [];
    const start = Math.max(h.bottom + 14, G.wide ? 250 : lk(250, 405));
    const pitch = Math.min(130 * bu, (G.cBot + (G.wide ? 20 : 0) - start) / Math.max(1, items.length));
    const rows = items.map((it, k) => {
      const y = start + k * pitch;
      const r = el("div", "abs", L.f, { top: y + "px", height: pitch + "px", textAlign: "center" });
      place(r, z);
      const bn = isBn(it.label);
      const w = splitLetters(r, bn ? it.label : it.label.toUpperCase(), { fontFamily: bn ? "var(--bn)" : "var(--serif)", fontWeight: bn ? 700 : RT.FN.dw, fontSize: (bn ? 90 : 112) * bu * (G.wide ? 1.05 : 1) + "px", letterSpacing: bn ? "0px" : LS(12), lineHeight: "1.05", display: "block", textAlign: "center",
        backgroundImage: `linear-gradient(100deg, ${C.accentD} 0%, ${C.accent} 40%, ${C.accentL} 50%, ${C.accent} 60%, ${C.accentD} 100%)`, backgroundSize: "300% 100%" });
      w.wrap.style.color = "transparent"; w.wrap.style.webkitBackgroundClip = "text"; w.wrap.style.backgroundClip = "text";
      const width = w.wrap.scrollWidth;
      const fit = width > z.w - 60 ? (z.w - 60) / width : 1;
      return { r, w, it, fit };
    });
    return (t) => {
      h(t, sc.start);
      rows.forEach((o) => {
        const p = prog(t, o.it.t, dsp(0.7), MOT.text);
        const lt = t - o.it.t;
        css(o.r, { opacity: clamp(p * 2), transform: `translateY(${(1 - p) * 50}px) scale(${o.fit * lerp(0.94, 1, p)})`, filter: `blur(${(1 - p) * 10}px)` });
        o.w.wrap.style.backgroundPosition = `${100 - clamp(lt / 1.6) * 100}% 0`;
      });
    };
  };

  // ======================================================== occasions / list (সংখ্যা-সহ তালিকা)
  B.occasions = (sc, L) => {
    const z = zoneOf("occasions");
    const bu = lk(0.78, 1);
    const h = header(L.f, sc, { zone: G.wide ? z : { x: 0, w: W, cx: W / 2 }, y: G.wide ? G.hdr : lk(66, 205), size: 88 });
    const items = sc.items || [];
    const left0 = G.wide ? z.x + 70 : 70;
    const rw = G.wide ? z.w - 100 : 660;
    const start = Math.max(h.bottom + 22, G.wide ? 300 : lk(300, 470));
    const pitch = Math.min(138 * (G.wide ? 0.9 : bu), (G.cBot + (G.wide ? 40 : 0) - start) / Math.max(1, items.length));
    const rows = items.map((it, k) => {
      const y = start + k * pitch;
      const rh = Math.min(110, pitch - 8);
      const r = el("div", "abs", L.f, { left: left0 + "px", top: y + "px", width: rw + "px", height: rh + "px", display: "flex", alignItems: "center", gap: "22px" });
      const num = el("div", "serif", r, { fontSize: 56 * bu * G.ts + "px", color: GOLD, width: 84 * bu + "px", flex: "none", fontWeight: 600, fontStyle: "italic" });
      num.textContent = String(k + 1).padStart(2, "0");
      const lab = el("div", (isBn(it.label) ? "bn" : "sans") + " nowrap", r, { fontSize: 44 * bu * G.ts + "px", fontWeight: 600, letterSpacing: "1px", color: INK, transformOrigin: "0 50%" });
      lab.textContent = it.label;
      const lw = lab.scrollWidth;
      const room = rw - 84 * bu - 22;
      const fit = lw > room ? room / lw : 1;
      lab.style.transform = fit < 1 ? `scale(${fit})` : "";
      const line = el("div", "abs", L.f, { left: left0 + "px", top: y + rh + 2 + "px", height: "2px", width: "0px", background: `linear-gradient(90deg, ${GOLD}, ${rgba(C.accent, 0)})` });
      return { r, line, it };
    });
    return (t) => {
      h(t, sc.start);
      rows.forEach((o) => {
        const p = prog(t, o.it.t, dsp(0.65), MOT.text);
        css(o.r, { opacity: clamp(p * 2), transform: `translateX(${(1 - p) * -90}px)` });
        o.line.style.width = prog(t, o.it.t + 0.1, 0.6) * (rw - 20) + "px";
      });
    };
  };
  B.list = B.occasions; B.bullets = B.occasions;

  // ======================================================== cta
  B.cta = (sc, L) => {
    const z = zoneOf("cta");
    const hs = G.heroState("cta");
    const u = G.wide ? 0.92 : lk(0.72, 1);
    const drawArch = arch(L.b, hs.x, G.wide ? hs.y : lk(hs.y + 10, 840), archScale());
    const size = Math.min(1500, Math.max(W, H) * 1.3);
    const rays = el("div", "abs", L.b, { width: size + "px", height: size + "px", left: hs.x - size / 2 + "px", top: hs.y - size / 2 + "px", borderRadius: "50%",
      background: `repeating-conic-gradient(from 0deg, ${rgba(C.accent, 0.26)} 0deg 5deg, ${rgba(C.accent, 0)} 5deg 12deg)`,
      WebkitMaskImage: "radial-gradient(circle, #000 12%, rgba(0,0,0,0.5) 40%, transparent 66%)", maskImage: "radial-gradient(circle, #000 12%, rgba(0,0,0,0.5) 40%, transparent 66%)" });
    if (S.rays === "none") rays.style.display = "none";
    const topT = G.wide ? 250 : lk(72, 200);
    const t1 = el("div", "abs", L.f, { top: topT + "px", textAlign: "center" });
    place(t1, z);
    headingStyle(t1, sc.headline || "Order Now", 142 * u * NF, 10);
    t1.className = (isBn(sc.headline) ? "bn" : DC) + " nowrap abs";
    t1.style.position = "absolute";
    fitW(t1, z.w - 50, parseFloat(t1.style.fontSize));
    const t2 = el("div", "sans upper nowrap abs", L.f, { top: topT + (G.wide ? 150 : lk(110, 185)) + "px", fontSize: 32 * u * G.ts + "px", letterSpacing: "10px", color: TXT, textAlign: "center" });
    t2.textContent = sc.line || "";
    place(t2, z);
    if (isBn(sc.line)) { t2.className = "bn nowrap abs"; t2.style.letterSpacing = "1px"; t2.style.textTransform = "none"; }
    fitW(t2, z.w - 50, 32 * u * G.ts);
    const bw = Math.min(820 * lk(0.86, 1), z.w - 90), bh = 124 * lk(0.78, 1);
    const bx = z.cx - bw / 2, by = G.wide ? topT + 330 : lk(644, 1205);
    const btn = el("div", "abs", L.f, { left: bx + "px", top: by + "px", width: bw + "px", height: bh + "px", borderRadius: bh / 2 + "px", overflow: "hidden",
      background: `linear-gradient(135deg, ${C.accentL} 0%, ${GOLD} 55%, ${GOLD_D} 100%)`, boxShadow: `0 18px 40px rgba(${C.glow},0.35), inset 0 2px 0 rgba(255,255,255,0.55)`, display: "flex", alignItems: "center", justifyContent: "center" });
    const bt = el("div", (isBn(sc.button) ? "bn" : "sans upper") + " nowrap", btn, { fontSize: 40 * u * G.ts + "px", fontWeight: 700, letterSpacing: isBn(sc.button) ? "0px" : "5px", color: C.onAccent, position: "relative" });
    bt.textContent = sc.button || "Order";
    fitW(bt, bw - 60, 40 * u * G.ts);
    const shine = el("div", "abs", btn, { top: "-20px", left: "-200px", width: "120px", height: bh + 50 + "px", background: "linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,0.65), rgba(255,255,255,0))", transform: "skewX(-20deg)" });
    const cur = svgRoot(L.f, 80, 90);
    const cg = sv("g", {}, cur);
    sv("path", { d: "M6 4 L6 66 L22 52 L34 80 L46 74 L34 48 L56 48 Z", fill: "#ffffff", stroke: RT.TH.dark ? "#000" : INK, "stroke-width": 4, "stroke-linejoin": "round" }, cg);
    const tx = bx + bw * 0.86, ty = by + bh * 0.5;
    const ripple = svgRoot(L.f);
    const rc = sv("circle", { cx: tx, cy: ty, r: 10, fill: "none", stroke: TXT, "stroke-width": 4 }, ripple);
    const sp = svgRoot(L.f);
    const sr = rng(5);
    const sparks = Array.from({ length: 22 }, () => ({ a: sr() * 6.28, d: (260 + sr() * 360) * lk(0.6, 1), s: (14 + sr() * 22) * lk(0.8, 1), e: sr() * 0.5 }));
    const spEls = sparks.map(() => sv("path", { d: sparkPath(0, 0, 1), fill: C.accentL }, sp));
    return (t) => {
      const lt = t - sc.start;
      drawArch(prog(lt, 0.1, dsp(1.6), E.inOutCubic));
      rays.style.opacity = prog(lt, 0.2, 1.2);
      rays.style.transform = `rotate(${lt * 5}deg)`;
      const p1 = prog(lt, 0.15, dsp(0.9), E.outBack);
      css(t1, { opacity: clamp(p1 * 1.5), transform: `scale(${lerp(0.8, 1, clamp(p1, 0, 1.1))})` });
      const p2 = prog(lt, 0.6, dsp(0.8));
      css(t2, { opacity: clamp(p2 * 1.5), transform: `translateY(${(1 - p2) * 18}px)` });
      const pb = prog(lt, 0.9, dsp(0.8), E.outBack);
      const press = lt > 1.65 ? 1 - 0.05 * Math.sin(Math.PI * clamp((lt - 1.65) / 0.3)) : 1;
      const pulse = lt > 2.2 ? 1 + 0.018 * Math.sin((lt - 2.2) * 4.5) : 1;
      css(btn, { opacity: clamp(pb * 2), transform: `translateY(${(1 - pb) * 60}px) scale(${lerp(0.8, 1, clamp(pb, 0, 1.1)) * press * pulse})` });
      shine.style.left = -200 + ((lt * 0.7) % 2.4) / 2.4 * (bw + 400) + "px";
      const cp = E.inOutCubic(clamp((lt - 0.95) / 0.7));
      const ccx = lerp(tx + 46, tx - 6, cp), ccy = lerp(ty + 300, ty - 4, cp);
      cur.style.left = ccx + "px"; cur.style.top = ccy + "px";
      cur.style.opacity = prog(lt, 0.9, 0.3) * (lt > 2.6 ? clamp(1 - (lt - 2.6) / 0.5) : 1);
      cg.setAttribute("transform", `scale(${lt > 1.65 ? 1 - 0.12 * Math.sin(Math.PI * clamp((lt - 1.65) / 0.3)) : 1})`);
      const rp = clamp((lt - 1.65) / 0.8);
      rc.setAttribute("r", 10 + 120 * E.outCubic(rp));
      rc.style.opacity = lt < 1.65 ? 0 : (1 - rp) * 0.9;
      sparks.forEach((s, i) => {
        const q = clamp((lt - 0.35 - s.e) / 1.6);
        const R = s.d * E.outCubic(q);
        const x = hs.x + R * Math.cos(s.a), y = hs.y + R * Math.sin(s.a);
        const sc2 = s.s * Math.sin(Math.PI * q);
        spEls[i].setAttribute("transform", `translate(${x} ${y}) scale(${sc2}) rotate(${q * 90})`);
        spEls[i].style.opacity = q > 0 && q < 1 ? 1 : 0;
      });
    };
  };

  // ======================================================== statement
  B.statement = (sc, L) => {
    const z = zoneOf("statement");
    const t1 = el("div", "bn abs", L.f, { top: Y(90, 300, H * 0.3) + "px", fontSize: 64 * G.ts + "px", fontWeight: 700, lineHeight: "1.5", color: INK, textAlign: "center", padding: "0 " + (G.wide ? 20 : 70) + "px", boxSizing: "border-box" });
    place(t1, z);
    t1.textContent = sc.text || "";
    return (t) => { const p = prog(t, sc.start + 0.2, dsp(0.8), MOT.text); css(t1, { opacity: clamp(p * 1.5), transform: `translateY(${(1 - p) * 30}px)` }); };
  };

  // ======================================================== headline (নিউজ-স্টাইল শিরোনাম)
  B.headline = (sc, L) => {
    const z = zoneOf("headline");
    const ts = G.ts;
    const top = G.wide ? 150 : lk(70, 250);
    const kick = el("div", "abs", L.f, { top: top + "px", textAlign: "center" });
    place(kick, z);
    const pill = el("div", "", kick, { display: "inline-flex", alignItems: "center", gap: "14px", padding: "10px 30px", borderRadius: S.chip === "pill" || S.chip === "glass" ? "40px" : "6px", background: C.accent, color: C.onAccent, fontFamily: isBn(sc.kicker) ? "var(--bn)" : "var(--sans)", fontWeight: 700, fontSize: 34 * ts + "px", letterSpacing: isBn(sc.kicker) ? "1px" : "6px", textTransform: "uppercase" });
    const dot = el("span", "", pill, { width: "16px", height: "16px", borderRadius: "50%", background: C.onAccent, display: "inline-block" });
    const kt = el("span", "", pill); kt.textContent = sc.kicker || "Breaking";
    const hdr = el("div", "bn abs", L.f, { top: top + 96 * ts + "px", fontSize: (G.wide ? 66 : lk(58, 72)) * ts + "px", fontWeight: 700, lineHeight: "1.38", color: INK, textAlign: "center", padding: "0 " + (G.wide ? 10 : 64) + "px", boxSizing: "border-box" });
    place(hdr, z);
    const words = (sc.text || sc.heading || "").split(/\s+/).filter(Boolean);
    const spans = words.map((w) => { const s = el("span", "", hdr, { display: "inline-block", marginRight: "0.28em" }); s.textContent = w; return s; });
    const src = el("div", "bn abs", L.f, { fontSize: 34 * ts + "px", color: TXT, textAlign: "center", fontWeight: 600, letterSpacing: "1px" });
    place(src, z);
    src.textContent = sc.source || "";
    src.style.top = hdr.offsetTop + hdr.offsetHeight + 26 + "px";
    const bar = el("div", "abs", L.f, { left: z.cx - 60 + "px", top: hdr.offsetTop + hdr.offsetHeight + 8 + "px", width: "120px", height: "5px", borderRadius: "3px", background: C.accent2 === C.accent ? C.accentL : C.accent });
    const per = Math.min(0.16, 1.6 / Math.max(1, words.length));
    return (t) => {
      const lt = t - sc.start;
      const pk = prog(lt, 0.1, dsp(0.6), E.outBack);
      css(kick, { opacity: clamp(pk * 2), transform: `translateY(${(1 - pk) * -30}px)` });
      dot.style.opacity = 0.5 + 0.5 * Math.sin(t * 6);
      spans.forEach((s, i) => { const p = prog(lt, 0.45 + i * per, dsp(0.5), MOT.text); css(s, { opacity: clamp(p * 1.6), transform: `translateY(${(1 - p) * 26}px)`, filter: `blur(${(1 - p) * 6}px)` }); });
      const pe = prog(lt, 0.6 + words.length * per, 0.7);
      bar.style.width = 120 * pe + "px"; bar.style.left = z.cx - 60 * pe + "px";
      css(src, { opacity: clamp(pe * 1.5), transform: `translateY(${(1 - pe) * 14}px)` });
    };
  };

  // ======================================================== stat (বড় সংখ্যা)
  const BD = "০১২৩৪৫৬৭৮৯";
  function parseNum(v) {
    const s = String(v);
    const m = s.match(/[0-9০-৯][0-9০-৯,.]*/);
    if (!m) return null;
    const raw = m[0];
    const bn = /[০-৯]/.test(raw);
    const ascii = raw.replace(/[০-৯]/g, (d) => BD.indexOf(d)).replace(/,/g, "");
    const dec = (ascii.split(".")[1] || "").length;
    return { pre: s.slice(0, m.index), post: s.slice(m.index + raw.length), val: parseFloat(ascii), dec, bn, comma: raw.includes(",") };
  }
  function fmtNum(n, x) {
    let s = x.toFixed(n.dec);
    if (n.comma) { const [a, b] = s.split("."); s = a.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (b ? "." + b : ""); }
    if (n.bn) s = s.replace(/[0-9]/g, (d) => BD[d]);
    return n.pre + s + n.post;
  }
  B.stat = (sc, L) => {
    const z = zoneOf("stat");
    const ts = G.ts;
    const num = parseNum(sc.value != null ? sc.value : "0");
    const cyR = G.wide ? 345 : lk(370, 600);
    const R = G.wide ? 170 : lk(175, 255);
    const g = svgRoot(L.b);
    const circ = 2 * Math.PI * R;
    sv("circle", { cx: z.cx, cy: cyR, r: R, fill: rgba(C.accent, 0.07), stroke: rgba(C.accent, 0.25), "stroke-width": 18 }, g);
    const arc = sv("circle", { cx: z.cx, cy: cyR, r: R, fill: "none", stroke: GOLD, "stroke-width": 18, "stroke-linecap": "round", transform: `rotate(-90 ${z.cx} ${cyR})`, "stroke-dasharray": circ }, g);
    const dots = Array.from({ length: 36 }, (_, i) => { const a = (i / 36) * 6.283; return sv("circle", { cx: z.cx + (R + 40) * Math.cos(a), cy: cyR + (R + 40) * Math.sin(a), r: 3, fill: GOLD, opacity: 0 }, g); });
    const pct = sc.percent != null ? clamp(parseFloat(sc.percent) / 100) : (num && /%|শতাংশ/.test(num.post) ? clamp(num.val / 100) : 0.78);
    const big = el("div", "abs nowrap", L.f, { top: cyR - 120 * ts * (G.wide ? 0.85 : lk(0.7, 1)) + "px", textAlign: "center", lineHeight: "1.0", fontFamily: "var(--serif)", fontWeight: RT.FN.dw, fontSize: (G.wide ? 170 : lk(130, 270)) * ts + "px", color: INK });
    place(big, z);
    big.textContent = sc.value || "";
    const bigFs = parseFloat(big.style.fontSize);
    // সংখ্যা বাংলা হলে বাংলা ফন্ট
    if (isBn(String(sc.value))) { big.style.fontFamily = "var(--bn)"; big.style.fontWeight = 700; big.style.fontSize = bigFs * 0.95 + "px"; }
    fitW(big, R * 2 - 60, parseFloat(big.style.fontSize));
    const lab = el("div", "abs", L.f, { top: cyR + R + (G.wide ? 26 : lk(44, 60)) + "px", textAlign: "center", fontSize: (isBn(sc.label) ? 52 : 46) * (G.wide ? 0.9 : ts) + "px", fontWeight: 700, color: INK, fontFamily: isBn(sc.label) ? "var(--bn)" : "var(--serif)", padding: "0 50px", boxSizing: "border-box", lineHeight: 1.3 });
    place(lab, z);
    lab.textContent = sc.label || "";
    const sub = el("div", "bn abs", L.f, { top: lab.offsetTop + lab.offsetHeight + 8 + "px", textAlign: "center", fontSize: 34 * ts + "px", color: TXT, fontWeight: 600, padding: "0 50px", boxSizing: "border-box" });
    place(sub, z);
    sub.textContent = sc.sub || sc.subtitle || "";
    const rv = (sc.times && sc.times.reveal) || sc.start + 0.7;
    return (t) => {
      const lt = t - rv;
      const p = clamp(lt / dsp(1.7));
      const e = E.outCubic(p);
      if (num) big.textContent = fmtNum(num, num.val * e);
      const pp = prog(t, sc.start + 0.2, 0.5);
      css(big, { opacity: clamp(pp * 2), transform: `scale(${lerp(0.85, 1, pp) * (1 + 0.04 * Math.sin(clamp(lt * 3, 0, 3.1)) * (lt > 0 ? 1 : 0))})` });
      arc.setAttribute("stroke-dashoffset", circ * (1 - pct * e));
      arc.style.opacity = pp;
      dots.forEach((d, i) => { d.style.opacity = clamp((lt - 0.4 - i * 0.02) * 2) * 0.55; });
      const pl = prog(lt, 0.9, 0.7);
      css(lab, { opacity: clamp(pl * 1.5), transform: `translateY(${(1 - pl) * 22}px)` });
      const ps = prog(lt, 1.15, 0.7);
      css(sub, { opacity: clamp(ps * 1.5), transform: `translateY(${(1 - ps) * 16}px)` });
    };
  };

  // ======================================================== quote (উক্তি)
  B.quote = (sc, L) => {
    const z = zoneOf("quote");
    const ts = G.ts;
    const top = G.wide ? 130 : lk(60, 230);
    const qm = el("div", "abs serif", L.f, { top: top - 20 + "px", textAlign: "center", fontSize: (G.wide ? 230 : lk(150, 320)) * ts + "px", lineHeight: "1", color: GOLD, opacity: 0.9, height: "20px" });
    place(qm, z);
    qm.textContent = "\u201C";
    const txt = el("div", "bn abs", L.f, { top: top + (G.wide ? 150 : lk(96, 190)) * ts + "px", textAlign: "center", fontSize: (G.wide ? 58 : lk(50, 62)) * ts + "px", fontWeight: 700, lineHeight: "1.45", color: INK, padding: "0 " + (G.wide ? 14 : 80) + "px", boxSizing: "border-box" });
    place(txt, z);
    const words = (sc.text || "").split(/\s+/).filter(Boolean);
    const spans = words.map((w) => { const s = el("span", "", txt, { display: "inline-block", marginRight: "0.26em" }); s.textContent = w; return s; });
    const au = el("div", "abs", L.f, { textAlign: "center" });
    place(au, z);
    const ln = makeRule(au, 300);
    const an = el("div", isBn(sc.author) ? "bn" : "sans", au, { marginTop: "8px", fontSize: 38 * ts + "px", fontWeight: 600, color: TXT, letterSpacing: isBn(sc.author) ? "1px" : "4px" });
    an.textContent = sc.author || "";
    const ar = el("div", "bn", au, { fontSize: 30 * ts + "px", color: INK, opacity: 0.7, marginTop: "4px" });
    ar.textContent = sc.role || "";
    au.style.top = txt.offsetTop + txt.offsetHeight + 30 + "px";
    const per = Math.min(0.14, 1.7 / Math.max(1, words.length));
    return (t) => {
      const lt = t - sc.start;
      const pq = prog(lt, 0.1, dsp(0.8), E.outBack);
      css(qm, { opacity: clamp(pq * 2) * 0.9, transform: `scale(${lerp(0.6, 1, clamp(pq, 0, 1.1))})` });
      spans.forEach((s, i) => { const p = prog(lt, 0.4 + i * per, dsp(0.5), MOT.text); css(s, { opacity: clamp(p * 1.6), transform: `translateY(${(1 - p) * 20}px)` }); });
      const pa = prog(lt, 0.7 + words.length * per, 0.7);
      ln(pa);
      css(an, { opacity: clamp(pa * 1.5), transform: `translateY(${(1 - pa) * 14}px)` });
      ar.style.opacity = clamp(pa * 1.5) * 0.7;
    };
  };

  // ======================================================== steps (ধাপ / টাইমলাইন)
  function card(parent, css0) {
    const c = el("div", "card", parent, css0);
    return c;
  }
  B.steps = (sc, L) => {
    const ts = G.ts;
    const items = sc.items || [];
    const n = items.length;
    const h = header(L.f, sc, { y: G.wide ? G.hdr : lk(66, 215), size: 88 });
    const top = Math.max(h.bottom + 26, G.wide ? 300 : lk(300, 520));
    const back = svgRoot(L.b);
    const nodes = [];
    if (G.wide) {
      // আনুভূমিক ধাপ
      const colW = Math.min(420, (W - 200) / n);
      const x0 = W / 2 - (colW * n) / 2;
      const yLine = top + 120;
      const line = sv("line", { x1: x0 + colW / 2, y1: yLine, x2: x0 + colW * (n - 0.5), y2: yLine, stroke: GOLD, "stroke-width": 4, opacity: 0.5 }, back);
      const fill = sv("line", { x1: x0 + colW / 2, y1: yLine, x2: x0 + colW / 2, y2: yLine, stroke: GOLD, "stroke-width": 6 }, back);
      items.forEach((it, i) => {
        const cx = x0 + colW * (i + 0.5);
        const c = el("div", "abs stepnum", L.f, { left: cx - 56 + "px", top: yLine - 56 + "px", width: "112px", height: "112px", fontSize: 56 * ts + "px" });
        c.textContent = String(i + 1);
        const tx = el("div", "abs", L.f, { left: cx - colW / 2 + 10 + "px", top: yLine + 84 + "px", width: colW - 20 + "px", textAlign: "center" });
        const lb = el("div", isBn(it.label) ? "bn" : "sans", tx, { fontSize: 54 * ts + "px", fontWeight: 700, color: INK, lineHeight: 1.25 }); lb.textContent = it.label;
        const ds = el("div", "bn", tx, { fontSize: 38 * ts + "px", color: TXT, marginTop: "8px", fontWeight: 500, lineHeight: 1.35 }); ds.textContent = it.text || "";
        nodes.push({ c, tx, it, cx, yLine });
      });
      return (t) => {
        h(t, sc.start);
        const last = nodes.reduce((a, o) => (t >= o.it.t ? o.cx : a), x0 + colW / 2);
        fill.setAttribute("x2", lerp(parseFloat(fill.getAttribute("x2")), last, 1));
        nodes.forEach((o) => {
          const p = prog(t, o.it.t, dsp(0.65), MOT.pop);
          css(o.c, { opacity: clamp(p * 2), transform: `scale(${lerp(0.3, 1, clamp(p, 0, 1.15))})` });
          css(o.tx, { opacity: clamp(p * 1.6), transform: `translateY(${(1 - p) * 30}px)` });
        });
      };
    }
    // উল্লম্ব ধাপ
    const sz = lk(1, 1.15);
    const avail = G.cBot + lk(0, 20) - top;
    const pitch = Math.min(220, avail / Math.max(1, n));
    const x = lk(120, 150);
    const line = sv("line", { x1: x, y1: top + 44, x2: x, y2: top + pitch * (n - 1) + 44, stroke: GOLD, "stroke-width": 4, opacity: 0.45 }, back);
    const fillL = sv("line", { x1: x, y1: top + 44, x2: x, y2: top + 44, stroke: GOLD, "stroke-width": 6 }, back);
    items.forEach((it, i) => {
      const y = top + i * pitch;
      const c = el("div", "abs stepnum", L.f, { left: x - 44 * sz + "px", top: y + "px", width: 88 * sz + "px", height: 88 * sz + "px", fontSize: 44 * ts * sz + "px" });
      c.textContent = String(i + 1);
      const tx = el("div", "abs", L.f, { left: x + 76 + "px", top: y + "px", width: W - x - 76 - 50 + "px", height: 88 * sz + "px", display: "flex", flexDirection: "column", justifyContent: "center" });
      const lb = el("div", isBn(it.label) ? "bn" : "sans", tx, { fontSize: 46 * ts * sz + "px", fontWeight: 700, color: INK, lineHeight: 1.2, whiteSpace: "nowrap", transformOrigin: "0 50%" }); lb.textContent = it.label;
      const room = W - x - 76 - 50;
      if (lb.scrollWidth > room) lb.style.transform = `scale(${room / lb.scrollWidth})`;
      const ds = el("div", "bn", tx, { fontSize: 32 * ts * sz + "px", color: TXT, fontWeight: 500, lineHeight: 1.25, whiteSpace: "nowrap" }); ds.textContent = it.text || "";
      if (!it.text) ds.style.display = "none";
      nodes.push({ c, tx, it, y });
    });
    return (t) => {
      h(t, sc.start);
      let ly = top + 44;
      nodes.forEach((o) => {
        const p = prog(t, o.it.t, dsp(0.65), MOT.pop);
        if (t >= o.it.t) ly = Math.max(ly, o.y + 44);
        css(o.c, { opacity: clamp(p * 2), transform: `scale(${lerp(0.3, 1, clamp(p, 0, 1.15))})` });
        css(o.tx, { opacity: clamp(p * 1.6), transform: `translateX(${(1 - p) * 60}px)` });
      });
      fillL.setAttribute("y2", ly);
    };
  };

  // ======================================================== compare (তুলনা)
  B.compare = (sc, L) => {
    const ts = G.ts;
    const items = (sc.items || []).slice(0, 2);
    const h = header(L.f, sc, { y: G.wide ? G.hdr : lk(66, 215), size: 88 });
    const top = Math.max(h.bottom + 24, G.wide ? 300 : lk(290, 520));
    const bottom = G.cBot + (G.wide ? 30 : lk(20, 40));
    const gap = G.wide ? 130 : lk(70, 96);
    const pw = G.wide ? Math.min(760, (W - 260) / 2) : W - 150;
    const ph = G.wide ? bottom - top : (bottom - top - gap) / 2;
    const cols = [C.accent, C.accent2 === C.accent ? C.accentD : C.accent2];
    const cs = clamp(ph / 280, 0.62, 1);
    const panels = items.map((it, i) => {
      const left = G.wide ? W / 2 + (i ? gap / 2 : -gap / 2 - pw) : (W - pw) / 2;
      const topP = G.wide ? top : top + i * (ph + gap);
      const c = card(L.f, { left: left + "px", top: topP + "px", width: pw + "px", height: ph + "px" });
      c.style.borderColor = cols[i];
      const bar = el("div", "abs", c, { left: "0px", top: "0px", width: "100%", height: "10px", background: cols[i], borderRadius: "inherit" });
      bar.style.height = "10px";
      const inn = el("div", "", c, { position: "absolute", left: "0px", top: "0px", width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: "20px 28px", boxSizing: "border-box", gap: 8 * cs + "px" });
      const lb = el("div", "", inn); headingStyle(lb, it.label || "", (G.wide ? 64 : lk(52, 66)) * ts * cs, 4); lb.style.whiteSpace = "normal"; lb.style.lineHeight = "1.15";
      fitW(lb, pw - 70, parseFloat(lb.style.fontSize));
      let vv = null;
      if (it.value != null) { vv = el("div", "", inn, { fontFamily: isBn(String(it.value)) ? "var(--bn)" : "var(--serif)", fontWeight: RT.FN.dw, fontSize: (G.wide ? 86 : lk(64, 92)) * ts * cs + "px", color: cols[i] === C.accent2 && !RT.TH.dark ? cols[i] : C.accent, lineHeight: 1.05 }); vv.textContent = it.value; fitW(vv, pw - 70, parseFloat(vv.style.fontSize)); }
      const tx = el("div", "bn", inn, { fontSize: (G.wide ? 36 : lk(32, 38)) * ts * cs + "px", color: INK, opacity: 0.85, lineHeight: 1.35, fontWeight: 500, whiteSpace: "pre-line" }); tx.textContent = it.text || "";
      return { c, it, i };
    });
    const vs = el("div", "abs vsbadge", L.f, { left: W / 2 - 52 + "px", top: (G.wide ? top + ph / 2 - 52 : top + ph + gap / 2 - 52) + "px", width: "104px", height: "104px", fontSize: 40 + "px" });
    vs.textContent = "VS";
    return (t) => {
      h(t, sc.start);
      panels.forEach((o) => {
        const p = prog(t, o.it.t, dsp(0.75), MOT.pop);
        const dx = G.wide ? (o.i ? 120 : -120) : 0, dy = G.wide ? 0 : (o.i ? 120 : -120);
        css(o.c, { opacity: clamp(p * 2), transform: `translate(${dx * (1 - p)}px, ${dy * (1 - p)}px) scale(${lerp(0.9, 1, clamp(p, 0, 1.1))})` });
      });
      const pv = prog(t, (items[1] ? items[1].t : sc.start + 1.5) - 0.3, dsp(0.6), E.outBack);
      css(vs, { opacity: clamp(pv * 2), transform: `scale(${lerp(0.2, 1, clamp(pv, 0, 1.2))}) rotate(${(1 - clamp(pv)) * -90}deg)` });
    };
  };
})(window.RT);
