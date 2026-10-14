#!/usr/bin/env python3
"""একটা ফোল্ডার (অডিও + SRT + [ছবি] + config.json) থেকে MP4 ভিডিও বানায়।
একই ভিডিও যেকোনো রেশিও (9:16, 4:5, 3:4, 1:1, 4:3, 16:9), যেকোনো রেজোলিউশন (SD/HD/FHD/QHD/4K)
আর ২৪টা থিমের যেকোনোটিতে পাওয়া যায়।

ব্যবহার:
    python make_video.py .                                   # config.json-এর থিম, 9:16, FHD
    python make_video.py . --theme neon --ratio 16x9 --res 4k
    python make_video.py . --theme all --ratio social --res fhd,hd     # ২৪ থিম x ৪ রেশিও
    python make_video.py . --theme auto --seed 7              # প্রতিবার আলাদা থিম (seed বদলালে)
টেস্ট:
    python make_video.py . --still 2 --still 12 --theme midnight --ratio 1x1
    python make_video.py . --quick --limit 10                 # ছোট দ্রুত প্রিভিউ
"""
import argparse
import glob
import json
import math
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import align  # noqa: E402
import sfx  # noqa: E402

AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
THEMES = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))


# --------------------------------------------------------------------------- ফাইল খোঁজা
def discover(project, cfg):
    files = sorted(os.listdir(project))

    def pick(pred, key):
        if cfg.get(key):
            p = os.path.join(project, cfg[key])
            if not os.path.exists(p):
                sys.exit(f"config.json-এ '{key}' হিসেবে দেওয়া ফাইল পাওয়া যায়নি: {cfg[key]}")
            return p
        for f in files:
            if pred(f.lower()):
                return os.path.join(project, f)
        return None

    is_bgm = lambda f: f.startswith(("bgm", "music", "background"))
    is_logo = lambda f: f.startswith("logo")
    audio = pick(lambda f: f.endswith(AUDIO_EXT) and not is_bgm(f), "audio")
    bgm = pick(lambda f: f.endswith(AUDIO_EXT) and is_bgm(f), "bgm")
    logo = pick(lambda f: f.endswith(IMG_EXT) and is_logo(f), "logo")
    # ছবি: config-এ "images": [...] থাকলে সেগুলো, নাহলে প্রথম ছবি। ছবি না থাকলেও চলবে (থিমের প্রতীক বসবে)।
    images = []
    if cfg.get("images"):
        for n in cfg["images"]:
            p = os.path.join(project, n)
            if not os.path.exists(p):
                sys.exit(f"config.json-এর images-এ দেওয়া ফাইল পাওয়া যায়নি: {n}")
            images.append(p)
    else:
        one = pick(lambda f: f.endswith(IMG_EXT) and not is_logo(f), "image")
        if one:
            images.append(one)
    if cfg.get("noImage"):
        images = []
    srt = pick(lambda f: f.endswith(".srt"), "srt")
    if not srt:  # .txt ফাইলেও SRT থাকতে পারে
        for f in files:
            if f.lower().endswith(".txt") and "-->" in open(os.path.join(project, f), encoding="utf-8-sig").read():
                srt = os.path.join(project, f)
    if not (audio and srt):
        sys.exit(
            "ফোল্ডারে অডিও (.mp3/.wav) আর সাবটাইটেল (.srt) লাগবে। (ছবি ঐচ্ছিক)\n"
            f"পাওয়া গেছে: audio={audio} srt={srt}"
        )
    return audio, srt, images, bgm, logo


# --------------------------------------------------------------------------- টাইমলাইন
def find_text(parts, text, from_part=0, from_char=0):
    """parts-এর মধ্যে text খুঁজে সময় বের করে (অংশের ভেতরে উচ্চারণ-অনুপাতে)।"""
    for pi in range(from_part, len(parts)):
        p = parts[pi]
        start_c = from_char if pi == from_part else 0
        idx = p["text"].find(text, start_c)
        if idx >= 0:
            before = align.syllables(p["text"][:idx]) if idx > 0 else 0
            tot = max(1, align.syllables(p["text"]))
            frac = min(0.95, before / tot) if idx > 0 else 0.0
            return p["start"] + (p["end"] - p["start"]) * frac, pi, idx + len(text)
    return None


