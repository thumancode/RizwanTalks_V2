/* মোশন গ্রাফিক্স স্টেজ (ভাগ ৪): হিরো নড়াচড়া, ক্যাপশন, মূল ফ্রেম, প্রস্তুতি। */
(function (RT) {
  const { D, CFG, W, H, G, C, S, el, css, clamp, lerp, prog, E, bgL, backL, frontL, capL, spotEl, heroEls, rgba, FN } = RT;
  const scenes = D.scenes;
  const lastIdx = scenes.length - 1;

  // কোন সিনে হিরো দেখাবে না
  const HIDE_ALWAYS = ["steps", "compare"];
  const HIDE_SMALL = ["stat", "quote", "headline"];
  RT.heroVisible = function (type) {
    if (!heroEls.length) return false;
    if (HIDE_ALWAYS.includes(type)) return false;
    if (HIDE_SMALL.includes(type) && !G.wide && H < 1400) return false;
    return true;
  };

  // সিনের ছবি (একাধিক ছবি থাকলে সিন অনুযায়ী বদলাবে; আগেরটাই চলতে থাকবে)
  let cur = 0;
  scenes.forEach((sc) => {
    if (sc.image != null && D.heroes) {
      const i = typeof sc.image === "number" ? sc.image : D.heroes.findIndex((h) => h.name === sc.image);
      if (i >= 0) cur = i;
    }
    sc._img = cur;
  });

  const states = scenes.map((s) => Object.assign({ vis: RT.heroVisible(s.type) ? 1 : 0, img: s._img }, G.heroState(s.type)));
  const dark = RT.TH.dark;
  if (S.spot && heroEls.length && heroEls[0].h.mode !== "card") {
    const tint = dark ? C.accentL : "#ffffff";
    spotEl.style.background = `radial-gradient(circle, rgba(255,255,255,0.97) 0%, ${rgba(tint, 0.55)} 38%, rgba(255,255,255,0.0) 70%)`;
  } else spotEl.style.display = "none";

  function heroAt(t) {
    let i = 0;
    for (let k = 0; k < scenes.length; k++) if (t >= scenes[k].start) i = k;
    const c = states[i], p = states[Math.max(0, i - 1)];
    const k = i === 0 ? 1 : E.inOutCubic(clamp((t - scenes[i].start) / 1.0));
    let x = lerp(p.x, c.x, k), y = lerp(p.y, c.y, k), s = lerp(p.s, c.s, k);
    const vis = lerp(p.vis, c.vis, k);
    const e = prog(t, 0.05, 1.5, E.outExpo);
    y += (1 - e) * 520 * (H / 1920 + 0.3); s *= lerp(0.72, 1, e);
    const o = clamp(t / 0.5) * vis;
    y += Math.sin(t * 1.5) * 9;
    const r = Math.sin(t * 0.9) * 0.9 + (1 - e) * -8;
    // কোন ছবি: সিন বদলের সময় ক্রসফেড
    const img = c.img, pimg = p.img;
    return { x, y, s, r, o, img, pimg, k };
  }

  // ---------- ক্যাপশন ----------
  const capEl = el("div", "cap", capL);
  css(capEl, {
    left: (W - G.capW) / 2 + "px", width: G.capW + "px",
    top: G.capTop + "px", height: G.capH + "px",
    fontSize: G.capFont + "px", lineHeight: G.wide ? "1.22" : "1.5",
    padding: G.wide ? "4px 8px" : "0 4px", overflow: "hidden"
  });
  const capTxt = el("div", "", capEl, {
    maxWidth: G.capW - 20 + "px", maxHeight: G.capH - 8 + "px",
    overflow: "hidden", overflowWrap: "anywhere"
  });
  const capLine = el("div", "abs", capL, { left: W / 2 - 110 + "px", top: G.capTop + G.capH + 10 + "px", width: "220px", height: "4px", borderRadius: "2px", background: rgba(C.accent, 0.25), overflow: "hidden" });
  const capFill = el("div", "", capLine, { height: "4px", width: "0px", background: `linear-gradient(90deg, ${C.accentL}, ${C.accent})` });
  const caps = D.captions;
  let lastCap = -2;
  function updateCaps(t) {
    let idx = -1;
    for (let i = 0; i < caps.length; i++) {
      const next = caps[i + 1] ? caps[i + 1].start : 1e9;
      const endShow = Math.min(caps[i].end + 0.3, next);
      if (t >= caps[i].start - 0.08 && t < endShow) { idx = i; break; }
    }
    if (idx !== lastCap) { capTxt.textContent = idx >= 0 ? caps[idx].text : ""; lastCap = idx; }
    if (idx < 0) { capEl.style.opacity = 0; capLine.style.opacity = 0; return; }
    const c = caps[idx];
    const next = caps[idx + 1] ? caps[idx + 1].start : 1e9;
    const endShow = Math.min(c.end + 0.3, next);
    const pin = prog(t, c.start - 0.08, 0.16);
    const pout = endShow < 1e8 && next - c.end < 0.4 ? 0 : clamp((endShow - t) / 0.18);
    capEl.style.opacity = Math.min(clamp(pin * 2.5), pout === 0 ? 1 : pout).toFixed(3);
    capTxt.style.transform = `translateY(${(1 - pin) * 26}px)`;
    capLine.style.opacity = 1;
    capFill.style.width = clamp((t - c.start) / Math.max(0.2, c.end - c.start)) * 220 + "px";
  }

  // ---------- সিন বসানো ----------
  const built = [];
  function buildAll() {
    scenes.forEach((sc) => {
      const f = el("div", "layer", frontL), b = el("div", "layer", backL);
      f.style.width = b.style.width = W + "px"; f.style.height = b.style.height = H + "px";
      const fn = (RT.B[sc.type] || RT.B.statement)(sc, { f, b });
      built.push({ sc, f, b, fn });
    });
  }
  let bgUp, frUp, paUp, brUp;
  window.renderFrame = function (t) {
    bgUp(t);
    const b = heroAt(t);
    const tf = `translate(${b.x - 500}px, ${b.y - 510}px) scale(${b.s.toFixed(4)}) rotate(${b.r.toFixed(3)}deg)`;
    css(spotEl, { left: "0px", top: "0px", width: "1000px", height: "1000px", opacity: S.spot ? b.o * 0.95 : 0, transform: tf });
    heroEls.forEach((h, i) => {
      let op = 1;
      if (heroEls.length > 1) op = b.img === i ? b.k : (b.pimg === i && b.pimg !== b.img ? 1 - b.k : (b.img === i ? 1 : 0));
      if (heroEls.length > 1 && b.img === b.pimg) op = b.img === i ? 1 : 0;
      css(h.wrap, { opacity: (b.o * op).toFixed(3), transform: tf });
    });
    if (RT.emblem) RT.emblem.rings.forEach((r, i) => r.setAttribute("transform", `rotate(${t * (i % 2 ? -6 : 6)} 500 500)`));
    if (RT.glowEl) css(RT.glowEl, { left: b.x - 550 + "px", top: b.y - 550 + "px", opacity: ((0.75 + 0.25 * Math.sin(t * 1.8)) * clamp(t / 0.8)).toFixed(3), transform: `scale(${(b.s * 0.9 + 0.35).toFixed(3)})` });
    frUp(t); brUp(t);
    built.forEach(({ sc, f, b: bk, fn }, i) => {
      const vis = t >= sc.start - 0.02 && t < sc.end + 0.02;
      f.style.display = bk.style.display = vis ? "block" : "none";
      if (!vis) return;
      const last = i === lastIdx;
      const ex = last ? 0 : E.inCubic(clamp((t - (sc.end - 0.38)) / 0.38));
      f.style.opacity = bk.style.opacity = (1 - ex).toFixed(3);
      f.style.transform = bk.style.transform = `translateY(${-24 * ex}px)`;
      fn(t);
    });
    updateCaps(t);
    paUp(t);
  };

  async function init() {
    try {
      const latin = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,-=:%$";
      const all = JSON.stringify(scenes) + (CFG.brand || "") + (CFG.productName || "") + latin;
      const bnText = D.captions.map((c) => c.text).join("") + (CFG.presenter || "") + "০১২৩৪৫৬৭৮৯" + all;
      const loads = [];
      [400, 500, 600, 700, 800].forEach((w) => {
        loads.push(document.fonts.load(`${w} 60px "${FN.display}"`, latin));
        loads.push(document.fonts.load(`${w} 40px "${FN.body}"`, latin));
        loads.push(document.fonts.load(`${w} 50px "${FN.bn}"`, bnText));
      });
      loads.push(document.fonts.load(`italic 600 60px "${FN.display}"`, latin));
      await Promise.race([Promise.all(loads).then(() => document.fonts.ready), new Promise((r) => setTimeout(r, 9000))]);
    } catch (e) {}
    await RT.heroImgsReady();
    for (const h of heroEls) { if (h.img) { try { await h.img.decode(); } catch (e) {} } }
    bgUp = RT.buildBackground(); frUp = RT.buildFrame(); paUp = RT.buildParticles(); brUp = RT.buildBrand();
    // লোগো প্রস্তুত
    if (D.logo) { const li = new Image(); li.src = D.logo; try { await li.decode(); } catch (e) {} }
    buildAll();
    window.renderFrame(0);
    window.__ready = true;
  }
  init();
})(window.RT);
