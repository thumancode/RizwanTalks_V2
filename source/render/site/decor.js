/* মোশন গ্রাফিক্স স্টেজ (ভাগ ২): থিমের সাজসজ্জা — ব্যাকগ্রাউন্ড প্যাটার্ন, ফ্রেম, কণা, ব্র্যান্ড বার। */
(function (RT) {
  const { W, H, C, S, G, CFG, el, sv, svgRoot, rng, css, clamp, lerp, prog, E, bgL, fx, chromeL, DPR, starPath, orn, ornPath,
    GOLD, GOLD_L, GOLD_D, INK, SUB, DC, LS, drawOn, pathLen } = RT;
  const rgba = (hex, a) => {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((x) => x + x).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  RT.rgba = rgba;
  const DIAG = Math.hypot(W, H);

  // ======================================================== ব্যাকগ্রাউন্ড
  RT.buildBackground = function () {
    const ups = [];
    const bgSvg = svgRoot(bgL);
    const defs = sv("defs", {}, bgSvg);
    let tid = 0;
    function tile(w, h, build, opacity, drift, extra) {
      const id = "pt" + tid++;
      const pat = sv("pattern", Object.assign({ id, width: w, height: h, patternUnits: "userSpaceOnUse" }, extra || {}), defs);
      build(pat);
      const rect = sv("rect", { x: -w, y: -h, width: W + 2 * w, height: H + 2 * h, fill: `url(#${id})`, opacity }, bgSvg);
      ups.push((t) => rect.setAttribute("transform", `translate(${(t * drift[0]) % w} ${(t * drift[1]) % h})`));
    }
    const P = S.pattern;
    if (P === "arabesque") {
      tile(120, 120, (pat) => {
        sv("path", { d: starPath(60, 60, 44, 31), fill: "none", stroke: GOLD, "stroke-width": 1.6, opacity: 0.55 }, pat);
        sv("rect", { x: 36, y: 36, width: 48, height: 48, fill: "none", stroke: GOLD, "stroke-width": 1.2, opacity: 0.35, transform: "rotate(45 60 60)" }, pat);
        sv("path", { d: "M0 0L26 26M120 0L94 26M0 120L26 94M120 120L94 94", stroke: GOLD, "stroke-width": 1.2, opacity: 0.4 }, pat);
        sv("circle", { cx: 60, cy: 60, r: 4, fill: GOLD, opacity: 0.5 }, pat);
      }, 0.2, [7, 4]);
    } else if (P === "grid") {
      tile(60, 60, (pat) => {
        sv("path", { d: "M60 0H0V60", fill: "none", stroke: GOLD, "stroke-width": 1, opacity: 0.45 }, pat);
      }, 0.16, [0, 10]);
      tile(300, 300, (pat) => {
        sv("path", { d: "M300 0H0V300", fill: "none", stroke: GOLD_L, "stroke-width": 2, opacity: 0.6 }, pat);
        sv("path", { d: "M-8 0H8M0 -8V8", stroke: GOLD_L, "stroke-width": 2.5, opacity: 0.9 }, pat);
      }, 0.2, [0, 10]);
      // দুই পাশে আলো
      const gl = el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: `radial-gradient(ellipse at 15% 20%, ${rgba(C.accent, 0.20)} 0%, transparent 45%), radial-gradient(ellipse at 90% 85%, ${rgba(C.accent2, 0.20)} 0%, transparent 48%)` });
    } else if (P === "topo") {
      const g = sv("g", { fill: "none", stroke: GOLD, "stroke-width": 2, opacity: 0.2 }, bgSvg);
      const cs = [[W * 0.18, H * 0.22, 1], [W * 0.86, H * 0.78, 2]];
      const grp = cs.map(([cx, cy, sd]) => {
        const gg = sv("g", {}, g);
        const r = rng(sd * 17);
        const p1 = r() * 6, p2 = r() * 6;
        for (let i = 0; i < 16; i++) {
          const base = 70 + i * 64;
          let d = "";
          for (let a = 0; a <= 96; a++) {
            const th = (a / 96) * Math.PI * 2;
            const rr = base * (1 + 0.14 * Math.sin(3 * th + p1 + i * 0.12) + 0.07 * Math.sin(5 * th + p2));
            d += (a ? "L" : "M") + (cx + rr * Math.cos(th)).toFixed(1) + " " + (cy + rr * Math.sin(th)).toFixed(1);
          }
          sv("path", { d: d + "Z" }, gg);
        }
        return { gg, cx, cy };
      });
      ups.push((t) => grp.forEach((o, i) => o.gg.setAttribute("transform", `rotate(${t * (i ? -1.4 : 1.4)} ${o.cx} ${o.cy})`)));
    } else if (P === "burst") {
      const d = el("div", "abs", bgL, { width: DIAG * 2 + "px", height: DIAG * 2 + "px", left: W / 2 - DIAG + "px", top: H * 0.4 - DIAG + "px", borderRadius: "50%",
        background: `repeating-conic-gradient(from 0deg, ${rgba(C.accent, 0.17)} 0deg 4.5deg, ${rgba(C.accent, 0)} 4.5deg 11deg)`,
        WebkitMaskImage: "radial-gradient(circle, #000 0%, #000 22%, transparent 52%)", maskImage: "radial-gradient(circle, #000 0%, #000 22%, transparent 52%)" });
      ups.push((t) => { d.style.transform = `rotate(${t * 2.2}deg)`; });
    } else if (P === "bokeh") {
      const r = rng(23);
      const bs = Array.from({ length: 15 }, () => ({ x: r() * W, y: r() * H, s: 180 + r() * 380, ph: r() * 6.28, sp: 0.15 + r() * 0.25, c: r() < 0.6 ? C.glow : "255,255,255", a: 0.22 + r() * 0.28 }));
      const ns = bs.map((b) => el("div", "abs", bgL, { width: b.s + "px", height: b.s + "px", borderRadius: "50%", background: `radial-gradient(circle, rgba(${b.c},${b.a}) 0%, rgba(${b.c},${b.a * 0.55}) 45%, rgba(${b.c},0) 70%)` }));
      ups.push((t) => bs.forEach((b, i) => { ns[i].style.left = b.x - b.s / 2 + 36 * Math.sin(t * b.sp + b.ph) + "px"; ns[i].style.top = b.y - b.s / 2 + 30 * Math.cos(t * b.sp * 0.8 + b.ph) + "px"; }));
    } else if (P === "waves") {
      tile(240, 70, (pat) => {
        sv("path", { d: "M0 35C40 5 80 5 120 35S200 65 240 35", fill: "none", stroke: GOLD, "stroke-width": 2.2, opacity: 0.5 }, pat);
      }, 0.22, [14, 0]);
      const wv = [0, 1].map((i) => sv("path", { fill: i ? rgba(C.accent, 0.14) : rgba(C.accentL, 0.30) }, bgSvg));
      ups.push((t) => wv.forEach((p, i) => {
        const base = H * (i ? 0.9 : 0.93), A = 26 + i * 12, f = (i ? 0.0042 : 0.0058), sp = i ? -0.8 : 1.1;
        let d = `M0 ${H}`;
        for (let x = 0; x <= W + 20; x += 20) d += `L${x} ${(base + A * Math.sin(x * f + t * sp + i * 2)).toFixed(1)}`;
        p.setAttribute("d", d + `L${W} ${H}Z`);
      }));
    } else if (P === "stripes") {
      const d = el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: `repeating-linear-gradient(-35deg, ${rgba(C.accent, 0.10)} 0px 26px, ${rgba(C.accent, 0)} 26px 92px)` });
      const v = el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: `radial-gradient(ellipse at 50% 45%, ${rgba(C.accent, 0.20)} 0%, transparent 55%)` });
      ups.push((t) => { d.style.backgroundPosition = `${(t * 26) % 92}px 0px`; });
    } else if (P === "scan") {
      el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: `radial-gradient(ellipse at 12% 18%, ${rgba(C.accent, 0.26)} 0%, transparent 42%), radial-gradient(ellipse at 92% 88%, ${rgba(C.accent2, 0.24)} 0%, transparent 46%)` });
      tile(80, 80, (pat) => { sv("path", { d: "M80 0H0V80", fill: "none", stroke: C.accent2, "stroke-width": 1, opacity: 0.5 }, pat); }, 0.10, [0, 16]);
      el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: "repeating-linear-gradient(0deg, rgba(255,255,255,0.045) 0px 2px, rgba(255,255,255,0) 2px 6px)" });
      const band = el("div", "abs", bgL, { left: "0px", width: W + "px", height: "260px", background: `linear-gradient(180deg, transparent, ${rgba(C.accent, 0.10)}, transparent)` });
      ups.push((t) => { band.style.top = ((t * 130) % (H + 520)) - 260 + "px"; });
    } else if (P === "dots") {
      const d = el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", backgroundImage: "radial-gradient(circle, rgba(0,0,0,0.22) 2.2px, transparent 2.8px)", backgroundSize: "34px 34px",
        WebkitMaskImage: "radial-gradient(ellipse at 50% 46%, transparent 12%, #000 90%)", maskImage: "radial-gradient(ellipse at 50% 46%, transparent 12%, #000 90%)" });
      ups.push((t) => { d.style.backgroundPosition = `${(t * 6) % 34}px ${(t * 3) % 34}px`; });
    } else if (P === "aurora") {
      const cols = [C.accent, C.accent2, C.accentL, "#7dd3fc"];
      const bl = cols.map((c, i) => el("div", "abs", bgL, { width: DIAG * 0.9 + "px", height: DIAG * 0.9 + "px", borderRadius: "50%", background: `radial-gradient(circle, ${rgba(c, 0.50)} 0%, ${rgba(c, 0.18)} 42%, ${rgba(c, 0)} 68%)` }));
      ups.push((t) => bl.forEach((b, i) => {
        const a = t * (0.12 + i * 0.05) + i * 1.7;
        b.style.left = W * (0.5 + 0.55 * Math.cos(a)) - DIAG * 0.45 + "px";
        b.style.top = H * (0.5 + 0.5 * Math.sin(a * 1.2)) - DIAG * 0.45 + "px";
      }));
    } else if (P === "deco") {
      tile(100, 100, (pat) => {
        const a = (cx, cy, r) => `M${cx - r} ${cy}A${r} ${r} 0 0 1 ${cx + r} ${cy}`;
        let d = "";
        [46, 34, 22, 10].forEach((r) => { d += a(50, 100, r) + a(0, 50, r) + a(100, 50, r); });
        sv("path", { d, fill: "none", stroke: GOLD, "stroke-width": 1.6, opacity: 0.55 }, pat);
      }, 0.24, [0, 7]);
      el("div", "abs", bgL, { left: "0px", top: "0px", width: W + "px", height: H + "px", background: `radial-gradient(ellipse at 50% 38%, ${rgba(C.accent, 0.14)} 0%, transparent 55%)` });
    } else if (P === "arcs") {
      const r = rng(41);
      const cols = [C.accent, C.accent2, C.accentL, C.accentD];
      const gs = Array.from({ length: 9 }, (_, i) => {
        const cx = r() * W, cy = r() * H, base = 50 + r() * 70, rot = Math.floor(r() * 4) * 90 + (r() - 0.5) * 30;
        const g = sv("g", { opacity: 0.2 }, bgSvg);
        for (let j = 0; j < 4; j++) {
          const rr = base + j * 20;
          sv("path", { d: `M${cx - rr} ${cy}A${rr} ${rr} 0 0 1 ${cx + rr} ${cy}`, fill: "none", stroke: cols[(i + j) % cols.length], "stroke-width": 11, "stroke-linecap": "round", transform: `rotate(${rot} ${cx} ${cy})` }, g);
        }
        return { g, cx, cy, rot, ph: r() * 6 };
      });
      ups.push((t) => gs.forEach((o) => o.g.setAttribute("transform", `rotate(${Math.sin(t * 0.25 + o.ph) * 4} ${o.cx} ${o.cy})`)));
    }
    // প্রান্ত অন্ধকার/হালকা (vignette)
    el("div", "layer", bgL, { background: `radial-gradient(ellipse at 50% 45%, rgba(${C.vig},0) 40%, rgba(${C.vig},${TH_DARK() ? 0.45 : 0.20}) 100%)` });
    RT.glowEl = el("div", "abs", bgL, { width: "1100px", height: "1100px", borderRadius: "50%", background: `radial-gradient(circle, rgba(${C.glow},${TH_DARK() ? 0.40 : 0.55}) 0%, rgba(${C.glow},0.16) 40%, rgba(${C.glow},0) 68%)` });
    return (t) => ups.forEach((f) => f(t));
  };
  function TH_DARK() { return RT.TH.dark; }

  // ======================================================== ফ্রেম
  RT.buildFrame = function () {
    const sv0 = svgRoot(chromeL);
    const ups = [];
    const kind = S.frame;
    const m = 30;
    const stroke = (p, w, c, o) => { p.setAttribute("fill", "none"); p.setAttribute("stroke", c || GOLD); p.setAttribute("stroke-width", w); if (o != null) p.setAttribute("opacity", o); return p; };
    if (kind === "ornate") {
      const fr1 = sv("rect", { x: m, y: m, width: W - 2 * m, height: H - 2 * m, rx: 6, fill: "none", stroke: GOLD, "stroke-width": 2.5, opacity: 0.8 }, sv0);
      const fr2 = sv("rect", { x: 46, y: 46, width: W - 92, height: H - 92, rx: 3, fill: "none", stroke: GOLD, "stroke-width": 1, opacity: 0.55 }, sv0);
      const cs = [[m, m], [W - m, m], [m, H - m], [W - m, H - m]].map(([x, y]) => {
        const g = sv("g", {}, sv0);
        sv("path", { d: orn(x, y, 24), fill: C.bg[0], stroke: GOLD, "stroke-width": 2.5 }, g);
        sv("circle", { cx: x, cy: y, r: 4.5, fill: GOLD }, g);
        return g;
      });
      const perim = 2 * (W - 60 + H - 60);
      fr1.setAttribute("stroke-dasharray", perim); fr2.setAttribute("stroke-dasharray", perim);
      ups.push((t) => { const fp = prog(t, 0.1, 1.6, E.inOutCubic); fr1.setAttribute("stroke-dashoffset", (1 - fp) * perim); fr2.setAttribute("stroke-dashoffset", (1 - fp) * perim); cs.forEach((c, i) => { c.style.opacity = prog(t, 0.9 + i * 0.1, 0.5); }); });
    } else if (kind === "double") {
      const fw = S.fw || 2.4;
      const a = stroke(sv("rect", { x: m, y: m, width: W - 2 * m, height: H - 2 * m, rx: 22 }, sv0), fw + 0.6, GOLD, 0.85);
      const b = stroke(sv("rect", { x: m + 16, y: m + 16, width: W - 2 * m - 32, height: H - 2 * m - 32, rx: 12 }, sv0), 1.2, GOLD_L, 0.7);
      const dd = [[m, m], [W - m, m], [m, H - m], [W - m, H - m]].map(([x, y]) => sv("path", { d: ornPath(S.orn, x, y, 13), fill: GOLD }, sv0));
      ups.push((t) => { const p = prog(t, 0.1, 1.6, E.inOutCubic); drawOn(a, p); drawOn(b, p); dd.forEach((n, i) => { n.style.opacity = prog(t, 0.9 + i * 0.1, 0.5); }); });
    } else if (kind === "brackets") {
      const L = 96, mm = 38;
      const d = [[mm, mm, 1, 1], [W - mm, mm, -1, 1], [mm, H - mm, 1, -1], [W - mm, H - mm, -1, -1]].map(([x, y, sx, sy]) => {
        const g = sv("g", {}, sv0);
        const p = stroke(sv("path", { d: `M${x} ${y + sy * L}V${y}H${x + sx * L}`, "stroke-linecap": "square" }, g), 5, GOLD, 1);
        sv("rect", { x: x + sx * 16 - 4, y: y + sy * 16 - 4, width: 8, height: 8, fill: C.accent2 }, g);
        return { g, p };
      });
      const rr = stroke(sv("rect", { x: mm, y: mm, width: W - 2 * mm, height: H - 2 * mm }, sv0), 1, GOLD, 0.22);
      ups.push((t) => { d.forEach((o, i) => { const p = prog(t, 0.1 + i * 0.12, 0.9, E.outCubic); drawOn(o.p, p, 2 * 96); o.g.style.opacity = clamp(p * 3); }); rr.setAttribute("opacity", 0.22 * prog(t, 0.6, 1.0)); });
    } else if (kind === "neon") {
      sv0.style.filter = `drop-shadow(0 0 9px ${C.accent}) drop-shadow(0 0 22px ${rgba(C.accent, 0.7)})`;
      const a = stroke(sv("rect", { x: 34, y: 34, width: W - 68, height: H - 68, rx: 30 }, sv0), 4, C.accent, 1);
      const b = stroke(sv("rect", { x: 56, y: 56, width: W - 112, height: H - 112, rx: 18 }, sv0), 2, C.accent2, 0.9);
      ups.push((t) => { const p = prog(t, 0.1, 1.5, E.inOutCubic); drawOn(a, p); drawOn(b, prog(t, 0.3, 1.5, E.inOutCubic)); const fl = 0.86 + 0.14 * Math.sin(t * 9) * Math.sin(t * 2.3); a.setAttribute("opacity", fl.toFixed(3)); });
    } else if (kind === "bar") {
      const bh = 20;
      const top = sv("rect", { x: 0, y: 0, width: W, height: bh, fill: C.accent }, sv0);
      const bot = sv("rect", { x: 0, y: H - bh, width: W, height: bh, fill: C.accent }, sv0);
      const tk = sv("path", { d: `M0 ${bh}H${W}`, stroke: C.accent2, "stroke-width": 4 }, sv0);
      const bk = sv("path", { d: `M0 ${H - bh}H${W}`, stroke: C.accent2, "stroke-width": 4 }, sv0);
      ups.push((t) => { const p = prog(t, 0.05, 0.9, E.outExpo); top.setAttribute("width", W * p); bot.setAttribute("x", W * (1 - p)); bot.setAttribute("width", W * p); tk.setAttribute("opacity", p); bk.setAttribute("opacity", p); });
    } else if (kind === "round") {
      const fw = S.fw || 6;
      const a = stroke(sv("rect", { x: 24 + fw / 2, y: 24 + fw / 2, width: W - 48 - fw, height: H - 48 - fw, rx: 54 }, sv0), fw, GOLD, 1);
      ups.push((t) => drawOn(a, prog(t, 0.1, 1.5, E.inOutCubic)));
    } else if (kind === "plain") {
      const a = stroke(sv("rect", { x: 40, y: 40, width: W - 80, height: H - 80 }, sv0), 2.5, INK, 0.9);
      const q = [[40, 40], [W - 40, 40], [40, H - 40], [W - 40, H - 40]].map(([x, y]) => sv("rect", { x: x - 8, y: y - 8, width: 16, height: 16, fill: C.accent2 }, sv0));
      ups.push((t) => { drawOn(a, prog(t, 0.1, 1.3, E.inOutCubic)); q.forEach((n, i) => { n.style.opacity = prog(t, 0.7 + i * 0.1, 0.4); }); });
    } else if (kind === "ticket") {
      const a = stroke(sv("rect", { x: 36, y: 36, width: W - 72, height: H - 72, rx: 44, "stroke-dasharray": "3 15", "stroke-linecap": "round" }, sv0), 4, GOLD, 0.85);
      ups.push((t) => { a.style.opacity = prog(t, 0.1, 1.0); a.setAttribute("stroke-dashoffset", -t * 8); });
    } else if (kind === "deco") {
      const c = 54;
      const poly = (i, d) => `M${i + c} ${i}H${W - i - c}L${W - i} ${i + c}V${H - i - c}L${W - i - c} ${H - i}H${i + c}L${i} ${H - i - c}V${i + c}Z`;
      const a = stroke(sv("path", { d: poly(30) }, sv0), 3, GOLD, 0.95);
      const b = stroke(sv("path", { d: poly(46) }, sv0), 1.2, GOLD_L, 0.7);
      const dd = [[30, 30], [W - 30, 30], [30, H - 30], [W - 30, H - 30]].map(([x, y]) => sv("path", { d: ornPath("diamond", x + (x < W / 2 ? 18 : -18), y + (y < H / 2 ? 18 : -18), 11), fill: GOLD }, sv0));
      ups.push((t) => { const p = prog(t, 0.1, 1.6, E.inOutCubic); drawOn(a, p); drawOn(b, p); dd.forEach((n, i) => { n.style.opacity = prog(t, 0.9 + i * 0.1, 0.5); }); });
    } else if (kind === "arch") {
      const mm = 34, r = Math.min((W - 2 * mm) / 2, 420);
      const d = `M${mm} ${H - mm}V${mm + r}A${(W - 2 * mm) / 2} ${r} 0 0 1 ${W - mm} ${mm + r}V${H - mm}Z`;
      const a = stroke(sv("path", { d }, sv0), 3, GOLD, 0.9);
      const d2 = `M${mm + 18} ${H - mm - 18}V${mm + r + 8}A${(W - 2 * mm - 36) / 2} ${r - 10} 0 0 1 ${W - mm - 18} ${mm + r + 8}V${H - mm - 18}Z`;
      const b = stroke(sv("path", { d: d2 }, sv0), 1.2, GOLD_L, 0.75);
      ups.push((t) => { const p = prog(t, 0.1, 1.7, E.inOutCubic); drawOn(a, p); drawOn(b, p); });
    }
    // উপরে প্রগ্রেস বার
    const progBar = el("div", "abs", chromeL, { left: "0px", top: kind === "bar" ? "20px" : "0px", height: kind === "bar" ? "8px" : "7px", width: "0px", background: kind === "bar" ? C.accent2 : `linear-gradient(90deg, ${GOLD_L}, ${GOLD}, ${GOLD_D})`, zIndex: 3 });
    return (t) => { ups.forEach((f) => f(t)); progBar.style.width = clamp(t / RT.D.duration) * W + "px"; };
  };

  // ======================================================== ব্র্যান্ড বার (নিচে)
  RT.buildBrand = function () {
    const pw = G.compact ? 1 : 1;
    const bar = el("div", "abs", chromeL, { left: "0px", top: G.brandY + "px", width: W + "px", textAlign: "center" });
    const row = el("div", "", bar, { display: "flex", alignItems: "center", justifyContent: "center", gap: G.compact ? "20px" : "22px" });
    const logo = RT.D.logo ? el("img", "", row, { height: (G.compact ? 44 : 60) + "px", width: "auto" }) : null;
    if (logo) logo.src = RT.D.logo;
    const fs = G.compact ? 30 : 40;
    const l1 = el("div", "", row, { height: "2px", width: (G.compact ? 70 : 110) + "px", background: `linear-gradient(90deg, transparent, ${GOLD})` });
    const txt = el("div", DC + " nowrap", row, { fontSize: fs + "px", letterSpacing: LS(G.compact ? 6 : 9), color: GOLD_D === GOLD ? INK : (RT.TH.dark ? C.sub : GOLD_D) });
    txt.textContent = CFG.brand || "";
    const l2 = el("div", "", row, { height: "2px", width: (G.compact ? 70 : 110) + "px", background: `linear-gradient(270deg, transparent, ${GOLD})` });
    const site = el("div", "sans nowrap", G.compact ? row : bar, { marginTop: G.compact ? "0px" : "10px", fontSize: (G.compact ? 24 : 28) + "px", letterSpacing: "4px", color: INK, opacity: 0.75 });
    site.textContent = CFG.website || "";
    if (G.compact && CFG.website && CFG.brand) { l2.style.display = "none"; }
    if (!CFG.brand) row.style.display = "none";
    if (!CFG.brand && CFG.website) { row.style.display = "flex"; l1.style.display = l2.style.display = "none"; txt.style.display = "none"; if (!G.compact) bar.insertBefore(site, row); site.style.opacity = 0.85; }
    return (t) => { const bp = prog(t, 0.8, 0.8); bar.style.opacity = bp; bar.style.transform = `translateY(${(1 - bp) * 14}px)`; };
  };

  // ======================================================== কণা (পার্টিকল)
  RT.buildParticles = function () {
    const kind = S.particles;
    if (kind === "none") return () => { fx.getContext("2d").clearRect(0, 0, fx.width, fx.height); };
    const ctx = fx.getContext("2d");
    const pr = rng(11);
    const cnt = { spark: 48, ember: 54, snow: 44, bubble: 26, square: 40, dot: 56 }[kind] || 40;
    const u = W / 1080;
    const pal = C.palette;
    const parts = Array.from({ length: cnt }, () => ({
      x: pr() * W, y: pr() * (H + 200), sp: (14 + pr() * 34) * (kind === "ember" ? 2.4 : kind === "snow" ? 0.9 : 1), r: (2 + pr() * 5) * u, ph: pr() * 6.28, tw: 0.8 + pr() * 1.8, c: pal[Math.floor(pr() * pal.length)],
    }));
    const down = kind === "snow";
    return (t) => {
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      ctx.clearRect(0, 0, W, H);
      for (const p of parts) {
        const span = H + 200;
        const travel = (down ? 1 : -1) * p.sp * t;
        const y = (((p.y + travel) % span) + span) % span - 100;
        const x = p.x + (kind === "ember" ? 40 : 28) * Math.sin(t * 0.55 + p.ph);
        const a = 0.25 + 0.55 * (0.5 + 0.5 * Math.sin(t * p.tw * 2 + p.ph));
        ctx.save();
        ctx.translate(x, y);
        if (kind === "spark") {
          ctx.globalAlpha = a * 0.8; ctx.fillStyle = p.r > 4 * u ? C.accentL : C.accent;
          const R = p.r * 1.6;
          ctx.beginPath(); ctx.moveTo(0, -R); ctx.quadraticCurveTo(R * 0.16, -R * 0.16, R, 0); ctx.quadraticCurveTo(R * 0.16, R * 0.16, 0, R); ctx.quadraticCurveTo(-R * 0.16, R * 0.16, -R, 0); ctx.quadraticCurveTo(-R * 0.16, -R * 0.16, 0, -R); ctx.fill();
        } else if (kind === "ember") {
          ctx.globalAlpha = a * 0.9; const g = ctx.createRadialGradient(0, 0, 0, 0, 0, p.r * 3.2); g.addColorStop(0, p.c); g.addColorStop(1, "rgba(0,0,0,0)");
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, p.r * 3.2, 0, 6.3); ctx.fill();
        } else if (kind === "snow") {
          ctx.globalAlpha = a * 0.7; ctx.fillStyle = RT.TH.dark ? "#ffffff" : C.accentL; ctx.beginPath(); ctx.arc(0, 0, p.r * 1.5, 0, 6.3); ctx.fill();
        } else if (kind === "bubble") {
          ctx.globalAlpha = a * 0.85; ctx.strokeStyle = p.c; ctx.lineWidth = 2 * u; ctx.beginPath(); ctx.arc(0, 0, p.r * 2.4, 0, 6.3); ctx.stroke();
          ctx.globalAlpha = a * 0.3; ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(-p.r * 0.8, -p.r * 0.8, p.r * 0.7, 0, 6.3); ctx.fill();
        } else if (kind === "square") {
          ctx.globalAlpha = a * 0.75; ctx.fillStyle = p.c; ctx.rotate(t * 0.5 + p.ph); const q = p.r * 1.3; ctx.fillRect(-q / 2, -q / 2, q, q);
        } else {
          ctx.globalAlpha = a * 0.8; ctx.fillStyle = p.c; ctx.beginPath(); ctx.arc(0, 0, p.r * 0.75, 0, 6.3); ctx.fill();
        }
        ctx.restore();
      }
    };
  };
})(window.RT);