def resolve_start(marker, parts, default=None):
    if isinstance(marker, (int, float)):
        return float(marker)
    if isinstance(marker, dict):
        if "cue" in marker:
            for p in parts:
                if p["cue"] == marker["cue"]:
                    return p["start"]
        if "text" in marker:
            r = find_text(parts, marker["text"])
            if r:
                return r[0]
        if "seconds" in marker:
            return float(marker["seconds"])
    return default


TYPE_ALIAS = {"list": "occasions", "bullets": "occasions", "ring": "family", "radial": "family", "fusion": "blend",
              "news": "headline", "number": "stat", "timeline": "steps", "versus": "compare", "vs": "compare"}


def build_timeline(cfg, parts, captions, audio_dur):
    tail = float(cfg.get("endHold", 1.4))
    total = audio_dur + tail
    scenes = [dict(s) for s in cfg["scenes"]]
    for s in scenes:
        s["type"] = TYPE_ALIAS.get(s.get("type"), s.get("type"))
    for i, s in enumerate(scenes):
        if i == 0:
            s["start"] = 0.0
            continue
        t = resolve_start(s.get("start"), parts)
        if t is None:
            sys.exit(f"সিন #{i + 1} ({s.get('type')}) এর শুরুর জায়গা খুঁজে পাওয়া যায়নি: {s.get('start')}")
        s["start"] = max(0.0, t - float(cfg.get("sceneLead", 0.12)))
    for i, s in enumerate(scenes):
        s["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else total
        if s["end"] <= s["start"] + 0.5:
            sys.exit(f"সিন #{i + 1} ({s['type']}) খুব ছোট বা ক্রম ঠিক নেই। config.json-এর start মার্কারগুলো ক্রমানুসারে দিন।")

    for s in scenes:
        rng = [p for p in parts if s["start"] - 0.3 <= p["start"] < s["end"] - 0.05]
        first = parts.index(rng[0]) if rng else 0
        cur = (first, 0)
        items = []
        raw_items = s.get("items", [])
        for k, it in enumerate(raw_items):
            it = {"label": it} if isinstance(it, str) else dict(it)
            key = it.get("say") or it.get("bn")   # কথায় যে শব্দ বলা হয় (সময় খুঁজতে)
            t = None
            if key:
                r = find_text(parts, key, cur[0], cur[1])
                if r and r[0] < s["end"] - 0.1:
                    t, cur = r[0], (r[1], r[2])
            if t is None:  # না পেলে সিনের ভেতরে সমান দূরত্বে
                lead = 0.9
                n = len(raw_items)
                t = s["start"] + lead + (s["end"] - s["start"] - lead - 0.9) * (k / max(1, n))
            it["t"] = round(max(s["start"] + 0.35, t - 0.08), 3)
            items.append(it)
        if items:
            for k in range(1, len(items)):
                items[k]["t"] = max(items[k]["t"], items[k - 1]["t"] + 0.3)
            s["items"] = items
        s["times"] = {}
        for key, val in list(s.items()):
            if key.endswith("At") and isinstance(val, dict):
                r = find_text(parts, val.get("text", ""), first, 0) if val.get("text") else None
                s["times"][key[:-2]] = round(max(s["start"] + 0.3, (r[0] if r else s["start"] + 1.0) - 0.05), 3)
                del s[key]
        # stat/title: revealAt না দিলে সিনের শুরুর একটু পরে
        if s["type"] in ("stat", "title") and "reveal" not in s["times"]:
            s["times"]["reveal"] = round(s["start"] + 1.0, 3)
    return {"duration": round(total, 3), "audioDuration": round(audio_dur, 3), "scenes": scenes}


# --------------------------------------------------------------------------- থিম / রেশিও / রেজোলিউশন নির্বাচন
def _split(spec):
    if spec is None:
        return []
    if isinstance(spec, (list, tuple)):
        return [str(x).strip().lower() for x in spec if str(x).strip()]
    return [x.strip().lower() for x in re.split(r"[,\s]+", str(spec)) if x.strip()]


def resolve_themes(spec, cfg, seed):
    order = THEMES["order"]
    if not spec or spec == "config":
        t = cfg.get("theme")
        if isinstance(t, dict):
            spec = t.get("id") or "royal"
        else:
            spec = t or "royal"
    out = []
    for tok in _split(spec):
        if tok == "all":
            out += order
        elif tok == "auto":
            out.append(order[(seed if seed is not None else int(time.time() // 86400)) % len(order)])
        elif tok in THEMES["themes"]:
            out.append(tok)
        else:
            sys.exit(f"অজানা থিম: {tok}। থিম: {', '.join(order)}, auto, all")
    return list(dict.fromkeys(out)) or ["royal"]


def resolve_ratios(spec, cfg):
    if spec is not None and str(spec).strip().lower() == "config":
        spec = None
    spec = spec or cfg.get("ratios") or cfg.get("ratio") or "9x16"
    out = []
    for tok in _split(spec):
        tok = tok.replace(":", "x").replace("*", "x")
        if tok in THEMES["groups"]:
            out += THEMES["groups"][tok]
        elif tok in THEMES["ratios"]:
            out.append(tok)
        else:
            sys.exit(f"অজানা রেশিও: {tok}। রেশিও: {', '.join(THEMES['ratios'])}, portrait, landscape, social, all")
    return list(dict.fromkeys(out))


def resolve_res(spec, cfg):
    if spec is not None and str(spec).strip().lower() == "config":
        spec = None
    spec = spec or cfg.get("resolutions") or cfg.get("resolution") or "fhd"
    out = []
    for tok in _split(spec):
        if tok == "all":
            out += ["hd", "fhd", "4k"]
        elif tok in ("1080p", "1080"):
            out.append("fhd")
        elif tok in ("720p", "720"):
            out.append("hd")
        elif tok in ("2160p", "uhd"):
            out.append("4k")
        elif tok in THEMES["resolutions"]:
            out.append(tok)
        else:
            sys.exit(f"অজানা রেজোলিউশন: {tok}। বিকল্প: {', '.join(THEMES['resolutions'])}, all")
    return list(dict.fromkeys(out))


def theme_payload(tid, cfg):
    th = json.loads(json.dumps(THEMES["themes"][tid]))
    th["id"] = tid
    over = cfg.get("theme") if isinstance(cfg.get("theme"), dict) else {}
    over = dict(over, **(cfg.get("themeColors") or {}))
    for k, v in over.items():
        if k in th["c"]:
            th["c"][k] = v
        elif k == "gold":  # পুরনো config-এর সাথে মিল
            th["c"]["accent"] = v
    return th


def font_links(th):
    out = ['<link rel="preconnect" href="https://fonts.googleapis.com">', '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>']
    for fam in th["font"]["gf"]:   # প্রতিটি ফন্টের আলাদা লিংক, যাতে একটা ব্যর্থ হলেও বাকিগুলো কাজ করে
        out.append(f'<link href="https://fonts.googleapis.com/css2?family={fam}&display=block" rel="stylesheet">')
    return "\n".join(out)


# --------------------------------------------------------------------------- ছবি প্রস্তুত
def prep_image(src, dst):
    """ছবির ধরন বুঝে সংরক্ষণ করে। ফেরত: (kind, w, h)
    kind = alpha (স্বচ্ছ PNG) | white (সাদা/হালকা ব্যাকগ্রাউন্ডের প্রোডাক্ট) | photo (সাধারণ ছবি)।"""
    import numpy as np
    from PIL import Image

    im0 = Image.open(src)
    has_alpha = im0.mode in ("RGBA", "LA") or (im0.mode == "P" and "transparency" in im0.info)
    im = im0.convert("RGBA") if has_alpha else im0.convert("RGB")
    w, h = im.size
    if has_alpha:
        a = np.asarray(im.split()[-1])
        if (a < 250).mean() > 0.03:
            im.save(dst)
            return "alpha", w, h
        im = im.convert("RGB")
    arr = np.asarray(im).astype("float32")
    b = max(4, min(h, w) // 100)
    ring = np.concatenate([arr[:b].reshape(-1, 3), arr[-b:].reshape(-1, 3), arr[:, :b].reshape(-1, 3), arr[:, -b:].reshape(-1, 3)])
    if ring.std(axis=0).mean() < 14 and np.percentile(ring, 8, axis=0).min() > 150:
        wp = np.clip(np.percentile(ring, 8, axis=0), 190, 255)
        out = np.clip(arr * (255.0 / wp), 0, 255).astype("uint8")
        Image.fromarray(out).save(dst)
        return "white", w, h
    # সাধারণ ছবি: বড় হলে ছোট করে নিই (ভিডিওতে ১২০০px-ই যথেষ্ট)
    if max(w, h) > 1800:
        r = 1800 / max(w, h)
        im = im.resize((int(w * r), int(h * r)), Image.LANCZOS)
    im.convert("RGB").save(dst)
    return "photo", im.size[0], im.size[1]


# --------------------------------------------------------------------------- রেন্ডার
def _launch(pw):
    return pw.chromium.launch(
        executable_path=os.environ.get("CHROME_PATH") or None,
        args=["--no-sandbox", "--font-render-hinting=none", "--disable-gpu-vsync", "--hide-scrollbars"],
    )


def _worker(args):
    (wid, frames, fps, scale, site_html, data_json, outdir, W, H, fmt, quality) = args
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = _launch(pw)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=scale)
        page = ctx.new_page()
        page.add_init_script(f"window.DATA = {data_json};")
        page.goto("file://" + site_html)
        page.wait_for_function("window.__ready === true", timeout=90000)
        done = 0
        for fr in frames:
            page.evaluate("t => window.renderFrame(t)", fr / fps)
            path = os.path.join(outdir, f"{fr:06d}.{fmt}")
            if fmt == "jpg":
                page.screenshot(path=path, type="jpeg", quality=quality)
            else:
                page.screenshot(path=path, type="png")
            done += 1
            if wid == 0 and done % 60 == 0:
                print(f"  ... {done}/{len(frames)} (worker 0)", flush=True)
        browser.close()


def render_stills(times, site_html, data_json, outdir, scale, W, H, tag):
    from playwright.sync_api import sync_playwright

    os.makedirs(outdir, exist_ok=True)
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=scale).new_page()
        page.add_init_script(f"window.DATA = {data_json};")
        page.goto("file://" + site_html)
        page.wait_for_function("window.__ready === true", timeout=90000)
        for t in times:
            page.evaluate("t => window.renderFrame(t)", t)
            p = os.path.join(outdir, f"still_{tag}_{t:07.2f}.png")
            page.screenshot(path=p, type="png")
            print("  ->", p)
        browser.close()


def mix_audio(voice, sfx_wav, bgm, duration, bgm_vol, out_wav):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice, "-i", sfx_wav]
    fmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
    split = "asplit=2[v1][v2]" if bgm else "anull[v1]"
    fc = [f"[0:a]{fmt},apad,atrim=0:{duration},{split}", f"[1:a]{fmt},volume=0.5[sx]"]
    labels = "[v1][sx]"
    n = 2
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", bgm]
        fc.append(
            f"[2:a]{fmt},atrim=0:{duration},afade=t=in:d=1.5,afade=t=out:st={max(0, duration - 2.5)}:d=2.5,volume={bgm_vol}[b0]"
        )
        fc.append("[b0][v2]sidechaincompress=threshold=0.03:ratio=9:attack=25:release=450[bg]")
        labels += "[bg]"
        n = 3
    fc.append(f"{labels}amix=inputs={n}:normalize=0:duration=longest,loudnorm=I=-15:TP=-1.5:LRA=11[out]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[out]", "-t", str(duration), "-ar", "44100", out_wav]
    subprocess.run(cmd, check=True)


def even(x):
    x = int(round(x))
    return x if x % 2 == 0 else x + 1


def out_size(ratio, res):
    r = THEMES["ratios"][ratio]
    k = THEMES["resolutions"][res] / 1080.0
    return even(r["w"] * k), even(r["h"] * k)


def default_config(cfg, cues):
    """config-এ scenes না থাকলে SRT-এর প্রতিটি লাইন একটা সিন হবে।"""
    sc = [{"type": "intro"}]
    for c in cues[1:-1]:
        sc.append({"type": "statement", "start": {"cue": c["i"]}, "text": c["text"]})
    if len(cues) > 1:
        sc.append({"type": "cta", "start": {"cue": cues[-1]["i"]}, "headline": "Order Now", "line": "Available on our website"})
    cfg["scenes"] = sc
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--out", default=None, help="আউটপুট ফোল্ডার (বা একটাই ভিডিও হলে .mp4 ফাইলের পথ)")
    ap.add_argument("--theme", default=None, help="থিম: নাম | কমা-ভাগ | auto | all | config (ডিফল্ট: config.json-এর theme)")
    ap.add_argument("--ratio", default=None, help="9x16,4x5,3x4,1x1,4x3,16x9 | portrait | landscape | social | all")
    ap.add_argument("--res", default=None, help="sd,hd,fhd,qhd,4k | all (ডিফল্ট fhd)")
    ap.add_argument("--seed", type=int, default=None, help="--theme auto-এর জন্য ঘূর্ণন নম্বর")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--scale", type=float, default=None, help="(পুরনো) 0.5 = দ্রুত প্রিভিউ")
    ap.add_argument("--quick", action="store_true", help="দ্রুত ছোট প্রিভিউ (SD, কম মান)")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2))))
    ap.add_argument("--limit", type=float, default=None, help="শুধু প্রথম N সেকেন্ড")
    ap.add_argument("--still", type=float, action="append", help="শুধু এই সময়ের স্টিল ছবি")
    ap.add_argument("--plan", action="store_true", help="(GitHub Actions) থিম x রেশিওর তালিকা JSON আকারে ছাপে")
    ap.add_argument("--build", default="build")
    ap.add_argument("--preset", default="medium")
    a = ap.parse_args()
    if a.scale and a.scale < 1:
        a.quick = True

    project = os.path.abspath(a.project)
    name = os.path.basename(project.rstrip("/")) or "video"
    if name in (".", ""):
        name = "video"
    cfg_path = os.path.join(project, "config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    # আউটপুট ফাইলের নাম: outputName > productName (ইংরেজি হলে) > ফোল্ডারের নাম
    slug = re.sub(r"[^A-Za-z0-9]+", "_", str(cfg.get("outputName") or cfg.get("productName") or "")).strip("_")
    if slug:
        name = slug

    themes = resolve_themes(a.theme, cfg, a.seed)
    ratios = resolve_ratios(a.ratio, cfg)
    ress = ["sd"] if a.quick else resolve_res(a.res, cfg)
    if a.plan:
        print(json.dumps({"include": [{"theme": t, "ratio": r} for t in themes for r in ratios]}, ensure_ascii=False))
        return

    audio, srt, images, bgm, logo = discover(project, cfg)
    print(f"অডিও: {os.path.basename(audio)} | SRT: {os.path.basename(srt)} | ছবি: {', '.join(os.path.basename(i) for i in images) or '- (থিমের প্রতীক বসবে)'} | bgm: {os.path.basename(bgm) if bgm else '-'}")
    print(f"থিম: {', '.join(themes)} | রেশিও: {', '.join(ratios)} | রেজোলিউশন: {', '.join(ress)}")

    build = os.path.abspath(os.path.join(a.build, name))
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)

    D = align.audio_duration(audio)
    cues = align.parse_srt(srt)
    if not cues:
        sys.exit("SRT ফাইল থেকে কোনো লাইন পড়া যায়নি।")
    parts = align.build_phrases(cues)
    sync = cfg.get("sync", "auto")
    if sync == "srt":
        parts = align.phrases_from_srt_times(parts, cues)
        print("সিঙ্ক: SRT-এর সময় ব্যবহার হচ্ছে")
    else:
        parts, info = align.align_phrases(parts, audio, D)
        print(f"সিঙ্ক: অডিও বিরতি দেখে মেলানো হয়েছে (অডিও {D:.1f}s, SRT শেষ {cues[-1]['end']:.1f}s, বিরতি {info['pauses']}টি)")
    off = float(cfg.get("syncOffset", 0.0))
    if off:
        for p in parts:
            p["start"] = min(max(0.0, p["start"] + off), D)
            p["end"] = min(max(p["start"] + 0.05, p["end"] + off), D)
    captions = align.merge_captions(parts)

    if "scenes" not in cfg:
        cfg = default_config(cfg, cues)
    tl = build_timeline(cfg, parts, captions, D)
    tl["captions"] = [{"text": c["text"], "start": round(c["start"], 3), "end": round(c["end"], 3)} for c in captions]
    tl["config"] = {k: cfg.get(k, d) for k, d in {
        "brand": "", "presenter": "", "productName": "", "productSubtitle": "", "website": "", "tagline": None, "welcome": None,
    }.items() if cfg.get(k, d) is not None}
    tl["fps"] = a.fps

    # ছবি প্রস্তুত (একবারই)
    prepped = []
    for i, src in enumerate(images):
        dst = os.path.join(build, f"hero{i}.png")
        kind, w, h = prep_image(src, dst)
        prepped.append({"src": f"hero{i}.png", "kind": kind, "w": w, "h": h, "name": os.path.basename(src)})
        print(f"ছবি {os.path.basename(src)}: ধরন = {kind}")
    logo_name = None
    if logo:
        from PIL import Image
        Image.open(logo).convert("RGBA").save(os.path.join(build, "logo.png"))
        logo_name = "logo.png"

    srt_out = os.path.join(build, "captions_synced.srt")
    with open(srt_out, "w", encoding="utf-8") as f:
        for n_, c in enumerate(tl["captions"], 1):
            f.write(f"{n_}\n{align.fmt_srt(c['start'])} --> {align.fmt_srt(c['end'])}\n{c['text']}\n\n")

    out_arg = a.out or "out"
    single_file = out_arg.lower().endswith(".mp4")
    outdir = os.path.dirname(os.path.abspath(out_arg)) if single_file else os.path.abspath(out_arg)
    os.makedirs(outdir, exist_ok=True)

    sfx_wav = os.path.join(build, "sfx.wav")
    mix = os.path.join(build, "mix.wav")
    total = tl["duration"] if a.limit is None else min(a.limit, tl["duration"])
    nframes = int(math.ceil(total * a.fps))
    made = []

    for tid in themes:
        th = theme_payload(tid, cfg)
        imode = cfg.get("imageMode", "auto")
        heroes = []
        for p in prepped:
            mode = imode
            if mode == "auto":
                mode = {"alpha": "cutout", "white": "spot" if th["dark"] else "blend", "photo": "card"}[p["kind"]]
            heroes.append({"src": p["src"], "mode": mode, "w": p["w"], "h": p["h"], "name": p["name"]})
        if not a.still:
            print(f"সাউন্ড ইফেক্ট বানানো হচ্ছে ({tid}) ...")
            sfx.build_sfx(tl, sfx_wav, th.get("sfx"))
            theme_bgm = os.path.join(build, f"bgm_{tid}.wav")
            if th.get("bgm"):
                sfx.build_theme_bgm(tl["duration"], theme_bgm, th.get("bgm"))
                selected_bgm = theme_bgm
            else:
                selected_bgm = bgm
            mix_audio(audio, sfx_wav, selected_bgm, tl["duration"], float(cfg.get("bgmVolume", 0.16)), mix)

        for ratio in ratios:
            R = THEMES["ratios"][ratio]
            W, H = R["w"], R["h"]
            site_dir = os.path.join(build, f"site_{tid}_{ratio}")
            shutil.copytree(os.path.join(HERE, "site"), site_dir)
            for p in prepped:
                shutil.copy(os.path.join(build, p["src"]), site_dir)
            if logo_name:
                shutil.copy(os.path.join(build, logo_name), site_dir)
            html_p = os.path.join(site_dir, "index.html")
            html = open(html_p, encoding="utf-8").read().replace("<!--FONTS-->", font_links(th))
            open(html_p, "w", encoding="utf-8").write(html)
            data = dict(tl, W=W, H=H, theme=th, heroes=heroes, logo=logo_name, ratio=ratio)
            data_json = json.dumps(data, ensure_ascii=False)
            if a.still:
                render_stills(a.still, html_p, data_json, os.path.join(build, "stills"), 1.0, W, H, f"{tid}_{ratio}")
                continue

            maxres = max(THEMES["resolutions"][r] for r in ress)
            rscale = 2.0 if maxres >= 1440 else (1.0 if maxres >= 720 else 0.5)
            frames_dir = os.path.join(build, f"frames_{tid}_{ratio}")
            os.makedirs(frames_dir)
            fmt, qual = ("jpg", 90 if rscale > 1 else 93)
            nw = max(1, a.workers)
            allf = list(range(nframes))
            chunks = [allf[i::nw] for i in range(nw)]
            print(f"[{tid} | {ratio}] {nframes} ফ্রেম রেন্ডার ({W * rscale:.0f}x{H * rscale:.0f}, {nw}টি প্রসেস) ...", flush=True)
            t0 = time.time()
            jobs = [(i, c, a.fps, rscale, html_p, data_json, frames_dir, W, H, fmt, qual) for i, c in enumerate(chunks) if c]
            with mp.get_context("spawn").Pool(len(jobs)) as pool:
                pool.map(_worker, jobs)
            print(f"  ফ্রেম শেষ ({time.time() - t0:.0f}s)। এনকোড হচ্ছে ({', '.join(ress)}) ...", flush=True)

            # একবার ফ্রেম পড়ে সব রেজোলিউশনে এনকোড
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(a.fps), "-i", os.path.join(frames_dir, f"%06d.{fmt}"), "-i", mix]
            n = len(ress)
            fc = [f"[0:v]format=yuv420p,split={n}" + "".join(f"[s{i}]" for i in range(n))]
            targets = []
            for i, rs in enumerate(ress):
                ow, oh = out_size(ratio, rs)
                same = abs(W * rscale - ow) < 1 and abs(H * rscale - oh) < 1
                fc.append(f"[s{i}]" + ("null" if same else f"scale={ow}:{oh}:flags=lanczos") + f"[o{i}]")
                if single_file and len(themes) * len(ratios) * len(ress) == 1:
                    path = os.path.abspath(out_arg)
                else:
                    path = os.path.join(outdir, f"{name}_{tid}_{ratio}_{rs}.mp4")
                targets.append((i, path, ow, oh))
            cmd += ["-filter_complex", ";".join(fc)]
            crf = "27" if a.quick else "18"
            pre = "veryfast" if a.quick else a.preset
            for i, path, ow, oh in targets:
                cmd += ["-map", f"[o{i}]", "-map", "1:a", "-c:v", "libx264", "-preset", pre, "-crf", crf, "-profile:v", "high",
                        "-level", "5.1" if ow > 2000 or oh > 2000 else "4.2", "-r", str(a.fps), "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", "-t", f"{nframes / a.fps:.3f}", path]
            subprocess.run(cmd, check=True)
            shutil.rmtree(frames_dir, ignore_errors=True)
            for i, path, ow, oh in targets:
                print(f"  তৈরি: {path} ({ow}x{oh}, {os.path.getsize(path) / 1e6:.1f} MB)", flush=True)
                made.append(path)
    if not a.still:
        sp = os.path.join(outdir, f"{name}_synced.srt")
        shutil.copy(srt_out, sp)
        print(f"অডিওর সাথে মেলানো SRT: {sp}")
        print(f"মোট {len(made)}টি ভিডিও তৈরি হয়েছে।")


if __name__ == "__main__":
    main()
