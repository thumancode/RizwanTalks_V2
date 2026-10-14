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
import os as _os

_ASSETS = {
    'align.py': r'''"""SRT পার্স করা + অডিওর বিরতি (pause) দেখে ক্যাপশনের টাইমিং অডিওর সাথে মেলানো।

কেন দরকার: SRT-এর টাইমিং অনেক সময় আনুমানিক হয় (যেমন ৬৭ সেকেন্ড), অথচ অডিও হয়তো ৬০ সেকেন্ডের।
এখানে আমরা অডিওতে কোথায় কোথায় থেমেছে সেটা ffmpeg দিয়ে বের করি, তারপর SRT-এর লেখাগুলোকে
ছোট ছোট ফ্রেজে ভেঙে সেই বিরতিগুলোর সাথে সবচেয়ে ভালোভাবে মিলিয়ে দিই।
"""
import math
import re
import subprocess


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def parse_srt(path):
    text = open(path, encoding="utf-8-sig").read().replace("\r", "")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, l in enumerate(lines):
            m = re.match(
                r"\s*(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", l
            )
            if m:
                g = [int(x) for x in m.groups()]
                s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                txt = " ".join(x.strip() for x in lines[i + 1:]).strip()
                cues.append({"i": len(cues) + 1, "start": s, "end": e, "text": txt})
                break
    return cues


def split_phrases(text, min_chars=22, max_chars=54):
    parts = [p.strip() for p in re.split(r"(?<=[।,:;!?—–])\s+", text) if p.strip()]
    chunks, cur = [], ""
    for p in parts:
        if cur and (len(cur) >= min_chars or len(cur) + 1 + len(p) > max_chars):
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        chunks.append(cur)

    def cut(c):
        if len(c) <= max_chars + 8 or " " not in c:
            return [c]
        mid = len(c) // 2
        best = min((i for i, ch in enumerate(c) if ch == " "), key=lambda i: abs(i - mid))
        return cut(c[:best].strip()) + cut(c[best:].strip())

    out = []
    for c in chunks:
        out += cut(c)
    return out


def detect_silences(audio, noise_db=-38, min_dur=0.12):
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", audio, "-af",
         f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    res = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        res.append((max(0.0, s), e))
    return res


def syllables(text):
    """বাংলা লেখার উচ্চারণ-একক (syllable) আনুমানিক গণনা। অক্ষর গোনার চেয়ে বক্তৃতার সময়ের কাছাকাছি হয়।"""
    t = re.sub(r"[^\u0980-\u09FF ]", "", text)
    n = 0
    for i, ch in enumerate(t):
        o = ord(ch)
        if 0x0985 <= o <= 0x0994 or 0x09BE <= o <= 0x09CC:
            n += 1  # স্বরবর্ণ / কার-চিহ্ন
        elif 0x0995 <= o <= 0x09B9 or o in (0x09DC, 0x09DD, 0x09DF):
            nxt = t[i + 1] if i + 1 < len(t) else " "
            if nxt == " ":
                continue  # শব্দের শেষের অন্তর্নিহিত স্বর প্রায়ই উচ্চারিত হয় না
            no = ord(nxt)
            if 0x09BE <= no <= 0x09CC or no == 0x09CD:
                continue
            n += 1
    if n == 0:  # ইংরেজি বা অন্য লেখা হলে অক্ষর দিয়ে আন্দাজ
        n = max(1, len(re.sub(r"\W", "", text)) // 3)
    return max(2, n)


def build_phrases(cues):
    """প্রতিটি যতিচিহ্নের (, । : —) জায়গায় ভেঙে ছোট ছোট অংশ বানায়।"""
    parts = []
    for c in cues:
        for p in re.split(r"(?<=[।,:;!?—–])\s+", c["text"]):
            if p.strip():
                parts.append({"text": p.strip(), "cue": c["i"], "chars": syllables(p)})
    return parts


def merge_captions(parts, min_chars=22, max_chars=54):
    """সময় বসানোর পর ছোট অংশগুলো জুড়ে পর্দায় দেখানোর মতো ক্যাপশন বানায়।"""
    caps, cur = [], None
    for p in parts:
        if cur and cur["cue"] == p["cue"] and len(cur["text"]) < min_chars and len(cur["text"]) + 1 + len(p["text"]) <= max_chars:
            cur["text"] += " " + p["text"]
            cur["end"] = p["end"]
        else:
            if cur:
                caps.append(cur)
            cur = dict(p)
    if cur:
        caps.append(cur)
    return caps


def detect_pauses(audio, thr_db=-34.0, smooth=5, min_dur=0.08):
    """ভলিউমের গ্রাফ (১০ মিলিসেকেন্ড ধাপে) দেখে বিরতি খোঁজে। ffmpeg-এর silencedetect-এর চেয়ে নির্ভরযোগ্য,
    কারণ ছোট ছোট ওঠানামা মসৃণ করে নেয়, তাই কমার ছোট বিরতিও ধরা পড়ে। ফেরত দেয় [(শুরু, শেষ), ...]।"""
    import numpy as np

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", audio, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    hop = 160
    n = len(x) // hop
    power = (x[: n * hop].reshape(n, hop) ** 2).mean(1)
    sm = np.convolve(power, np.ones(smooth) / smooth, mode="same")
    low = 10 * np.log10(sm + 1e-12) < thr_db
    out, i = [], 0
    while i < n:
        if low[i]:
            j = i
            while j < n and low[j]:
                j += 1
            if (j - i) * 0.01 >= min_dur or i == 0 or j == n:
                out.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return out


def _speech_edges(pauses, duration):
    """অডিওর শুরু ও শেষের নীরবতা বাদ দিয়ে আসল কথা কখন শুরু ও শেষ হয় বের করে।"""
    sp0, sp1 = 0.0, duration
    for s, e in pauses:
        if s <= 0.02:
            sp0 = e
        elif e >= duration - 0.03:
            sp1 = min(sp1, s)
    return sp0, max(sp0 + 1.0, sp1)


def _punct_kind(text):
    """ফ্রেজের শেষের যতিচিহ্ন দেখে বুঝি পরে কতটা বিরতি আশা করা যায়।"""
    t = text.rstrip().rstrip("\"'”’)")
    if t.endswith(("।", "?", "!", ".")):
        return "strong"
    if t.endswith(("—", "–", ":", ";")):
        return "mid"
    if t.endswith(","):
        return "weak"
    return "none"


def align_phrases(phrases, audio, duration):
    """প্রতিটি phrase-এর start/end বসায় (সেকেন্ডে)।

    পদ্ধতি: অডিওর প্রতিটি আসল বিরতি (pause) একটা সম্ভাব্য "কমা/দাঁড়ির জায়গা"। ডাইনামিক প্রোগ্রামিং দিয়ে
    এমনভাবে ফ্রেজ-সীমানা বসাই যাতে (১) দাঁড়ি (।) লম্বা বিরতিতে পড়ে, কমা ছোট বিরতিতে পড়ে,
    (২) প্রতিটি ফ্রেজের দৈর্ঘ্য তার উচ্চারণ-একক (syllable) সংখ্যার সাথে মানানসই থাকে।
    আগের পদ্ধতিতে ভুল বিরতিতে বসে গিয়ে ধাপে ধাপে দেরি জমত; এখানে প্রতিটি বড় বিরতি নিজে থেকে নোঙর (anchor) হয়।
    """
    import numpy as np

    P = len(phrases)
    allp = detect_pauses(audio)
    sp0, sp1 = _speech_edges(allp, duration)
    pauses = [(s, e) for s, e in allp if s > sp0 + 0.25 and e < sp1 - 0.25]

    # প্রার্থী সীমানা: আসল বিরতিগুলো + ০.১ সেকেন্ড পরপর "ফাঁকা" জায়গা (বিরতি না পেলে শেষ ভরসা)
    cand = [(s, e, e - s) for s, e in pauses]
    t = sp0 + 0.3
    while t < sp1 - 0.3:
        cand.append((t, t, 0.0))
        t += 0.1
    cand.sort(key=lambda c: (c[0], -c[2]))
    S = np.array([c[0] for c in cand])   # বিরতি শুরু (ফ্রেজ শেষ)
    E = np.array([c[1] for c in cand])   # বিরতি শেষ (পরের ফ্রেজ শুরু)
    L = np.array([c[2] for c in cand])
    C = len(cand)

    chars = np.array([p["chars"] for p in phrases], dtype=float)
    pref = np.concatenate([[0.0], np.cumsum(chars)])
    pause_total = float(sum(l for l in L if l > 0))
    rate = (sp1 - sp0 - pause_total * 0.6) / pref[-1]   # প্রতি syllable-এ গড় সেকেন্ড

    kinds = [_punct_kind(p["text"]) for p in phrases]

    def bcost(kind):
        # সীমানা-খরচ (প্রতিটি প্রার্থীর জন্য একটা ভেক্টর): বিরতি যত উপযুক্ত, খরচ তত কম
        if kind == "strong":
            c = 7.0 * np.clip(0.38 - L, 0, None) / 0.38
        elif kind == "mid":
            c = 5.0 * np.clip(0.28 - L, 0, None) / 0.28
        elif kind == "weak":
            c = 3.5 * np.clip(0.16 - L, 0, None) / 0.16
        else:
            c = 1.5 * np.clip(0.10 - L, 0, None) / 0.10
        return c - 0.8 * np.minimum(L, 0.6)   # বড় বিরতি সবসময় একটু বেশি পছন্দ

    INF = 1e12
    # dp[i][k] = i-তম ফ্রেজ k নম্বর প্রার্থীর আগে শেষ হলে সর্বনিম্ন মোট খরচ (i = 0..P-1)
    dp = np.full((P, C), INF)
    bk = np.zeros((P, C), dtype=int)

    def phrase_cost(i, start_arr, end_arr):
        dur = end_arr - start_arr
        exp = chars[i] * rate
        bad = dur <= 0.12
        c = chars[i] * (np.log((np.maximum(dur, 0.01) + 0.35) / (exp + 0.35))) ** 2
        return np.where(bad, INF, c)

    # প্রথম ফ্রেজ: শুরু = sp0
    dp[0] = phrase_cost(0, np.full(C, sp0), S) + (bcost(kinds[0]) if P > 1 else 0)
    for i in range(1, P):
        last = i == P - 1
        bc = np.zeros(C) if last else bcost(kinds[i])
        if last:
            # শেষ ফ্রেজের শেষ = sp1, শুরু = আগের সীমানার E
            pc = phrase_cost(i, E, np.full(C, sp1))
            tot = dp[i - 1] + pc
            k = int(np.argmin(tot))
            dp[i][k] = tot[k]
            bk[i][k] = k
            continue
        # M[a, b] = dp[i-1][a] + ফ্রেজ i-এর খরচ (শুরু E[a], শেষ S[b]), শুধু a < b
        dur = S[None, :] - E[:, None]
        exp = chars[i] * rate
        pcm = chars[i] * (np.log((np.maximum(dur, 0.01) + 0.35) / (exp + 0.35))) ** 2
        pcm = np.where(dur <= 0.12, INF, pcm)
        M = dp[i - 1][:, None] + pcm
        arg = np.argmin(M, axis=0)
        dp[i] = M[arg, np.arange(C)] + bc
        bk[i] = arg
    # শেষ ফ্রেজের জন্য সেরা প্রার্থী খুঁজে ব্যাকট্র্যাক
    if P == 1:
        bounds = []
    else:
        i = P - 1
        pc = phrase_cost(i, E, np.full(C, sp1))
        tot = dp[i - 1] + pc
        k = int(np.argmin(tot))
        bounds = [k]
        for i in range(P - 2, 0, -1):
            k = int(bk[i][k])
            bounds.append(k)
        bounds.reverse()   # bounds[j] = j-তম ফ্রেজের পরের সীমানা

    t0 = sp0
    for i, ph in enumerate(phrases):
        if i < len(bounds):
            k = bounds[i]
            ph["start"], ph["end"] = float(t0), float(S[k])
            t0 = float(E[k])
        else:
            ph["start"], ph["end"] = float(t0), float(sp1)
    used = sum(1 for k in bounds if L[k] > 0)
    return phrases, {"speech_start": sp0, "speech_end": sp1, "pauses": len(pauses), "used_pauses": used}


def fmt_srt(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def phrases_from_srt_times(phrases, cues):
    """sync = "srt" হলে: SRT-এর সময় যেমন আছে তেমন, cue-এর ভেতরে অক্ষরের অনুপাতে ভাগ।"""
    by_cue = {}
    for p in phrases:
        by_cue.setdefault(p["cue"], []).append(p)
    for c in cues:
        ps = by_cue.get(c["i"], [])
        tot = sum(p["chars"] for p in ps) or 1
        acc = 0
        for p in ps:
            p["start"] = c["start"] + (c["end"] - c["start"]) * acc / tot
            acc += p["chars"]
            p["end"] = c["start"] + (c["end"] - c["start"]) * acc / tot
    return phrases
''',
    'sfx.py': r'''"""সাউন্ড ইফেক্ট কোড দিয়ে বানানো হয় (কোনো ডাউনলোড বা কপিরাইট ঝামেলা নেই)।
hook, whoosh, pop, chime, impact, riser, click, shimmer: সব numpy দিয়ে সিন্থেসাইজ।
"""
import numpy as np
from scipy.signal import butter, lfilter
import wave
import math

SR = 44100
RNG = np.random.default_rng(7)


def _t(d):
    return np.arange(int(d * SR)) / SR


def _norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1.0
    return x / m * peak


def _fade(x, a=0.004, b=0.01):
    n = len(x)
    na, nb = int(a * SR), int(b * SR)
    x = x.copy()
    if na:
        x[:na] *= np.linspace(0, 1, na)
    if nb:
        x[-nb:] *= np.linspace(1, 0, nb)
    return x


def _bp_sweep(noise, f0, f1, q=1.2, block=512):
    """কেন্দ্র-ফ্রিকোয়েন্সি f0 থেকে f1 পর্যন্ত সরতে থাকা ব্যান্ডপাস ফিল্টার।"""
    out = np.zeros_like(noise)
    zi = None
    n = len(noise)
    for i in range(0, n, block):
        fc = f0 * (f1 / f0) ** (i / max(1, n))
        lo, hi = max(40, fc / (1 + 1 / q)), min(SR / 2 - 100, fc * (1 + 1 / q))
        b, a = butter(2, [lo / (SR / 2), hi / (SR / 2)], btype="band")
        if zi is None:
            zi = np.zeros(max(len(a), len(b)) - 1)
        else:
            zi = np.zeros(max(len(a), len(b)) - 1) if len(zi) != max(len(a), len(b)) - 1 else zi
        seg, zi = lfilter(b, a, noise[i:i + block], zi=zi)
        out[i:i + block] = seg
    return out


def whoosh(d=0.75, up=True):
    t = _t(d)
    noise = RNG.standard_normal(len(t))
    f0, f1 = (300, 5000) if up else (5000, 300)
    x = _bp_sweep(noise, f0, f1, q=1.1)
    env = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 2.2
    return _fade(_norm(x * env))


def impact(d=1.6):
    t = _t(d)
    f = 45 + 90 * np.exp(-t * 14)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 3.2)
    noise = lfilter(*butter(2, 1800 / (SR / 2)), RNG.standard_normal(len(t))) * np.exp(-t * 18)
    return _fade(_norm(body + 0.55 * noise))


def bell(freq=880, d=1.4, bright=1.0):
    t = _t(d)
    parts = [(1, 1.0, 3.0), (2.0, 0.45, 4.0), (2.76, 0.35, 5.0), (4.07, 0.18 * bright, 7.0), (5.4, 0.1 * bright, 9.0)]
    x = sum(a * np.sin(2 * np.pi * freq * m * t) * np.exp(-t * dec) for m, a, dec in parts)
    return _fade(_norm(x), 0.002, 0.02)


def pop(freq=520, d=0.16):
    t = _t(d)
    f = freq * (1 + 1.4 * np.exp(-t * 55))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 26)
    return _fade(_norm(x), 0.001, 0.01)


def click(d=0.05):
    t = _t(d)
    n = RNG.standard_normal(len(t))
    b, a = butter(2, 2500 / (SR / 2), btype="high")
    return _norm(lfilter(b, a, n) * np.exp(-t * 90))


def riser(d=2.0):
    t = _t(d)
    noise = RNG.standard_normal(len(t))
    x = _bp_sweep(noise, 250, 7000, q=0.9)
    tone = np.sin(2 * np.pi * np.cumsum(180 * (1 + 5 * (t / d) ** 2)) / SR) * 0.35
    env = (t / d) ** 1.8
    return _fade(_norm((x + tone) * env), 0.01, 0.03)


def shimmer(d=1.8, base=1568):
    t = _t(d)
    out = np.zeros(len(t))
    notes = [1, 1.25, 1.5, 2, 2.5, 3]
    for i, m in enumerate(notes):
        st = i * 0.09
        mask = (t >= st)
        tt = np.where(mask, t - st, 0)
        out += mask * np.sin(2 * np.pi * base * m * tt) * np.exp(-tt * 4.2) * (0.8 ** i)
    return _fade(_norm(out), 0.002, 0.05)


def hook(d=2.0):
    """ভিডিওর শুরুর hook: নিচু বুম + ঝিলমিল।"""
    n = int(d * SR)
    out = np.zeros(n)
    for sig, at, g in ((impact(1.6), 0.0, 0.75), (shimmer(1.8), 0.12, 0.35), (whoosh(0.8, up=False), 0.0, 0.4)):
        i = int(at * SR)
        seg = sig[: n - i] * g
        out[i:i + len(seg)] += seg
    return _norm(out, 0.9)


def chime_arp(base=659.3, steps=(1, 1.25, 1.5, 2.0), gap=0.11, d=2.2):
    n = int(d * SR)
    out = np.zeros(n)
    for i, m in enumerate(steps):
        b = bell(base * m, 1.6)
        s = int(i * gap * SR)
        seg = b[: n - s] * (0.9 ** i)
        out[s:s + len(seg)] += seg
    return _norm(out, 0.9)


class Track:
    def __init__(self, duration):
        self.n = int(duration * SR)
        self.L = np.zeros(self.n)
        self.R = np.zeros(self.n)

    def add(self, sig, t, gain=0.5, pan=0.0):
        i = int(max(0, t) * SR)
        if i >= self.n:
            return
        seg = sig[: self.n - i] * gain
        gl = np.cos((pan + 1) * np.pi / 4)
        gr = np.sin((pan + 1) * np.pi / 4)
        self.L[i:i + len(seg)] += seg * gl * 1.414
        self.R[i:i + len(seg)] += seg * gr * 1.414

    def save(self, path):
        data = np.stack([self.L, self.R], axis=1)
        peak = np.max(np.abs(data)) or 1
        if peak > 0.95:
            data = data / peak * 0.95
        pcm = (data * 32767).astype("<i2")
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())


PENTA = [1, 9 / 8, 5 / 4, 3 / 2, 5 / 3, 2]


def build_sfx(timeline, path, prof=None):
    """timeline-এর সিন ও আইটেম দেখে সাউন্ড বসায়। prof = থিমের সাউন্ড প্রোফাইল {pitch, bright, sub}।"""
    prof = prof or {}
    pt = float(prof.get("pitch", 1.0))      # সুরের উচ্চতা (থিম অনুযায়ী)
    sub = float(prof.get("sub", 1.0))       # নিচু বুম কতটা জোরালো
    tr = Track(timeline["duration"])
    W = {"whoosh": whoosh(0.75), "whoosh_down": whoosh(0.6, up=False), "impact": impact(),
         "riser": riser(2.2), "shimmer": shimmer(), "click": click()}
    tr.add(hook(), 0.0, 0.55)
    scenes = timeline["scenes"]
    for si, sc in enumerate(scenes):
        st, typ = sc["start"], sc["type"]
        if si > 0:
            tr.add(W["whoosh"], max(0, st - 0.35), 0.30)
        if typ == "title":
            rv = sc.get("times", {}).get("reveal", st + 1.0)
            tr.add(W["impact"], rv + 0.02, min(0.6, 0.40 * sub))
            tr.add(W["shimmer"], rv + 0.15, 0.22)
        elif typ == "blend":
            tr.add(W["riser"], max(0, st - 0.05), 0.30)
            tr.add(bell(523.3 * pt, 2.0), sc.get("times", {}).get("accords", st + 2.15), 0.28)
        elif typ == "cta":
            tr.add(chime_arp(659.3 * pt), st + 0.35, 0.40)
            tr.add(W["click"], st + 1.65, 0.45)
            tr.add(bell(1318.5 * pt, 1.6), st + 1.7, 0.2)
        elif typ == "headline":
            tr.add(W["impact"], st + 0.12, min(0.55, 0.32 * sub))
            tr.add(W["click"], st + 0.2, 0.3)
        elif typ == "stat":
            rv = sc.get("times", {}).get("reveal", st + 1.0)
            tr.add(W["riser"], max(0, rv - 0.2), 0.26)
            tr.add(W["impact"], rv + 1.6, min(0.6, 0.38 * sub))
            tr.add(bell(880 * pt, 1.6), rv + 1.65, 0.22)
        elif typ == "quote":
            tr.add(bell(587.3 * pt, 2.2), st + 0.2, 0.26)
        elif typ == "compare":
            tr.add(W["impact"], (sc.get("items") or [{"t": st + 1.5}])[-1]["t"], min(0.5, 0.3 * sub))
        elif typ == "intro":
            pass
        for k, it in enumerate(sc.get("items", [])):
            pan = -0.35 if k % 2 == 0 else 0.35
            if typ in ("notes", "traits", "occasions", "steps", "compare", "list", "bullets"):
                tr.add(pop(420 * pt * PENTA[k % len(PENTA)]), it["t"], 0.42, pan)
            elif typ == "family":
                tr.add(bell(523.3 * pt * PENTA[k % len(PENTA)], 1.2), it["t"], 0.30, (k - 2) * 0.25)
            elif typ == "character":
                tr.add(W["impact"][: int(0.7 * SR)] * np.linspace(1, 0, int(0.7 * SR)), it["t"], 0.16 * sub)
                tr.add(shimmer(1.2, 1318 * pt), it["t"] + 0.05, 0.10)
    tr.add(bell(1046.5 * pt, 2.2), timeline["duration"] - 1.5, 0.18)
    tr.save(path)


# 48 theme-specific procedural BGM beds. Each profile controls genre/timbre, mode,
# tempo, root, rhythm, brightness and seed; no two themes share a profile.
def build_theme_bgm(duration, path, profile=None):
    profile = profile or {}
    n = int(float(duration) * SR)
    if n <= 0: n = SR
    t = np.arange(n, dtype=np.float64) / SR
    seed = int(profile.get("seed", 1))
    rng = np.random.default_rng(seed)
    genre = str(profile.get("genre", "piano"))
    mode = str(profile.get("mode", "major"))
    tempo = float(profile.get("tempo", 90))
    root = float(profile.get("root", 130.81))
    bright = float(profile.get("brightness", .5))
    rhythm = str(profile.get("rhythm", "pulse"))
    scale_map = {
        "major": [0,2,4,5,7,9,11], "minor": [0,2,3,5,7,8,10],
        "dorian": [0,2,3,5,7,9,10], "pentatonic": [0,2,4,7,9],
        "lydian": [0,2,4,6,7,9,11], "mixolydian": [0,2,4,5,7,9,10]
    }
    scale = scale_map.get(mode, scale_map["major"])
    out = np.zeros(n, dtype=np.float64)
    beat = 60.0 / max(40, tempo)
    # genre-specific envelope/timbre: intentionally different sound families
    timbre = {
      "piano": (1,.34,.12,3.8), "marimba": (1,.22,.04,7.0), "analog_pad": (.65,.22,.28,1.8),
      "plucked": (1,.14,.03,5.5), "bell": (1,.38,.16,4.2), "strings": (.7,.32,.10,1.5),
      "guitar": (1,.22,.06,3.2), "mallet": (1,.28,.08,6.2), "synth_bass": (.6,.35,.04,2.2),
      "kalimba": (1,.35,.06,8.0), "organ": (.7,.28,.14,1.0), "choir_pad": (.5,.3,.2,1.2),
      "muted_guitar": (1,.12,.03,4.4), "harp": (1,.3,.07,3.6), "soft_brass": (.7,.32,.1,1.4),
      "glass_pad": (.7,.4,.22,2.5), "handpan": (1,.25,.05,3.8), "woodblock": (1,.08,.01,10.0),
      "rhodes": (.8,.3,.14,2.3), "celesta": (1,.4,.1,5.8), "qanun_like": (1,.3,.05,6.0),
      "flute_pad": (.55,.15,.18,1.1), "bass_pulse": (.5,.25,.03,2.0), "arp_synth": (.8,.4,.12,2.6)
    }
    attack, h2, h3, decay = timbre.get(genre, timbre["piano"])
    # soft low drone/pad, with different harmonic color per theme
    base_phase = rng.uniform(0, 2*np.pi)
    pad = (np.sin(2*np.pi*root*t + base_phase) + h2*np.sin(2*np.pi*root*1.5*t) + h3*np.sin(2*np.pi*root*2*t))
    pad_env = .5 + .5*np.sin(2*np.pi*t/max(4.0, beat*16) + base_phase)
    out += pad * pad_env * (0.045 + .035*bright)
    # Genre-dependent rhythmic motifs, with distinct note order and spacing
    step = beat * ({"drone":4,"pulse":1,"syncopated":.75,"arpeggio":.5,"waltz":2/3,"ostinato":.5}.get(rhythm,1))
    total_steps = int(math.ceil(float(duration)/step))
    note_order = list(range(len(scale)))
    rng.shuffle(note_order)
    for j in range(total_steps):
        at = j*step
        if at >= duration: break
        degree = note_order[j % len(note_order)]
        octave = 1 if (j//len(note_order))%2==0 else 2
        if rhythm == "drone": octave=1
        freq = root * (2 ** ((scale[degree] + 12*(octave-1))/12))
        length = min(float(duration)-at, max(.12, step*({"drone":1.7,"pulse":.7,"syncopated":.42,"arpeggio":.42,"waltz":.8,"ostinato":.36}.get(rhythm,.7))))
        count = int(length*SR)
        if count < 2: continue
        tt = np.arange(count)/SR
        env = np.exp(-tt*decay) if genre not in ("analog_pad","strings","choir_pad","glass_pad","flute_pad","organ") else np.minimum(1,tt*8)*np.exp(-tt*max(.45,decay*.45))
        phase = rng.uniform(0,2*np.pi)
        wave1 = np.sin(2*np.pi*freq*tt+phase)
        if genre in ("analog_pad","synth_bass","arp_synth"):
            wave1 = .65*wave1 + .2*np.sin(2*np.pi*freq*1.01*tt) + .15*np.sin(2*np.pi*freq*2*tt)
        elif genre in ("woodblock","handpan","marimba","kalimba","celesta","bell","mallet"):
            wave1 = wave1 + .35*np.sin(2*np.pi*freq*2.7*tt)*np.exp(-tt*8)
        seg = wave1*env*(.09 + .035*bright)
        start = int(at*SR); end = min(n,start+len(seg))
        out[start:end] += seg[:end-start]
    # Gentle filtered noise texture only for selected cinematic/ambient genres
    if genre in ("glass_pad","choir_pad","flute_pad","analog_pad","strings"):
        noise = rng.normal(0,1,n)
        smooth = np.convolve(noise, np.ones(256)/256, mode='same')
        out += smooth*(.012 + .01*bright)
    # fades and conservative peak to keep narration intelligible
    fade_n = min(int(1.8*SR), n//3)
    if fade_n:
        out[:fade_n] *= np.linspace(0,1,fade_n)
        out[-fade_n:] *= np.linspace(1,0,fade_n)
    peak = np.max(np.abs(out)) or 1
    out = out / peak * .24
    pcm = (out*32767).astype('<i2')
    import wave as _wave
    with _wave.open(path,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
''',
    'themes.json': r'''{
  "order": [
    "royal",
    "midnight",
    "emerald",
    "sunrise",
    "rose",
    "ocean",
    "crimson",
    "neon",
    "mono",
    "lavender",
    "luxe",
    "sand",
    "editorial",
    "cyberpunk",
    "forest",
    "blueprint",
    "candy",
    "volcanic",
    "arctic",
    "newspaper",
    "royalblue",
    "retro",
    "minimal",
    "cosmic",
    "museum",
    "vaporwave",
    "kintsugi",
    "bauhaus",
    "noir",
    "botanical",
    "liquid",
    "sports",
    "craft",
    "terminal",
    "mediterranean",
    "glacier",
    "comic",
    "watercolor",
    "industrial",
    "desertnight",
    "festival",
    "organic",
    "monsoon",
    "spaceage",
    "heritage",
    "streetart",
    "zen",
    "synthwave",
    "aurora",
    "terracotta",
    "deepsea",
    "typewriter",
    "silkroad",
    "lunar",
    "mosaic",
    "sakura",
    "acidpop",
    "bluehour",
    "espresso",
    "origami",
    "stainedglass",
    "safari",
    "underwater",
    "pixelarcade",
    "copper",
    "linen",
    "stormfront",
    "hologram",
    "antique",
    "neonmetro",
    "saffron",
    "cloudstudy",
    "cobalt",
    "papercut",
    "frostedglass",
    "wildflower",
    "blackvelvet",
    "sunprint",
    "kineticred",
    "citrus",
    "geode",
    "rainywindow",
    "fable",
    "signalwave",
    "oldmoney",
    "sundial",
    "cherrychrome",
    "cloisonne",
    "nightgarden",
    "chalkboard",
    "topographic",
    "prismatica",
    "vinyljazz",
    "sugarcube",
    "obsidian",
    "kinfolk",
    "atlasa",
    "atlasb",
    "atlasc",
    "atlasd",
    "atlase",
    "atlasf",
    "atlasg",
    "atlash",
    "atlasi",
    "atlasj",
    "dialoguea",
    "dialogueb",
    "dialoguec",
    "dialogued",
    "dialoguee",
    "dialoguef",
    "dialogueg",
    "dialogueh",
    "dialoguei",
    "dialoguej",
    "scholara",
    "scholarb",
    "scholarc",
    "scholard",
    "scholare",
    "scholarf",
    "scholarg",
    "scholarh",
    "scholari",
    "scholarj",
    "chroniclea",
    "chronicleb",
    "chroniclec",
    "chronicled",
    "chroniclee",
    "chroniclef",
    "chronicleg",
    "chronicleh",
    "chroniclei",
    "chroniclej",
    "orbita",
    "orbitb",
    "orbitc",
    "orbitd",
    "orbite",
    "orbitf",
    "orbitg",
    "orbith",
    "orbiti",
    "orbitj",
    "signala",
    "signalb",
    "signalc",
    "signald",
    "signale",
    "signalf",
    "signalg",
    "signalh",
    "signali",
    "signalj",
    "canvasa",
    "canvasb",
    "canvasc",
    "canvasd",
    "canvase",
    "canvasf",
    "canvasg",
    "canvash",
    "canvasi",
    "canvasj",
    "foruma",
    "forumb",
    "forumc",
    "forumd",
    "forume",
    "forumf",
    "forumg",
    "forumh",
    "forumi",
    "forumj",
    "fieldnotea",
    "fieldnoteb",
    "fieldnotec",
    "fieldnoted",
    "fieldnotee",
    "fieldnotef",
    "fieldnoteg",
    "fieldnoteh",
    "fieldnotei",
    "fieldnotej",
    "studioa",
    "studiob",
    "studioc",
    "studiod",
    "studioe",
    "studiof",
    "studiog",
    "studioh",
    "studioi",
    "studioj",
    "pulsea",
    "pulseb",
    "pulsec",
    "pulsed",
    "pulsee",
    "pulsef",
    "pulseg",
    "pulseh",
    "pulsei",
    "pulsej",
    "archivea",
    "archiveb",
    "archivec",
    "archived",
    "archivee",
    "archivef",
    "archiveg",
    "archiveh",
    "archivei",
    "archivej",
    "compassa",
    "compassb",
    "compassc",
    "compassd",
    "compasse",
    "compassf",
    "compassg",
    "compassh",
    "compassi",
    "compassj",
    "thesisa",
    "thesisb",
    "thesisc",
    "thesisd",
    "thesise",
    "thesisf",
    "thesisg",
    "thesish",
    "thesisi",
    "thesisj",
    "storybooka",
    "storybookb",
    "storybookc",
    "storybookd",
    "storybooke",
    "storybookf",
    "storybookg",
    "storybookh",
    "storybooki",
    "storybookj",
    "blueprinta",
    "blueprintb",
    "blueprintc",
    "blueprintd",
    "blueprinte",
    "blueprintf",
    "blueprintg",
    "blueprinth",
    "blueprinti",
    "blueprintj",
    "monumenta",
    "monumentb",
    "monumentc",
    "monumentd",
    "monumente",
    "monumentf",
    "monumentg",
    "monumenth",
    "monumenti",
    "monumentj",
    "spectruma",
    "spectrumb",
    "spectrumc",
    "spectrumd",
    "spectrume",
    "spectrumf",
    "spectrumg",
    "spectrumh",
    "spectrumi",
    "spectrumj",
    "workshopa",
    "workshopb",
    "workshopc",
    "workshopd",
    "workshope",
    "workshopf",
    "workshopg",
    "workshoph",
    "workshopi",
    "workshopj",
    "observatorya",
    "observatoryb",
    "observatoryc",
    "observatoryd",
    "observatorye",
    "observatoryf",
    "observatoryg",
    "observatoryh",
    "observatoryi",
    "observatoryj"
  ],
  "themes": {
    "royal": {
      "name": "Royal Ivory",
      "bn": "রয়্যাল আইভরি (আইভরি + সোনালি)",
      "dark": false,
      "c": {
        "bg": [
          "#fbf6ec",
          "#f2e8d4",
          "#e2d1ae"
        ],
        "ink": "#2a1c10",
        "sub": "#8a6224",
        "accent": "#b98a3e",
        "accentL": "#e6cc8f",
        "accentD": "#8a6224",
        "accent2": "#1f4d46",
        "onAccent": "#2a1608",
        "chip": "rgba(255,252,245,0.82)",
        "halo": "255,250,238",
        "glow": "226,184,100",
        "vig": "120,84,30",
        "palette": [
          "#d9a441",
          "#d6587f",
          "#2f7f6b",
          "#8f7bc4",
          "#c8672a",
          "#7a5a37"
        ]
      },
      "font": {
        "display": "Cormorant Garamond",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,500;1,600",
          "Jost:wght@400;500;600",
          "Noto+Sans+Bengali:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "arabesque",
        "frame": "deco",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.9,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "harp",
        "mode": "major",
        "tempo": 60,
        "root": 98,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 100
      }
    },
    "midnight": {
      "name": "Midnight Tech",
      "bn": "মিডনাইট টেক (নেভি + সায়ান)",
      "dark": true,
      "c": {
        "bg": [
          "#14284e",
          "#0b1530",
          "#050a1a"
        ],
        "ink": "#eaf3ff",
        "sub": "#6fd6ff",
        "accent": "#25c2ff",
        "accentL": "#9fe6ff",
        "accentD": "#0a8fd1",
        "accent2": "#7c6bff",
        "onAccent": "#03101f",
        "chip": "rgba(10,26,56,0.72)",
        "halo": "4,10,28",
        "glow": "37,194,255",
        "vig": "0,0,0",
        "palette": [
          "#25c2ff",
          "#7c6bff",
          "#2de2b0",
          "#ff7ab6",
          "#ffd166",
          "#4d8dff"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Space Grotesk",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Space+Grotesk:wght@400;500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "scan",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "line",
        "rays": "rings",
        "particles": "square",
        "arch": "diamond",
        "upper": true,
        "ls": 0.7,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.86,
        "bright": 0.8,
        "sub": 1.3
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "minor",
        "tempo": 68,
        "root": 110,
        "rhythm": "pulse",
        "brightness": 0.23,
        "seed": 101
      }
    },
    "emerald": {
      "name": "Emerald Garden",
      "bn": "এমারেল্ড গার্ডেন (গাঢ় সবুজ + পুদিনা)",
      "dark": true,
      "c": {
        "bg": [
          "#1d5b4d",
          "#0f3d33",
          "#07241e"
        ],
        "ink": "#f1fbf6",
        "sub": "#8be0b6",
        "accent": "#35d49a",
        "accentL": "#a8f0d0",
        "accentD": "#1a9a6f",
        "accent2": "#e6c36a",
        "onAccent": "#04231a",
        "chip": "rgba(8,48,40,0.7)",
        "halo": "5,28,23",
        "glow": "53,212,154",
        "vig": "0,0,0",
        "palette": [
          "#35d49a",
          "#e6c36a",
          "#7bd88f",
          "#4cc9f0",
          "#f4a261",
          "#b8f2e6"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Serif Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Playfair+Display:wght@500;600;700",
          "Jost:wght@400;500;600",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "topo",
        "frame": "arch",
        "orn": "leaf",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "bubble",
        "arch": "oval",
        "upper": false,
        "ls": 0.25,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.95,
        "bright": 0.9,
        "sub": 1.1
      },
      "bgm": {
        "genre": "plucked",
        "mode": "dorian",
        "tempo": 76,
        "root": 123.47,
        "rhythm": "syncopated",
        "brightness": 0.34,
        "seed": 102
      }
    },
    "sunrise": {
      "name": "Sunrise Pop",
      "bn": "সানরাইজ পপ (কমলা + কোরাল)",
      "dark": false,
      "c": {
        "bg": [
          "#fff4e1",
          "#ffd9b8",
          "#ffb7a0"
        ],
        "ink": "#3a1608",
        "sub": "#c2410c",
        "accent": "#ff6a1a",
        "accentL": "#ffc27a",
        "accentD": "#c2410c",
        "accent2": "#e11d74",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.88)",
        "halo": "255,244,228",
        "glow": "255,140,60",
        "vig": "190,70,20",
        "palette": [
          "#ff6a1a",
          "#e11d74",
          "#ffb703",
          "#fb5607",
          "#8338ec",
          "#06d6a0"
        ]
      },
      "font": {
        "display": "Poppins",
        "body": "Poppins",
        "bn": "Hind Siliguri",
        "dw": 700,
        "bw": 600,
        "gf": [
          "Poppins:wght@500;600;700",
          "Hind+Siliguri:wght@400;500;600;700"
        ]
      },
      "style": {
        "pattern": "burst",
        "frame": "round",
        "fw": 12,
        "orn": "sun",
        "chip": "block",
        "rule": "bar",
        "rays": "conic",
        "particles": "ember",
        "arch": "circle",
        "upper": true,
        "ls": 0.35,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 1.12,
        "bright": 1.1,
        "sub": 0.9
      },
      "bgm": {
        "genre": "piano",
        "mode": "pentatonic",
        "tempo": 88,
        "root": 130.81,
        "rhythm": "arpeggio",
        "brightness": 0.45,
        "seed": 103
      }
    },
    "rose": {
      "name": "Rose Blush",
      "bn": "রোজ ব্লাশ (গোলাপি + প্লাম)",
      "dark": false,
      "c": {
        "bg": [
          "#fff2f5",
          "#fbd9e3",
          "#f2b6ca"
        ],
        "ink": "#3b1230",
        "sub": "#a21d5b",
        "accent": "#d6336c",
        "accentL": "#f7a8c4",
        "accentD": "#9d174d",
        "accent2": "#6d2a5e",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "255,240,244",
        "glow": "240,120,160",
        "vig": "160,40,90",
        "palette": [
          "#d6336c",
          "#f7a8c4",
          "#6d2a5e",
          "#ff8fab",
          "#b5179e",
          "#ffb3c6"
        ]
      },
      "font": {
        "display": "DM Serif Display",
        "body": "DM Sans",
        "bn": "Noto Serif Bengali",
        "dw": 400,
        "bw": 500,
        "gf": [
          "DM+Serif+Display:ital@0;1",
          "DM+Sans:wght@400;500;600",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "bokeh",
        "frame": "ticket",
        "fw": 2,
        "orn": "spark",
        "chip": "glass",
        "rule": "dots",
        "rays": "none",
        "particles": "snow",
        "arch": "oval",
        "upper": false,
        "ls": 0.15,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 1.2,
        "sub": 0.6
      },
      "bgm": {
        "genre": "strings",
        "mode": "lydian",
        "tempo": 94,
        "root": 146.83,
        "rhythm": "waltz",
        "brightness": 0.56,
        "seed": 104
      }
    },
    "ocean": {
      "name": "Ocean Breeze",
      "bn": "ওশান ব্রিজ (অ্যাকোয়া + টিল)",
      "dark": false,
      "c": {
        "bg": [
          "#ebfcff",
          "#bfeef6",
          "#80d4e7"
        ],
        "ink": "#06324a",
        "sub": "#0b7a99",
        "accent": "#0891b2",
        "accentL": "#7dd3e8",
        "accentD": "#0e5f7a",
        "accent2": "#f59e0b",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.86)",
        "halo": "232,251,255",
        "glow": "34,190,220",
        "vig": "10,90,120",
        "palette": [
          "#0891b2",
          "#f59e0b",
          "#06b6d4",
          "#3b82f6",
          "#10b981",
          "#f472b6"
        ]
      },
      "font": {
        "display": "Nunito",
        "body": "Nunito",
        "bn": "Baloo Da 2",
        "dw": 800,
        "bw": 700,
        "gf": [
          "Nunito:wght@600;700;800",
          "Baloo+Da+2:wght@500;600;700"
        ]
      },
      "style": {
        "pattern": "waves",
        "frame": "none",
        "orn": "drop",
        "chip": "pill",
        "rule": "dots",
        "rays": "rings",
        "particles": "bubble",
        "arch": "circle",
        "upper": false,
        "ls": 0.1,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.05,
        "bright": 1.0,
        "sub": 0.9
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 102,
        "root": 164.81,
        "rhythm": "ostinato",
        "brightness": 0.67,
        "seed": 105
      }
    },
    "crimson": {
      "name": "Crimson Breaking",
      "bn": "ক্রিমসন ব্রেকিং (কালো + লাল)",
      "dark": true,
      "c": {
        "bg": [
          "#2c0e11",
          "#170709",
          "#080203"
        ],
        "ink": "#fff4f1",
        "sub": "#ff7a6b",
        "accent": "#ef2b2d",
        "accentL": "#ff8a80",
        "accentD": "#b4101a",
        "accent2": "#ffd166",
        "onAccent": "#ffffff",
        "chip": "rgba(34,8,10,0.8)",
        "halo": "10,2,3",
        "glow": "239,43,45",
        "vig": "0,0,0",
        "palette": [
          "#ef2b2d",
          "#ffd166",
          "#ff8a80",
          "#ffffff",
          "#b4101a",
          "#ff6b35"
        ]
      },
      "font": {
        "display": "Bebas Neue",
        "body": "Barlow Condensed",
        "bn": "Anek Bangla",
        "dw": 400,
        "bw": 600,
        "gf": [
          "Bebas+Neue",
          "Barlow+Condensed:wght@500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "stripes",
        "frame": "bar",
        "orn": "tri",
        "chip": "block",
        "rule": "bar",
        "rays": "conic",
        "particles": "ember",
        "arch": "rect",
        "upper": true,
        "ls": 0.65,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.8,
        "bright": 0.7,
        "sub": 1.6
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "major",
        "tempo": 112,
        "root": 174.61,
        "rhythm": "drone",
        "brightness": 0.78,
        "seed": 106
      }
    },
    "neon": {
      "name": "Neon Pulse",
      "bn": "নিয়ন পালস (বেগুনি + ম্যাজেন্টা)",
      "dark": true,
      "c": {
        "bg": [
          "#2c1052",
          "#160829",
          "#07030f"
        ],
        "ink": "#fdf4ff",
        "sub": "#5ef2ff",
        "accent": "#ff2bd6",
        "accentL": "#ff9cf0",
        "accentD": "#c0149f",
        "accent2": "#19e6ff",
        "onAccent": "#12021f",
        "chip": "rgba(22,6,42,0.7)",
        "halo": "8,2,16",
        "glow": "255,43,214",
        "vig": "0,0,0",
        "palette": [
          "#ff2bd6",
          "#19e6ff",
          "#b388ff",
          "#ffe45e",
          "#7cffb2",
          "#ff6b9d"
        ]
      },
      "font": {
        "display": "Orbitron",
        "body": "Rajdhani",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 600,
        "gf": [
          "Orbitron:wght@600;800",
          "Rajdhani:wght@500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "grid",
        "frame": "brackets",
        "orn": "plus",
        "chip": "outline",
        "rule": "line",
        "rays": "rings",
        "particles": "square",
        "arch": "diamond",
        "upper": true,
        "ls": 0.45,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.25,
        "bright": 1.3,
        "sub": 1.2
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "minor",
        "tempo": 120,
        "root": 196,
        "rhythm": "pulse",
        "brightness": 0.89,
        "seed": 107
      }
    },
    "mono": {
      "name": "Mono Editorial",
      "bn": "মনো এডিটোরিয়াল (সাদা + কালো)",
      "dark": false,
      "c": {
        "bg": [
          "#ffffff",
          "#f5f5f2",
          "#e5e5e0"
        ],
        "ink": "#0b0b0b",
        "sub": "#555555",
        "accent": "#111111",
        "accentL": "#9a9a9a",
        "accentD": "#000000",
        "accent2": "#e5322d",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.96)",
        "halo": "255,255,255",
        "glow": "120,120,120",
        "vig": "60,60,60",
        "palette": [
          "#111111",
          "#e5322d",
          "#777777",
          "#2b6cb0",
          "#d69e2e",
          "#38a169"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Archivo",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": [
          "Archivo:wght@500;600;800",
          "Noto+Sans+Bengali:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "dots",
        "frame": "plain",
        "orn": "square",
        "chip": "tag",
        "rule": "bar",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": true,
        "ls": 0.3,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 0.9,
        "sub": 1.0
      },
      "bgm": {
        "genre": "celesta",
        "mode": "dorian",
        "tempo": 132,
        "root": 220,
        "rhythm": "syncopated",
        "brightness": 0.12,
        "seed": 108
      }
    },
    "lavender": {
      "name": "Lavender Dream",
      "bn": "ল্যাভেন্ডার ড্রিম (বেগুনি + লিলাক)",
      "dark": false,
      "c": {
        "bg": [
          "#f8f2ff",
          "#e7dafb",
          "#cdb9f5"
        ],
        "ink": "#2a1457",
        "sub": "#6d3fd6",
        "accent": "#8b5cf6",
        "accentL": "#c4b0fb",
        "accentD": "#5b2fc2",
        "accent2": "#f472b6",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "247,241,255",
        "glow": "139,92,246",
        "vig": "90,50,170",
        "palette": [
          "#8b5cf6",
          "#f472b6",
          "#38bdf8",
          "#fbbf24",
          "#34d399",
          "#c4b0fb"
        ]
      },
      "font": {
        "display": "Quicksand",
        "body": "Quicksand",
        "bn": "Hind Siliguri",
        "dw": 700,
        "bw": 600,
        "gf": [
          "Quicksand:wght@500;600;700",
          "Hind+Siliguri:wght@400;500;600;700"
        ]
      },
      "style": {
        "pattern": "aurora",
        "frame": "ticket",
        "orn": "moon",
        "chip": "glass",
        "rule": "dots",
        "rays": "none",
        "particles": "snow",
        "arch": "circle",
        "upper": false,
        "ls": 0.3,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.1,
        "bright": 1.15,
        "sub": 0.7
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "pentatonic",
        "tempo": 144,
        "root": 246.94,
        "rhythm": "arpeggio",
        "brightness": 0.23,
        "seed": 109
      }
    },
    "luxe": {
      "name": "Luxe Black Gold",
      "bn": "লাক্স ব্ল্যাক গোল্ড (কালো + সোনালি)",
      "dark": true,
      "c": {
        "bg": [
          "#2b2519",
          "#15120c",
          "#070604"
        ],
        "ink": "#f6ecd2",
        "sub": "#e3bd5e",
        "accent": "#d4a63a",
        "accentL": "#f1d98a",
        "accentD": "#a67c1c",
        "accent2": "#f1d98a",
        "onAccent": "#1a1204",
        "chip": "rgba(26,22,13,0.8)",
        "halo": "8,7,4",
        "glow": "212,166,58",
        "vig": "0,0,0",
        "palette": [
          "#d4a63a",
          "#f1d98a",
          "#a67c1c",
          "#e8e2d0",
          "#8c6a1f",
          "#ffd86b"
        ]
      },
      "font": {
        "display": "Cinzel",
        "body": "Montserrat",
        "bn": "Noto Serif Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Cinzel:wght@500;700",
          "Montserrat:wght@400;500;600",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "style": {
        "pattern": "deco",
        "frame": "deco",
        "orn": "diamond",
        "chip": "outline",
        "rule": "orn",
        "rays": "conic",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.95,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.0,
        "sub": 1.2
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 80,
        "root": 261.63,
        "rhythm": "waltz",
        "brightness": 0.34,
        "seed": 110
      }
    },
    "sand": {
      "name": "Sand Terracotta",
      "bn": "স্যান্ড টেরাকোটা (মাটি রং + সেজ)",
      "dark": false,
      "c": {
        "bg": [
          "#fcf3e6",
          "#f1ddc2",
          "#e2c39b"
        ],
        "ink": "#3d2314",
        "sub": "#b4532a",
        "accent": "#c2603a",
        "accentL": "#e9b08c",
        "accentD": "#8f3d1e",
        "accent2": "#5f7a54",
        "onAccent": "#ffffff",
        "chip": "rgba(255,249,238,0.86)",
        "halo": "251,242,228",
        "glow": "220,150,100",
        "vig": "140,80,40",
        "palette": [
          "#c2603a",
          "#5f7a54",
          "#e9b08c",
          "#d9a441",
          "#8f3d1e",
          "#9bb08c"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "DM Sans",
        "bn": "Tiro Bangla",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Fraunces:wght@500;600;700",
          "DM+Sans:wght@400;500;600",
          "Tiro+Bangla:ital@0;1"
        ]
      },
      "style": {
        "pattern": "arcs",
        "frame": "arch",
        "orn": "circle",
        "chip": "tag",
        "rule": "orn",
        "rays": "none",
        "particles": "dot",
        "arch": "arch",
        "upper": false,
        "ls": 0.25,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.98,
        "bright": 0.85,
        "sub": 1.0
      },
      "bgm": {
        "genre": "handpan",
        "mode": "mixolydian",
        "tempo": 100,
        "root": 293.66,
        "rhythm": "ostinato",
        "brightness": 0.45,
        "seed": 111
      }
    },
    "editorial": {
      "label": "Editorial Swiss",
      "dark": false,
      "style": {
        "pattern": "stripes",
        "frame": "plain",
        "orn": "square",
        "chip": "tag",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": true,
        "ls": 1.0,
        "motion": "smooth",
        "spot": false
      },
      "c": {
        "bg": [
          "#f7f4ee",
          "#e7e1d6",
          "#d4ccbe"
        ],
        "ink": "#171717",
        "sub": "#5b5b55",
        "accent": "#d62929",
        "accentL": "#ff8a75",
        "accentD": "#8f1717",
        "accent2": "#171717",
        "onAccent": "#f4f0e8",
        "chip": "rgba(255,255,255,0.9)",
        "halo": "245,242,235",
        "glow": "215,45,45",
        "vig": "80,60,55",
        "palette": [
          "#d62929",
          "#171717",
          "#6b7280",
          "#eab308",
          "#0f766e",
          "#f8fafc"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": [
          "Archivo:wght@500;600;800",
          "Inter:wght@400;500;600;700",
          "Noto+Sans+Bengali:wght@400;600;700"
        ]
      },
      "name": "Editorial Swiss",
      "bn": "Editorial Swiss",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 60,
        "root": 98,
        "rhythm": "drone",
        "brightness": 0.56,
        "seed": 112
      }
    },
    "cyberpunk": {
      "label": "Cyberpunk",
      "dark": true,
      "style": {
        "pattern": "scan",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "line",
        "rays": "rings",
        "particles": "square",
        "arch": "diamond",
        "upper": true,
        "ls": 0.7,
        "motion": "snappy",
        "spot": true
      },
      "c": {
        "bg": [
          "#10051f",
          "#230b35",
          "#070711"
        ],
        "ink": "#f8f3ff",
        "sub": "#ff54de",
        "accent": "#ff2bd6",
        "accentL": "#ff9cf0",
        "accentD": "#b50d91",
        "accent2": "#00f5ff",
        "onAccent": "#12021f",
        "chip": "rgba(20,5,36,0.8)",
        "halo": "10,2,18",
        "glow": "255,43,214",
        "vig": "0,0,0",
        "palette": [
          "#ff2bd6",
          "#00f5ff",
          "#b8ff3b",
          "#ff4d6d",
          "#a78bfa",
          "#ffe45e"
        ]
      },
      "font": {
        "display": "Orbitron",
        "body": "Rajdhani",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 600,
        "gf": [
          "Orbitron:wght@600;800",
          "Rajdhani:wght@500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "name": "Cyberpunk",
      "bn": "Cyberpunk",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 68,
        "root": 110,
        "rhythm": "pulse",
        "brightness": 0.67,
        "seed": 113
      }
    },
    "forest": {
      "label": "Forest Field",
      "dark": true,
      "style": {
        "pattern": "topo",
        "frame": "arch",
        "orn": "leaf",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "bubble",
        "arch": "oval",
        "upper": false,
        "ls": 0.1,
        "motion": "smooth",
        "spot": false
      },
      "c": {
        "bg": [
          "#102d24",
          "#1d4937",
          "#081b15"
        ],
        "ink": "#f0f8ed",
        "sub": "#a7d7a2",
        "accent": "#7bc67b",
        "accentL": "#c2e6a7",
        "accentD": "#3b8d62",
        "accent2": "#e6c86e",
        "onAccent": "#10251a",
        "chip": "rgba(11,45,31,0.8)",
        "halo": "6,25,18",
        "glow": "123,198,123",
        "vig": "0,0,0",
        "palette": [
          "#7bc67b",
          "#e6c86e",
          "#d2e9b8",
          "#63b3a5",
          "#f4a261",
          "#eaf4df"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "Manrope",
        "bn": "Noto Serif Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Fraunces:wght@500;600;700",
          "Manrope:wght@400;500;600;700",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "name": "Forest Field",
      "bn": "Forest Field",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "dorian",
        "tempo": 76,
        "root": 123.47,
        "rhythm": "syncopated",
        "brightness": 0.78,
        "seed": 114
      }
    },
    "blueprint": {
      "label": "Blueprint",
      "dark": true,
      "style": {
        "pattern": "grid",
        "frame": "brackets",
        "orn": "plus",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": true,
        "ls": 0.6,
        "motion": "snappy",
        "spot": false
      },
      "c": {
        "bg": [
          "#082c54",
          "#0a4476",
          "#061b36"
        ],
        "ink": "#f0f7ff",
        "sub": "#8bc8ff",
        "accent": "#2b9cff",
        "accentL": "#a9dcff",
        "accentD": "#1264a3",
        "accent2": "#f0f7ff",
        "onAccent": "#031b33",
        "chip": "rgba(4,34,66,0.75)",
        "halo": "5,30,60",
        "glow": "43,156,255",
        "vig": "0,0,0",
        "palette": [
          "#2b9cff",
          "#f0f7ff",
          "#fbbf24",
          "#22d3ee",
          "#a78bfa",
          "#34d399"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "IBM Plex Sans",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Space+Grotesk:wght@400;500;600;700",
          "IBM+Plex+Sans:wght@400;500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "name": "Blueprint",
      "bn": "Blueprint",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 88,
        "root": 130.81,
        "rhythm": "arpeggio",
        "brightness": 0.89,
        "seed": 115
      }
    },
    "candy": {
      "label": "Candy Pop",
      "dark": false,
      "style": {
        "pattern": "bokeh",
        "frame": "ticket",
        "orn": "spark",
        "chip": "pill",
        "rule": "dots",
        "rays": "none",
        "particles": "bubble",
        "arch": "circle",
        "upper": false,
        "ls": 0.1,
        "motion": "smooth",
        "spot": true
      },
      "c": {
        "bg": [
          "#fff0f7",
          "#ffd5e8",
          "#f8bde0"
        ],
        "ink": "#42133c",
        "sub": "#a21d75",
        "accent": "#ff4fa3",
        "accentL": "#ff9fd0",
        "accentD": "#bc2675",
        "accent2": "#7c3aed",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.8)",
        "halo": "255,238,247",
        "glow": "255,79,163",
        "vig": "150,30,100",
        "palette": [
          "#ff4fa3",
          "#7c3aed",
          "#22c55e",
          "#f59e0b",
          "#06b6d4",
          "#fb7185"
        ]
      },
      "font": {
        "display": "Nunito",
        "body": "Nunito",
        "bn": "Baloo Da 2",
        "dw": 800,
        "bw": 700,
        "gf": [
          "Nunito:wght@600;700;800",
          "Baloo+Da+2:wght@500;600;700"
        ]
      },
      "name": "Candy Pop",
      "bn": "Candy Pop",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "organ",
        "mode": "lydian",
        "tempo": 94,
        "root": 146.83,
        "rhythm": "waltz",
        "brightness": 0.12,
        "seed": 116
      }
    },
    "volcanic": {
      "label": "Volcanic",
      "dark": true,
      "style": {
        "pattern": "burst",
        "frame": "bar",
        "orn": "tri",
        "chip": "block",
        "rule": "bar",
        "rays": "conic",
        "particles": "ember",
        "arch": "rect",
        "upper": true,
        "ls": 0.9,
        "motion": "snappy",
        "spot": true
      },
      "c": {
        "bg": [
          "#250c0a",
          "#4a1710",
          "#100504"
        ],
        "ink": "#fff1e7",
        "sub": "#ff9b62",
        "accent": "#f04427",
        "accentL": "#ffb14a",
        "accentD": "#a82017",
        "accent2": "#ffb14a",
        "onAccent": "#ffffff",
        "chip": "rgba(50,10,5,0.8)",
        "halo": "15,4,2",
        "glow": "240,68,39",
        "vig": "0,0,0",
        "palette": [
          "#f04427",
          "#ffb14a",
          "#fff1e7",
          "#f97316",
          "#a3e635",
          "#e11d48"
        ]
      },
      "font": {
        "display": "Bebas Neue",
        "body": "Barlow Condensed",
        "bn": "Anek Bangla",
        "dw": 400,
        "bw": 600,
        "gf": [
          "Bebas+Neue",
          "Barlow+Condensed:wght@500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "name": "Volcanic",
      "bn": "Volcanic",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "mixolydian",
        "tempo": 102,
        "root": 164.81,
        "rhythm": "ostinato",
        "brightness": 0.23,
        "seed": 117
      }
    },
    "arctic": {
      "label": "Arctic Glass",
      "dark": false,
      "style": {
        "pattern": "aurora",
        "frame": "double",
        "orn": "drop",
        "chip": "glass",
        "rule": "dots",
        "rays": "rings",
        "particles": "snow",
        "arch": "oval",
        "upper": false,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "c": {
        "bg": [
          "#f4fcff",
          "#d6f1fa",
          "#a9dce9"
        ],
        "ink": "#073348",
        "sub": "#197b99",
        "accent": "#00a8cc",
        "accentL": "#9be7f5",
        "accentD": "#126a83",
        "accent2": "#6d5dfc",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.76)",
        "halo": "242,252,255",
        "glow": "0,168,204",
        "vig": "30,110,140",
        "palette": [
          "#00a8cc",
          "#6d5dfc",
          "#ffffff",
          "#f59e0b",
          "#10b981",
          "#fb7185"
        ]
      },
      "font": {
        "display": "Quicksand",
        "body": "Nunito",
        "bn": "Hind Siliguri",
        "dw": 700,
        "bw": 600,
        "gf": [
          "Quicksand:wght@500;600;700",
          "Nunito:wght@600;700;800",
          "Hind+Siliguri:wght@400;500;600;700"
        ]
      },
      "name": "Arctic Glass",
      "bn": "Arctic Glass",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "major",
        "tempo": 112,
        "root": 174.61,
        "rhythm": "drone",
        "brightness": 0.34,
        "seed": 118
      }
    },
    "newspaper": {
      "label": "Newspaper",
      "dark": false,
      "style": {
        "pattern": "dots",
        "frame": "plain",
        "orn": "square",
        "chip": "tag",
        "rule": "bar",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": true,
        "ls": 1.2,
        "motion": "snappy",
        "spot": false
      },
      "c": {
        "bg": [
          "#f8f5ed",
          "#e6e0d4",
          "#cfc6b6"
        ],
        "ink": "#171717",
        "sub": "#4b5563",
        "accent": "#111827",
        "accentL": "#6b7280",
        "accentD": "#b91c1c",
        "accent2": "#b91c1c",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.92)",
        "halo": "248,245,237",
        "glow": "30,30,30",
        "vig": "70,60,50",
        "palette": [
          "#111827",
          "#b91c1c",
          "#4b5563",
          "#d97706",
          "#166534",
          "#f8f5ed"
        ]
      },
      "font": {
        "display": "Roboto Slab",
        "body": "Roboto",
        "bn": "Noto Serif Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Roboto+Slab:wght@500;600;700",
          "Roboto:wght@400;500;700",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "name": "Newspaper",
      "bn": "Newspaper",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "guitar",
        "mode": "minor",
        "tempo": 120,
        "root": 196,
        "rhythm": "pulse",
        "brightness": 0.45,
        "seed": 119
      }
    },
    "royalblue": {
      "label": "Royal Blue",
      "dark": true,
      "style": {
        "pattern": "arcs",
        "frame": "deco",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.7,
        "motion": "smooth",
        "spot": true
      },
      "c": {
        "bg": [
          "#071b4b",
          "#122e72",
          "#050d2b"
        ],
        "ink": "#f5f7ff",
        "sub": "#a9c7ff",
        "accent": "#4c7dff",
        "accentL": "#c7d8ff",
        "accentD": "#2548aa",
        "accent2": "#f5d16c",
        "onAccent": "#06143d",
        "chip": "rgba(8,27,75,0.78)",
        "halo": "5,20,65",
        "glow": "76,125,255",
        "vig": "0,0,0",
        "palette": [
          "#4c7dff",
          "#f5d16c",
          "#c7d8ff",
          "#ff7ab6",
          "#2dd4bf",
          "#ffffff"
        ]
      },
      "font": {
        "display": "Cinzel",
        "body": "Montserrat",
        "bn": "Noto Serif Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Cinzel:wght@500;700",
          "Montserrat:wght@400;500;600",
          "Noto+Serif+Bengali:wght@400;600;700"
        ]
      },
      "name": "Royal Blue",
      "bn": "Royal Blue",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "dorian",
        "tempo": 132,
        "root": 220,
        "rhythm": "syncopated",
        "brightness": 0.56,
        "seed": 120
      }
    },
    "retro": {
      "label": "Retro Print",
      "dark": false,
      "style": {
        "pattern": "stripes",
        "frame": "ticket",
        "orn": "circle",
        "chip": "block",
        "rule": "bar",
        "rays": "conic",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.3,
        "motion": "snappy",
        "spot": false
      },
      "c": {
        "bg": [
          "#f7e9c8",
          "#e7c78d",
          "#c89b5c"
        ],
        "ink": "#2b1b12",
        "sub": "#8b451d",
        "accent": "#c65d2e",
        "accentL": "#f1b85b",
        "accentD": "#77351d",
        "accent2": "#f1b85b",
        "onAccent": "#ffffff",
        "chip": "rgba(255,248,224,0.88)",
        "halo": "247,233,200",
        "glow": "198,93,46",
        "vig": "100,60,30",
        "palette": [
          "#c65d2e",
          "#f1b85b",
          "#315c45",
          "#6b4e9b",
          "#e76f51",
          "#2b1b12"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "DM Sans",
        "bn": "Tiro Bangla",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Fraunces:wght@500;600;700",
          "DM+Sans:wght@400;500;600",
          "Tiro+Bangla:ital@0;1"
        ]
      },
      "name": "Retro Print",
      "bn": "Retro Print",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "bell",
        "mode": "pentatonic",
        "tempo": 144,
        "root": 246.94,
        "rhythm": "arpeggio",
        "brightness": 0.67,
        "seed": 121
      }
    },
    "minimal": {
      "label": "Minimal Studio",
      "dark": false,
      "style": {
        "pattern": "none",
        "frame": "none",
        "orn": "square",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": false,
        "ls": 0.8,
        "motion": "smooth",
        "spot": false
      },
      "c": {
        "bg": [
          "#fafafa",
          "#ededed",
          "#dcdcdc"
        ],
        "ink": "#171717",
        "sub": "#656565",
        "accent": "#292929",
        "accentL": "#8d8d8d",
        "accentD": "#555555",
        "accent2": "#d94645",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.88)",
        "halo": "250,250,250",
        "glow": "80,80,80",
        "vig": "80,80,80",
        "palette": [
          "#292929",
          "#d94645",
          "#2563eb",
          "#0f766e",
          "#d97706",
          "#737373"
        ]
      },
      "font": {
        "display": "Inter",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Inter:wght@400;500;600;700",
          "Noto+Sans+Bengali:wght@400;600;700"
        ]
      },
      "name": "Minimal Studio",
      "bn": "Minimal Studio",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 80,
        "root": 261.63,
        "rhythm": "waltz",
        "brightness": 0.78,
        "seed": 122
      }
    },
    "cosmic": {
      "label": "Cosmic Dream",
      "dark": true,
      "style": {
        "pattern": "aurora",
        "frame": "round",
        "orn": "moon",
        "chip": "glass",
        "rule": "dots",
        "rays": "rings",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.5,
        "motion": "smooth",
        "spot": true
      },
      "c": {
        "bg": [
          "#100f35",
          "#29205c",
          "#08071e"
        ],
        "ink": "#f6f2ff",
        "sub": "#b8a8ff",
        "accent": "#9b7cff",
        "accentL": "#d7caff",
        "accentD": "#6246c8",
        "accent2": "#54d6ff",
        "onAccent": "#100c2d",
        "chip": "rgba(22,16,56,0.76)",
        "halo": "15,12,45",
        "glow": "155,124,255",
        "vig": "0,0,0",
        "palette": [
          "#9b7cff",
          "#54d6ff",
          "#f5a6ff",
          "#ffe66d",
          "#72f1b8",
          "#f6f2ff"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Manrope",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": [
          "Space+Grotesk:wght@400;500;600;700",
          "Manrope:wght@400;500;600;700",
          "Anek+Bangla:wght@400;600;700"
        ]
      },
      "name": "Cosmic Dream",
      "bn": "Cosmic Dream",
      "sfx": {
        "pitch": 1.0,
        "bright": 1.0,
        "sub": 1.0
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 100,
        "root": 293.66,
        "rhythm": "ostinato",
        "brightness": 0.89,
        "seed": 123
      }
    },
    "museum": {
      "name": "Museum Gallery",
      "bn": "Museum Gallery",
      "dark": false,
      "c": {
        "bg": [
          "#f1eee6",
          "#dddbd4",
          "#c4c3bf"
        ],
        "ink": "#262b33",
        "sub": "#5e6c78",
        "accent": "#b08d57",
        "accentL": "#ccb592",
        "accentD": "#8e744e",
        "accent2": "#5e6c78",
        "onAccent": "#262b33",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "241,238,230",
        "glow": "176,141,87",
        "vig": "0,0,0",
        "palette": [
          "#b08d57",
          "#5e6c78",
          "#c4aa81",
          "#7e8993",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "none",
        "frame": "double",
        "orn": "leaf",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "arch",
        "upper": true,
        "ls": 0.1,
        "motion": "slow",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.65,
        "sub": 0.65
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 62,
        "root": 110,
        "rhythm": "drone",
        "brightness": 0.15,
        "seed": 200
      }
    },
    "vaporwave": {
      "name": "Vaporwave Sunset",
      "bn": "Vaporwave Sunset",
      "dark": true,
      "c": {
        "bg": [
          "#211a4c",
          "#372f5d",
          "#524972"
        ],
        "ink": "#fff0f7",
        "sub": "#49e6ff",
        "accent": "#ff6ac1",
        "accentL": "#ff9ed7",
        "accentD": "#ff8cce",
        "accent2": "#49e6ff",
        "onAccent": "#fff0f7",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "33,26,76",
        "glow": "255,106,193",
        "vig": "0,0,0",
        "palette": [
          "#ff6ac1",
          "#49e6ff",
          "#ff8fd0",
          "#6debff",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "aurora",
        "frame": "neon",
        "orn": "diamond",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "circle",
        "upper": false,
        "ls": 0.23,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.795,
        "bright": 0.77,
        "sub": 0.78
      },
      "bgm": {
        "genre": "marimba",
        "mode": "dorian",
        "tempo": 72,
        "root": 123.47,
        "rhythm": "pulse",
        "brightness": 0.27,
        "seed": 201
      }
    },
    "kintsugi": {
      "name": "Kintsugi Gold",
      "bn": "Kintsugi Gold",
      "dark": true,
      "c": {
        "bg": [
          "#171717",
          "#2d2c29",
          "#48463f"
        ],
        "ink": "#f7edcf",
        "sub": "#a33e35",
        "accent": "#d6ae4a",
        "accentL": "#e4ca89",
        "accentD": "#debe6b",
        "accent2": "#a33e35",
        "onAccent": "#f7edcf",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "23,23,23",
        "glow": "214,174,74",
        "vig": "0,0,0",
        "palette": [
          "#d6ae4a",
          "#a33e35",
          "#e0c277",
          "#b5655d",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "deco",
        "frame": "deco",
        "orn": "plus",
        "chip": "tag",
        "rule": "bar",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.36,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.87,
        "bright": 0.89,
        "sub": 0.91
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "pentatonic",
        "tempo": 84,
        "root": 130.81,
        "rhythm": "syncopated",
        "brightness": 0.39,
        "seed": 202
      }
    },
    "bauhaus": {
      "name": "Bauhaus Geometry",
      "bn": "Bauhaus Geometry",
      "dark": false,
      "c": {
        "bg": [
          "#f5f0e5",
          "#dfdad0",
          "#c4c0b7"
        ],
        "ink": "#161616",
        "sub": "#1d4ed8",
        "accent": "#e33e2b",
        "accentL": "#ed8275",
        "accentD": "#b03426",
        "accent2": "#1d4ed8",
        "onAccent": "#161616",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "245,240,229",
        "glow": "227,62,43",
        "vig": "0,0,0",
        "palette": [
          "#e33e2b",
          "#1d4ed8",
          "#ea6e60",
          "#4a71e0",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "bar",
        "orn": "spark",
        "chip": "block",
        "rule": "dots",
        "rays": "none",
        "particles": "square",
        "arch": "rect",
        "upper": false,
        "ls": 0.49,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.01,
        "sub": 1.04
      },
      "bgm": {
        "genre": "plucked",
        "mode": "minor",
        "tempo": 96,
        "root": 146.83,
        "rhythm": "arpeggio",
        "brightness": 0.51,
        "seed": 203
      }
    },
    "noir": {
      "name": "Film Noir",
      "bn": "Film Noir",
      "dark": true,
      "c": {
        "bg": [
          "#17191d",
          "#2d2e31",
          "#474849"
        ],
        "ink": "#f3eee5",
        "sub": "#8b949e",
        "accent": "#d6d0c4",
        "accentL": "#e4e0d9",
        "accentD": "#ddd8cc",
        "accent2": "#8b949e",
        "onAccent": "#f3eee5",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "23,25,29",
        "glow": "214,208,196",
        "vig": "0,0,0",
        "palette": [
          "#d6d0c4",
          "#8b949e",
          "#e0dcd3",
          "#a2a9b1",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "plain",
        "orn": "circle",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "rect",
        "upper": true,
        "ls": 0.62,
        "motion": "slow",
        "spot": false
      },
      "sfx": {
        "pitch": 1.02,
        "bright": 1.13,
        "sub": 1.17
      },
      "bgm": {
        "genre": "bell",
        "mode": "lydian",
        "tempo": 108,
        "root": 164.81,
        "rhythm": "waltz",
        "brightness": 0.63,
        "seed": 204
      }
    },
    "botanical": {
      "name": "Botanical Press",
      "bn": "Botanical Press",
      "dark": false,
      "c": {
        "bg": [
          "#e8efdf",
          "#d4dece",
          "#bdc9b9"
        ],
        "ink": "#244333",
        "sub": "#c58b62",
        "accent": "#668b54",
        "accentL": "#9cb490",
        "accentD": "#56794c",
        "accent2": "#c58b62",
        "onAccent": "#244333",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "232,239,223",
        "glow": "102,139,84",
        "vig": "0,0,0",
        "palette": [
          "#668b54",
          "#c58b62",
          "#8ca87f",
          "#d1a281",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "topo",
        "frame": "arch",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "leaf",
        "arch": "oval",
        "upper": false,
        "ls": 0.75,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.095,
        "bright": 1.25,
        "sub": 1.3
      },
      "bgm": {
        "genre": "strings",
        "mode": "mixolydian",
        "tempo": 118,
        "root": 174.61,
        "rhythm": "ostinato",
        "brightness": 0.75,
        "seed": 205
      }
    },
    "liquid": {
      "name": "Liquid Chrome",
      "bn": "Liquid Chrome",
      "dark": true,
      "c": {
        "bg": [
          "#101a23",
          "#263039",
          "#404b53"
        ],
        "ink": "#e8f8ff",
        "sub": "#9a8cff",
        "accent": "#6fe7f5",
        "accentL": "#a1eff8",
        "accentD": "#8debf8",
        "accent2": "#9a8cff",
        "onAccent": "#e8f8ff",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "16,26,35",
        "glow": "111,231,245",
        "vig": "0,0,0",
        "palette": [
          "#6fe7f5",
          "#9a8cff",
          "#93edf8",
          "#aea3ff",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "waves",
        "frame": "double",
        "orn": "leaf",
        "chip": "glass",
        "rule": "bar",
        "rays": "rings",
        "particles": "bubble",
        "arch": "oval",
        "upper": true,
        "ls": 0.88,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.37,
        "sub": 1.43
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 126,
        "root": 196,
        "rhythm": "drone",
        "brightness": 0.87,
        "seed": 206
      }
    },
    "sports": {
      "name": "Stadium Energy",
      "bn": "Stadium Energy",
      "dark": true,
      "c": {
        "bg": [
          "#101c2e",
          "#283343",
          "#454e5c"
        ],
        "ink": "#ffffff",
        "sub": "#ffd43b",
        "accent": "#ff4b32",
        "accentL": "#ff8a7a",
        "accentD": "#ff7865",
        "accent2": "#ffd43b",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "16,28,46",
        "glow": "255,75,50",
        "vig": "0,0,0",
        "palette": [
          "#ff4b32",
          "#ffd43b",
          "#ff7865",
          "#ffdd62",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "bar",
        "orn": "diamond",
        "chip": "outline",
        "rule": "dots",
        "rays": "conic",
        "particles": "ember",
        "arch": "rect",
        "upper": false,
        "ls": 1.01,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 1.245,
        "bright": 1.49,
        "sub": 1.56
      },
      "bgm": {
        "genre": "mallet",
        "mode": "dorian",
        "tempo": 138,
        "root": 220,
        "rhythm": "pulse",
        "brightness": 0.15,
        "seed": 207
      }
    },
    "craft": {
      "name": "Handcrafted Paper",
      "bn": "Handcrafted Paper",
      "dark": false,
      "c": {
        "bg": [
          "#efe0c4",
          "#decfb5",
          "#cabba2"
        ],
        "ink": "#49382a",
        "sub": "#6c8061",
        "accent": "#b45b3b",
        "accentL": "#ce9480",
        "accentD": "#995237",
        "accent2": "#6c8061",
        "onAccent": "#49382a",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "239,224,196",
        "glow": "180,91,59",
        "vig": "0,0,0",
        "palette": [
          "#b45b3b",
          "#6c8061",
          "#c7846c",
          "#899981",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "ticket",
        "orn": "plus",
        "chip": "tag",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 1.14,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.32,
        "bright": 0.65,
        "sub": 1.69
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "pentatonic",
        "tempo": 62,
        "root": 110,
        "rhythm": "syncopated",
        "brightness": 0.27,
        "seed": 208
      }
    },
    "terminal": {
      "name": "Terminal Green",
      "bn": "Terminal Green",
      "dark": true,
      "c": {
        "bg": [
          "#07130e",
          "#182b21",
          "#2d4739"
        ],
        "ink": "#b5ffd0",
        "sub": "#9effd4",
        "accent": "#52ff9a",
        "accentL": "#8fffbd",
        "accentD": "#6bffa8",
        "accent2": "#9effd4",
        "onAccent": "#b5ffd0",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "7,19,14",
        "glow": "82,255,154",
        "vig": "0,0,0",
        "palette": [
          "#52ff9a",
          "#9effd4",
          "#7dffb3",
          "#b1ffdd",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "IBM Plex Mono",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "brackets",
        "orn": "spark",
        "chip": "block",
        "rule": "orn",
        "rays": "rings",
        "particles": "square",
        "arch": "rect",
        "upper": false,
        "ls": 1.27,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.395,
        "bright": 0.77,
        "sub": 0.65
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "minor",
        "tempo": 72,
        "root": 123.47,
        "rhythm": "arpeggio",
        "brightness": 0.39,
        "seed": 209
      }
    },
    "mediterranean": {
      "name": "Mediterranean Tile",
      "bn": "Mediterranean Tile",
      "dark": false,
      "c": {
        "bg": [
          "#f7f0df",
          "#e2e0d3",
          "#c8cdc5"
        ],
        "ink": "#214f68",
        "sub": "#e5a94b",
        "accent": "#167f92",
        "accentL": "#68acb8",
        "accentD": "#197388",
        "accent2": "#e5a94b",
        "onAccent": "#214f68",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "247,240,223",
        "glow": "22,127,146",
        "vig": "0,0,0",
        "palette": [
          "#167f92",
          "#e5a94b",
          "#509fad",
          "#eaba6f",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "tile",
        "frame": "deco",
        "orn": "circle",
        "chip": "pill",
        "rule": "bar",
        "rays": "none",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.1,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.47,
        "bright": 0.89,
        "sub": 0.78
      },
      "bgm": {
        "genre": "organ",
        "mode": "lydian",
        "tempo": 84,
        "root": 130.81,
        "rhythm": "waltz",
        "brightness": 0.51,
        "seed": 210
      }
    },
    "glacier": {
      "name": "Glacier Expedition",
      "bn": "Glacier Expedition",
      "dark": false,
      "c": {
        "bg": [
          "#e6f4fa",
          "#d1e2e9",
          "#b8cbd5"
        ],
        "ink": "#163b52",
        "sub": "#b5e7ee",
        "accent": "#62b7d4",
        "accentL": "#99d0e3",
        "accentD": "#4f98b4",
        "accent2": "#b5e7ee",
        "onAccent": "#163b52",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "230,244,250",
        "glow": "98,183,212",
        "vig": "0,0,0",
        "palette": [
          "#62b7d4",
          "#b5e7ee",
          "#89c9df",
          "#c4ecf1",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crystal",
        "frame": "double",
        "orn": "tri",
        "chip": "glass",
        "rule": "dots",
        "rays": "rings",
        "particles": "snow",
        "arch": "oval",
        "upper": false,
        "ls": 0.23,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.545,
        "bright": 1.01,
        "sub": 0.91
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "mixolydian",
        "tempo": 96,
        "root": 146.83,
        "rhythm": "ostinato",
        "brightness": 0.63,
        "seed": 211
      }
    },
    "comic": {
      "name": "Comic Book Pop",
      "bn": "Comic Book Pop",
      "dark": false,
      "c": {
        "bg": [
          "#fff1c2",
          "#e8dbb1",
          "#ccc19c"
        ],
        "ink": "#171717",
        "sub": "#2764d8",
        "accent": "#ed334e",
        "accentL": "#f37a8c",
        "accentD": "#b82c40",
        "accent2": "#2764d8",
        "onAccent": "#171717",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "255,241,194",
        "glow": "237,51,78",
        "vig": "0,0,0",
        "palette": [
          "#ed334e",
          "#2764d8",
          "#f2667a",
          "#5283e0",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "bar",
        "orn": "leaf",
        "chip": "glass",
        "rule": "line",
        "rays": "conic",
        "particles": "star",
        "arch": "burst",
        "upper": true,
        "ls": 0.36,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.13,
        "sub": 1.04
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 108,
        "root": 164.81,
        "rhythm": "drone",
        "brightness": 0.75,
        "seed": 212
      }
    },
    "watercolor": {
      "name": "Watercolor Calm",
      "bn": "Watercolor Calm",
      "dark": false,
      "c": {
        "bg": [
          "#f2e9e7",
          "#e2d9d9",
          "#cfc6c9"
        ],
        "ink": "#51485e",
        "sub": "#7faeae",
        "accent": "#b88fbb",
        "accentL": "#d1b6d3",
        "accentD": "#9e7da4",
        "accent2": "#7faeae",
        "onAccent": "#51485e",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "242,233,231",
        "glow": "184,143,187",
        "vig": "0,0,0",
        "palette": [
          "#b88fbb",
          "#7faeae",
          "#caabcc",
          "#99bebe",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "wash",
        "frame": "none",
        "orn": "diamond",
        "chip": "outline",
        "rule": "orn",
        "rays": "none",
        "particles": "bubble",
        "arch": "oval",
        "upper": false,
        "ls": 0.49,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.795,
        "bright": 1.25,
        "sub": 1.17
      },
      "bgm": {
        "genre": "harp",
        "mode": "dorian",
        "tempo": 118,
        "root": 174.61,
        "rhythm": "pulse",
        "brightness": 0.87,
        "seed": 213
      }
    },
    "industrial": {
      "name": "Industrial Steel",
      "bn": "Industrial Steel",
      "dark": true,
      "c": {
        "bg": [
          "#252b30",
          "#393f42",
          "#525659"
        ],
        "ink": "#f0f0e9",
        "sub": "#8b9aa5",
        "accent": "#e7a52b",
        "accentL": "#efc475",
        "accentD": "#e9b85a",
        "accent2": "#8b9aa5",
        "onAccent": "#f0f0e9",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "37,43,48",
        "glow": "231,165,43",
        "vig": "0,0,0",
        "palette": [
          "#e7a52b",
          "#8b9aa5",
          "#edbc60",
          "#a2aeb7",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "IBM Plex Mono",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "metal",
        "frame": "brackets",
        "orn": "plus",
        "chip": "tag",
        "rule": "bar",
        "rays": "none",
        "particles": "square",
        "arch": "rect",
        "upper": true,
        "ls": 0.62,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 0.87,
        "bright": 1.37,
        "sub": 1.3
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "pentatonic",
        "tempo": 126,
        "root": 196,
        "rhythm": "syncopated",
        "brightness": 0.15,
        "seed": 214
      }
    },
    "desertnight": {
      "name": "Desert Night",
      "bn": "Desert Night",
      "dark": true,
      "c": {
        "bg": [
          "#211d37",
          "#373246",
          "#524b59"
        ],
        "ink": "#fff0d0",
        "sub": "#c96b55",
        "accent": "#e6a65d",
        "accentL": "#efc596",
        "accentD": "#ecb87a",
        "accent2": "#c96b55",
        "onAccent": "#fff0d0",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "33,29,55",
        "glow": "230,166,93",
        "vig": "0,0,0",
        "palette": [
          "#e6a65d",
          "#c96b55",
          "#ecbc86",
          "#d48977",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stars",
        "frame": "arch",
        "orn": "spark",
        "chip": "block",
        "rule": "dots",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": false,
        "ls": 0.75,
        "motion": "slow",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.49,
        "sub": 1.43
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "minor",
        "tempo": 138,
        "root": 220,
        "rhythm": "arpeggio",
        "brightness": 0.27,
        "seed": 215
      }
    },
    "festival": {
      "name": "Festival Lights",
      "bn": "Festival Lights",
      "dark": true,
      "c": {
        "bg": [
          "#251046",
          "#3b2756",
          "#554369"
        ],
        "ink": "#fff6e5",
        "sub": "#ff4f9a",
        "accent": "#ffcf4a",
        "accentL": "#ffe089",
        "accentD": "#ffd971",
        "accent2": "#ff4f9a",
        "onAccent": "#fff6e5",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "37,16,70",
        "glow": "255,207,74",
        "vig": "0,0,0",
        "palette": [
          "#ffcf4a",
          "#ff4f9a",
          "#ffdb77",
          "#ff72ae",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "confetti",
        "frame": "ticket",
        "orn": "circle",
        "chip": "pill",
        "rule": "line",
        "rays": "conic",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.88,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 1.02,
        "bright": 0.65,
        "sub": 1.56
      },
      "bgm": {
        "genre": "handpan",
        "mode": "lydian",
        "tempo": 62,
        "root": 110,
        "rhythm": "waltz",
        "brightness": 0.39,
        "seed": 216
      }
    },
    "organic": {
      "name": "Organic Shapes",
      "bn": "Organic Shapes",
      "dark": false,
      "c": {
        "bg": [
          "#f3e9d7",
          "#e1dac8",
          "#cbc8b7"
        ],
        "ink": "#3d5144",
        "sub": "#8aa66b",
        "accent": "#e28c61",
        "accentL": "#ecb498",
        "accentD": "#b97d5a",
        "accent2": "#8aa66b",
        "onAccent": "#3d5144",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "243,233,215",
        "glow": "226,140,97",
        "vig": "0,0,0",
        "palette": [
          "#e28c61",
          "#8aa66b",
          "#e9a988",
          "#a1b889",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "DM Sans",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "blobs",
        "frame": "round",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "bubble",
        "arch": "oval",
        "upper": false,
        "ls": 1.01,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.095,
        "bright": 0.77,
        "sub": 1.69
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "mixolydian",
        "tempo": 72,
        "root": 123.47,
        "rhythm": "ostinato",
        "brightness": 0.51,
        "seed": 217
      }
    },
    "monsoon": {
      "name": "Monsoon Rain",
      "bn": "Monsoon Rain",
      "dark": true,
      "c": {
        "bg": [
          "#122c3a",
          "#27404d",
          "#3f5864"
        ],
        "ink": "#e0f4f8",
        "sub": "#9ba9dc",
        "accent": "#69c5d8",
        "accentL": "#9ed9e6",
        "accentD": "#87d1e0",
        "accent2": "#9ba9dc",
        "onAccent": "#e0f4f8",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "18,44,58",
        "glow": "105,197,216",
        "vig": "0,0,0",
        "palette": [
          "#69c5d8",
          "#9ba9dc",
          "#8ed4e2",
          "#afbae3",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rain",
        "frame": "double",
        "orn": "leaf",
        "chip": "glass",
        "rule": "bar",
        "rays": "rings",
        "particles": "drop",
        "arch": "oval",
        "upper": true,
        "ls": 1.14,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.89,
        "sub": 0.65
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 84,
        "root": 130.81,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 218
      }
    },
    "spaceage": {
      "name": "Space Age",
      "bn": "Space Age",
      "dark": true,
      "c": {
        "bg": [
          "#11152c",
          "#262b41",
          "#40455a"
        ],
        "ink": "#e5f1ff",
        "sub": "#6e8dff",
        "accent": "#ff6d91",
        "accentL": "#ffa0b8",
        "accentD": "#f88eac",
        "accent2": "#6e8dff",
        "onAccent": "#e5f1ff",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "17,21,44",
        "glow": "255,109,145",
        "vig": "0,0,0",
        "palette": [
          "#ff6d91",
          "#6e8dff",
          "#ff92ac",
          "#8ba4ff",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "diamond",
        "chip": "outline",
        "rule": "dots",
        "rays": "rings",
        "particles": "star",
        "arch": "circle",
        "upper": false,
        "ls": 1.27,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 1.245,
        "bright": 1.01,
        "sub": 0.78
      },
      "bgm": {
        "genre": "celesta",
        "mode": "dorian",
        "tempo": 96,
        "root": 146.83,
        "rhythm": "pulse",
        "brightness": 0.75,
        "seed": 219
      }
    },
    "heritage": {
      "name": "Heritage Archive",
      "bn": "Heritage Archive",
      "dark": false,
      "c": {
        "bg": [
          "#e8d8b5",
          "#d7c7a7",
          "#c2b395"
        ],
        "ink": "#3c3025",
        "sub": "#61704e",
        "accent": "#a34f35",
        "accentL": "#c38d7c",
        "accentD": "#894731",
        "accent2": "#61704e",
        "onAccent": "#3c3025",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "232,216,181",
        "glow": "163,79,53",
        "vig": "0,0,0",
        "palette": [
          "#a34f35",
          "#61704e",
          "#ba7b68",
          "#818d71",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "engrave",
        "frame": "deco",
        "orn": "plus",
        "chip": "tag",
        "rule": "line",
        "rays": "none",
        "particles": "diamond",
        "arch": "arch",
        "upper": true,
        "ls": 0.1,
        "motion": "slow",
        "spot": false
      },
      "sfx": {
        "pitch": 1.32,
        "bright": 1.13,
        "sub": 0.91
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "pentatonic",
        "tempo": 108,
        "root": 164.81,
        "rhythm": "syncopated",
        "brightness": 0.87,
        "seed": 220
      }
    },
    "streetart": {
      "name": "Street Art",
      "bn": "Street Art",
      "dark": false,
      "c": {
        "bg": [
          "#f6f0e7",
          "#e0dad2",
          "#c5c1ba"
        ],
        "ink": "#191919",
        "sub": "#2b59c3",
        "accent": "#f04438",
        "accentL": "#f5857e",
        "accentD": "#ba3930",
        "accent2": "#2b59c3",
        "onAccent": "#191919",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "246,240,231",
        "glow": "240,68,56",
        "vig": "0,0,0",
        "palette": [
          "#f04438",
          "#2b59c3",
          "#f4736a",
          "#557acf",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "spray",
        "frame": "bar",
        "orn": "spark",
        "chip": "block",
        "rule": "orn",
        "rays": "conic",
        "particles": "dot",
        "arch": "rect",
        "upper": false,
        "ls": 0.23,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.395,
        "bright": 1.25,
        "sub": 1.04
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "minor",
        "tempo": 118,
        "root": 174.61,
        "rhythm": "arpeggio",
        "brightness": 0.15,
        "seed": 221
      }
    },
    "zen": {
      "name": "Zen Minimal",
      "bn": "Zen Minimal",
      "dark": false,
      "c": {
        "bg": [
          "#e9e4d9",
          "#d8d5ca",
          "#c3c2b8"
        ],
        "ink": "#3e4943",
        "sub": "#c49d79",
        "accent": "#7b8f7b",
        "accentL": "#a9b6a9",
        "accentD": "#6c7e6d",
        "accent2": "#c49d79",
        "onAccent": "#3e4943",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "233,228,217",
        "glow": "123,143,123",
        "vig": "0,0,0",
        "palette": [
          "#7b8f7b",
          "#c49d79",
          "#9cab9c",
          "#d0b194",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "enso",
        "frame": "none",
        "orn": "circle",
        "chip": "pill",
        "rule": "bar",
        "rays": "none",
        "particles": "none",
        "arch": "circle",
        "upper": true,
        "ls": 0.36,
        "motion": "slow",
        "spot": false
      },
      "sfx": {
        "pitch": 1.47,
        "bright": 1.37,
        "sub": 1.17
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "lydian",
        "tempo": 126,
        "root": 196,
        "rhythm": "waltz",
        "brightness": 0.27,
        "seed": 222
      }
    },
    "synthwave": {
      "name": "Synthwave Drive",
      "bn": "Synthwave Drive",
      "dark": true,
      "c": {
        "bg": [
          "#160f35",
          "#2d2649",
          "#494061"
        ],
        "ink": "#fff0fc",
        "sub": "#41d9ff",
        "accent": "#f64fc7",
        "accentL": "#f98ddb",
        "accentD": "#f877d4",
        "accent2": "#41d9ff",
        "onAccent": "#fff0fc",
        "chip": "rgba(255,255,255,0.16)",
        "halo": "22,15,53",
        "glow": "246,79,199",
        "vig": "0,0,0",
        "palette": [
          "#f64fc7",
          "#41d9ff",
          "#f87bd5",
          "#67e1ff",
          "#d9a441",
          "#5e7890"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Jost",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "sunsetgrid",
        "frame": "neon",
        "orn": "tri",
        "chip": "glass",
        "rule": "dots",
        "rays": "rings",
        "particles": "square",
        "arch": "circle",
        "upper": false,
        "ls": 0.49,
        "motion": "snappy",
        "spot": false
      },
      "sfx": {
        "pitch": 1.545,
        "bright": 1.49,
        "sub": 1.3
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "mixolydian",
        "tempo": 138,
        "root": 220,
        "rhythm": "ostinato",
        "brightness": 0.39,
        "seed": 223
      }
    },
    "aurora": {
      "name": "Aurora Borealis",
      "bn": "northern lights",
      "dark": true,
      "c": {
        "bg": [
          "#f9f3f0",
          "#ecd4ca",
          "#dcbf92"
        ],
        "ink": "#182429",
        "sub": "#278673",
        "accent": "#c8b41c",
        "accentL": "#e8df95",
        "accentD": "#837615",
        "accent2": "#278673",
        "onAccent": "#182429",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,201,78",
        "vig": "35,35,55",
        "palette": [
          "#d66e41",
          "#cad641",
          "#55d641",
          "#41d6a2",
          "#4196d6",
          "#6141d6"
        ]
      },
      "font": {
        "display": "DM Serif Display",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 0.35,
        "sub": 0.65
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 54,
        "root": 82.41,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 1000
      }
    },
    "terracotta": {
      "name": "Terracotta Studio",
      "bn": "clay and warm earth",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f5",
          "#caecde",
          "#92dcd4"
        ],
        "ink": "#29181f",
        "sub": "#86277d",
        "accent": "#1caac8",
        "accentL": "#95dae8",
        "accentD": "#157083",
        "accent2": "#86277d",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,193,217",
        "vig": "35,35,55",
        "palette": [
          "#41d699",
          "#419ed6",
          "#5941d6",
          "#ce41d6",
          "#d6416a",
          "#d68d41"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "subtle",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.37,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 0.5,
        "sub": 0.77
      },
      "bgm": {
        "genre": "marimba",
        "mode": "minor",
        "tempo": 65,
        "root": 95.41,
        "rhythm": "ostinato",
        "brightness": 0.225,
        "seed": 1037
      }
    },
    "deepsea": {
      "name": "Deep Sea Bioluminescence",
      "bn": "oceanic glow",
      "dark": false,
      "c": {
        "bg": [
          "#f8f0f9",
          "#e8caec",
          "#dc92cf"
        ],
        "ink": "#1a2918",
        "sub": "#618627",
        "accent": "#c81c78",
        "accentL": "#e895c1",
        "accentD": "#831550",
        "accent2": "#618627",
        "onAccent": "#1a2918",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,152",
        "vig": "35,35,55",
        "palette": [
          "#c541d6",
          "#d64173",
          "#d68441",
          "#b3d641",
          "#41d644",
          "#41d6b9"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "radial",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.54,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 0.65,
        "sub": 0.89
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "dorian",
        "tempo": 76,
        "root": 108.41,
        "rhythm": "drone",
        "brightness": 0.33,
        "seed": 1074
      }
    },
    "typewriter": {
      "name": "Typewriter Noir",
      "bn": "monospaced editorial",
      "dark": true,
      "c": {
        "bg": [
          "#f7f9f0",
          "#e6ecca",
          "#b9dc92"
        ],
        "ink": "#1b1829",
        "sub": "#274586",
        "accent": "#46c81c",
        "accentL": "#a9e895",
        "accentD": "#2f8315",
        "accent2": "#274586",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "111,217,78",
        "vig": "35,35,55",
        "palette": [
          "#bcd641",
          "#47d641",
          "#41d6b0",
          "#4188d6",
          "#6f41d6",
          "#d641c9"
        ]
      },
      "font": {
        "display": "IBM Plex Sans",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "waves",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "none",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.71,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.8,
        "sub": 1.01
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "minor",
        "tempo": 87,
        "root": 121.41,
        "rhythm": "pulse",
        "brightness": 0.435,
        "seed": 1111
      }
    },
    "silkroad": {
      "name": "Silk Road Caravan",
      "bn": "silk, brass and trade routes",
      "dark": false,
      "c": {
        "bg": [
          "#f0f5f9",
          "#cadcec",
          "#92a3dc"
        ],
        "ink": "#292018",
        "sub": "#86272a",
        "accent": "#251cc8",
        "accentL": "#9995e8",
        "accentD": "#1a1583",
        "accent2": "#86272a",
        "onAccent": "#292018",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "85,78,217",
        "vig": "35,35,55",
        "palette": [
          "#4191d6",
          "#6741d6",
          "#d641d1",
          "#d6415c",
          "#d69b41",
          "#9dd641"
        ]
      },
      "font": {
        "display": "Bodoni Moda",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "topo",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "subtle",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.88,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 0.95,
        "sub": 1.13
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "mixolydian",
        "tempo": 98,
        "root": 134.41,
        "rhythm": "waltz",
        "brightness": 0.54,
        "seed": 1148
      }
    },
    "lunar": {
      "name": "Lunar Observatory",
      "bn": "moonlit science",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f2",
          "#eccad2",
          "#dc9692"
        ],
        "ink": "#182925",
        "sub": "#27863f",
        "accent": "#c8571c",
        "accentL": "#e8b295",
        "accentD": "#833b15",
        "accent2": "#27863f",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,125,78",
        "vig": "35,35,55",
        "palette": [
          "#d64165",
          "#d69241",
          "#a6d641",
          "#41d651",
          "#41d6c6",
          "#4172d6"
        ]
      },
      "font": {
        "display": "Manrope",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "radial",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.05,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 1.1,
        "sub": 1.25
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "lydian",
        "tempo": 109,
        "root": 147.41,
        "rhythm": "drone",
        "brightness": 0.645,
        "seed": 1185
      }
    },
    "mosaic": {
      "name": "Persian Mosaic",
      "bn": "intricate mosaic geometry",
      "dark": true,
      "c": {
        "bg": [
          "#f0f9f0",
          "#caeccb",
          "#92dcac"
        ],
        "ink": "#291828",
        "sub": "#5b2786",
        "accent": "#1cc889",
        "accentL": "#95e8ca",
        "accentD": "#15835b",
        "accent2": "#5b2786",
        "onAccent": "#291828",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,166",
        "vig": "35,35,55",
        "palette": [
          "#41d649",
          "#41d6be",
          "#417ad6",
          "#7d41d6",
          "#d641bb",
          "#d64146"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "none",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 1.22,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 1.25,
        "sub": 0.65
      },
      "bgm": {
        "genre": "harp",
        "mode": "minor",
        "tempo": 120,
        "root": 160.41,
        "rhythm": "arpeggio",
        "brightness": 0.75,
        "seed": 1222
      }
    },
    "sakura": {
      "name": "Sakura Spring",
      "bn": "cherry blossom minimalism",
      "dark": false,
      "c": {
        "bg": [
          "#f3f0f9",
          "#d5caec",
          "#c292dc"
        ],
        "ink": "#232918",
        "sub": "#867727",
        "accent": "#bc1cc8",
        "accentL": "#e295e8",
        "accentD": "#7b1583",
        "accent2": "#867727",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "207,78,217",
        "vig": "35,35,55",
        "palette": [
          "#7441d6",
          "#d641c4",
          "#d6414f",
          "#d6a841",
          "#8fd641",
          "#41d668"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "subtle",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.2,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 0.35,
        "sub": 0.77
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 131,
        "root": 173.41,
        "rhythm": "pulse",
        "brightness": 0.855,
        "seed": 1259
      }
    },
    "acidpop": {
      "name": "Acid Pop",
      "bn": "acid colors and kinetic shapes",
      "dark": false,
      "c": {
        "bg": [
          "#f9f5f0",
          "#ecdfca",
          "#dcd792"
        ],
        "ink": "#181e29",
        "sub": "#277986",
        "accent": "#a3c81c",
        "accentL": "#d6e895",
        "accentD": "#6b8315",
        "accent2": "#277986",
        "onAccent": "#181e29",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "187,217,78",
        "vig": "35,35,55",
        "palette": [
          "#d6a041",
          "#98d641",
          "#41d65f",
          "#41d6d4",
          "#4164d6",
          "#9341d6"
        ]
      },
      "font": {
        "display": "Libre Baskerville",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "mesh",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "radial",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.37,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 0.5,
        "sub": 0.89
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "dorian",
        "tempo": 59,
        "root": 186.41,
        "rhythm": "syncopated",
        "brightness": 0.12,
        "seed": 1296
      }
    },
    "bluehour": {
      "name": "Blue Hour Cinema",
      "bn": "twilight cinematic",
      "dark": true,
      "c": {
        "bg": [
          "#f0f9f8",
          "#caece9",
          "#92cbdc"
        ],
        "ink": "#29181a",
        "sub": "#86275d",
        "accent": "#1c71c8",
        "accentL": "#95bee8",
        "accentD": "#154b83",
        "accent2": "#86275d",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,146,217",
        "vig": "35,35,55",
        "palette": [
          "#41d6cb",
          "#416cd6",
          "#8b41d6",
          "#d641ad",
          "#d64a41",
          "#d6bf41"
        ]
      },
      "font": {
        "display": "Sora",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.54,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 0.65,
        "sub": 1.01
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 70,
        "root": 199.41,
        "rhythm": "ostinato",
        "brightness": 0.225,
        "seed": 1333
      }
    },
    "espresso": {
      "name": "Espresso Atelier",
      "bn": "coffee editorial",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f7",
          "#eccae4",
          "#dc92b6"
        ],
        "ink": "#18291c",
        "sub": "#418627",
        "accent": "#c81c3e",
        "accentL": "#e895a6",
        "accentD": "#83152b",
        "accent2": "#418627",
        "onAccent": "#18291c",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,105",
        "vig": "35,35,55",
        "palette": [
          "#d641b6",
          "#d64141",
          "#d6b641",
          "#82d641",
          "#41d676",
          "#41c2d6"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "subtle",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.71,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 0.8,
        "sub": 1.13
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "mixolydian",
        "tempo": 81,
        "root": 212.41,
        "rhythm": "pulse",
        "brightness": 0.33,
        "seed": 1370
      }
    },
    "origami": {
      "name": "Origami Motion",
      "bn": "folded paper geometry",
      "dark": false,
      "c": {
        "bg": [
          "#f4f9f0",
          "#daecca",
          "#a0dc92"
        ],
        "ink": "#211829",
        "sub": "#272786",
        "accent": "#1cc82c",
        "accentL": "#95e89d",
        "accentD": "#15831f",
        "accent2": "#272786",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,91",
        "vig": "35,35,55",
        "palette": [
          "#8ad641",
          "#41d66d",
          "#41cbd6",
          "#4156d6",
          "#a141d6",
          "#d64197"
        ]
      },
      "font": {
        "display": "Cormorant Garamond",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "radial",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.88,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.95,
        "sub": 1.25
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "pentatonic",
        "tempo": 92,
        "root": 225.41,
        "rhythm": "syncopated",
        "brightness": 0.435,
        "seed": 1407
      }
    },
    "stainedglass": {
      "name": "Stained Glass",
      "bn": "cathedral glass light",
      "dark": true,
      "c": {
        "bg": [
          "#f0f2f9",
          "#cad0ec",
          "#9a92dc"
        ],
        "ink": "#292618",
        "sub": "#864327",
        "accent": "#5e1cc8",
        "accentL": "#b595e8",
        "accentD": "#3f1583",
        "accent2": "#864327",
        "onAccent": "#292618",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "131,78,217",
        "vig": "35,35,55",
        "palette": [
          "#415fd6",
          "#9841d6",
          "#d6419f",
          "#d65841",
          "#d6cd41",
          "#6bd641"
        ]
      },
      "font": {
        "display": "DM Serif Display",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 1.05,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 1.1,
        "sub": 0.65
      },
      "bgm": {
        "genre": "organ",
        "mode": "major",
        "tempo": 103,
        "root": 88.41,
        "rhythm": "waltz",
        "brightness": 0.54,
        "seed": 1444
      }
    },
    "safari": {
      "name": "Savanna Safari",
      "bn": "savanna landscape",
      "dark": false,
      "c": {
        "bg": [
          "#f9f1f0",
          "#eccdca",
          "#dcaf92"
        ],
        "ink": "#182729",
        "sub": "#27865f",
        "accent": "#c8911c",
        "accentL": "#e8cd95",
        "accentD": "#835f15",
        "accent2": "#27865f",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,172,78",
        "vig": "35,35,55",
        "palette": [
          "#d64f41",
          "#d6c441",
          "#74d641",
          "#41d683",
          "#41b5d6",
          "#4341d6"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "subtle",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.22,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 1.25,
        "sub": 0.77
      },
      "bgm": {
        "genre": "handpan",
        "mode": "mixolydian",
        "tempo": 114,
        "root": 101.41,
        "rhythm": "ostinato",
        "brightness": 0.645,
        "seed": 1481
      }
    },
    "underwater": {
      "name": "Underwater Dream",
      "bn": "submerged slow motion",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f3",
          "#caecd7",
          "#92dcc5"
        ],
        "ink": "#291823",
        "sub": "#7b2786",
        "accent": "#1cc8c3",
        "accentL": "#95e8e6",
        "accentD": "#158380",
        "accent2": "#7b2786",
        "onAccent": "#291823",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,213",
        "vig": "35,35,55",
        "palette": [
          "#41d67b",
          "#41bdd6",
          "#4148d6",
          "#af41d6",
          "#d64189",
          "#d66e41"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "radial",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.2,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 0.35,
        "sub": 0.89
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "dorian",
        "tempo": 125,
        "root": 114.41,
        "rhythm": "drone",
        "brightness": 0.75,
        "seed": 1518
      }
    },
    "pixelarcade": {
      "name": "Pixel Arcade",
      "bn": "8-bit arcade",
      "dark": true,
      "c": {
        "bg": [
          "#f6f0f9",
          "#e1caec",
          "#db92dc"
        ],
        "ink": "#1e2918",
        "sub": "#758627",
        "accent": "#c81c9c",
        "accentL": "#e895d3",
        "accentD": "#831566",
        "accent2": "#758627",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,181",
        "vig": "35,35,55",
        "palette": [
          "#a641d6",
          "#d64192",
          "#d66641",
          "#d2d641",
          "#5dd641",
          "#41d69a"
        ]
      },
      "font": {
        "display": "IBM Plex Sans",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "waves",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "none",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.37,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 0.5,
        "sub": 1.01
      },
      "bgm": {
        "genre": "celesta",
        "mode": "minor",
        "tempo": 136,
        "root": 127.41,
        "rhythm": "syncopated",
        "brightness": 0.855,
        "seed": 1555
      }
    },
    "copper": {
      "name": "Copper Patina",
      "bn": "oxidized metal luxe",
      "dark": false,
      "c": {
        "bg": [
          "#f9f8f0",
          "#ecebca",
          "#c8dc92"
        ],
        "ink": "#181929",
        "sub": "#275986",
        "accent": "#69c81c",
        "accentL": "#bae895",
        "accentD": "#468315",
        "accent2": "#275986",
        "onAccent": "#181929",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "140,217,78",
        "vig": "35,35,55",
        "palette": [
          "#d6d241",
          "#66d641",
          "#41d691",
          "#41a7d6",
          "#5041d6",
          "#c541d6"
        ]
      },
      "font": {
        "display": "Bodoni Moda",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "topo",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "subtle",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.54,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 0.65,
        "sub": 1.13
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "minor",
        "tempo": 64,
        "root": 140.41,
        "rhythm": "pulse",
        "brightness": 0.12,
        "seed": 1592
      }
    },
    "linen": {
      "name": "Linen & Ink",
      "bn": "textile natural editorial",
      "dark": false,
      "c": {
        "bg": [
          "#f0f6f9",
          "#cae3ec",
          "#92b3dc"
        ],
        "ink": "#291d18",
        "sub": "#86273d",
        "accent": "#1c37c8",
        "accentL": "#95a2e8",
        "accentD": "#152683",
        "accent2": "#86273d",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,100,217",
        "vig": "35,35,55",
        "palette": [
          "#41afd6",
          "#4841d6",
          "#bd41d6",
          "#d6417b",
          "#d67c41",
          "#bcd641"
        ]
      },
      "font": {
        "display": "Manrope",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "radial",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.71,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 0.8,
        "sub": 1.25
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 75,
        "root": 153.41,
        "rhythm": "waltz",
        "brightness": 0.225,
        "seed": 1629
      }
    },
    "stormfront": {
      "name": "Stormfront",
      "bn": "dramatic weather energy",
      "dark": true,
      "c": {
        "bg": [
          "#f9f0f4",
          "#eccad9",
          "#dc929d"
        ],
        "ink": "#182922",
        "sub": "#27862c",
        "accent": "#c8341c",
        "accentL": "#e8a195",
        "accentD": "#832415",
        "accent2": "#27862c",
        "onAccent": "#182922",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,97,78",
        "vig": "35,35,55",
        "palette": [
          "#d64184",
          "#d67341",
          "#c5d641",
          "#50d641",
          "#41d6a7",
          "#4190d6"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "none",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.88,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 0.95,
        "sub": 0.65
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "minor",
        "tempo": 86,
        "root": 166.41,
        "rhythm": "ostinato",
        "brightness": 0.33,
        "seed": 1666
      }
    },
    "hologram": {
      "name": "Holographic Prism",
      "bn": "iridescent holographic",
      "dark": false,
      "c": {
        "bg": [
          "#f1f9f0",
          "#cfecca",
          "#92dc9d"
        ],
        "ink": "#261829",
        "sub": "#472786",
        "accent": "#1cc866",
        "accentL": "#95e8b9",
        "accentD": "#158344",
        "accent2": "#472786",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,137",
        "vig": "35,35,55",
        "palette": [
          "#58d641",
          "#41d69f",
          "#4199d6",
          "#5e41d6",
          "#d341d6",
          "#d64165"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "subtle",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 1.05,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.1,
        "sub": 0.77
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "lydian",
        "tempo": 97,
        "root": 179.41,
        "rhythm": "arpeggio",
        "brightness": 0.435,
        "seed": 1703
      }
    },
    "antique": {
      "name": "Antique Bookplate",
      "bn": "antique engraved print",
      "dark": false,
      "c": {
        "bg": [
          "#f1f0f9",
          "#cecaec",
          "#b292dc"
        ],
        "ink": "#272918",
        "sub": "#866327",
        "accent": "#981cc8",
        "accentL": "#d195e8",
        "accentD": "#641583",
        "accent2": "#866327",
        "onAccent": "#272918",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "178,78,217",
        "vig": "35,35,55",
        "palette": [
          "#5541d6",
          "#ca41d6",
          "#d6416e",
          "#d68a41",
          "#aed641",
          "#41d649"
        ]
      },
      "font": {
        "display": "Libre Baskerville",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "mesh",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "radial",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 1.22,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 1.25,
        "sub": 0.89
      },
      "bgm": {
        "genre": "piano",
        "mode": "minor",
        "tempo": 108,
        "root": 192.41,
        "rhythm": "waltz",
        "brightness": 0.54,
        "seed": 1740
      }
    },
    "neonmetro": {
      "name": "Neon Metro",
      "bn": "urban transit at night",
      "dark": true,
      "c": {
        "bg": [
          "#f9f4f0",
          "#ecd8ca",
          "#dcc892"
        ],
        "ink": "#182229",
        "sub": "#27867f",
        "accent": "#c6c81c",
        "accentL": "#e7e895",
        "accentD": "#828315",
        "accent2": "#27867f",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "215,217,78",
        "vig": "35,35,55",
        "palette": [
          "#d68141",
          "#b7d641",
          "#42d641",
          "#41d6b5",
          "#4183d6",
          "#7541d6"
        ]
      },
      "font": {
        "display": "Sora",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.2,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 0.35,
        "sub": 1.01
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "dorian",
        "tempo": 119,
        "root": 205.41,
        "rhythm": "syncopated",
        "brightness": 0.645,
        "seed": 1777
      }
    },
    "saffron": {
      "name": "Saffron Ceremony",
      "bn": "spice market warmth",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f6",
          "#caece2",
          "#92dbdc"
        ],
        "ink": "#29181d",
        "sub": "#862771",
        "accent": "#1c94c8",
        "accentL": "#95cfe8",
        "accentD": "#156283",
        "accent2": "#862771",
        "onAccent": "#29181d",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,175,217",
        "vig": "35,35,55",
        "palette": [
          "#41d6ac",
          "#418bd6",
          "#6c41d6",
          "#d641cc",
          "#d64157",
          "#d6a041"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "subtle",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.37,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 0.5,
        "sub": 1.13
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 218.41,
        "rhythm": "ostinato",
        "brightness": 0.75,
        "seed": 1814
      }
    },
    "cloudstudy": {
      "name": "Cloud Study",
      "bn": "soft sky and airy forms",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f8",
          "#eccaec",
          "#dc92c5"
        ],
        "ink": "#182919",
        "sub": "#558627",
        "accent": "#c81c62",
        "accentL": "#e895b7",
        "accentD": "#831542",
        "accent2": "#558627",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,134",
        "vig": "35,35,55",
        "palette": [
          "#d641d5",
          "#d64160",
          "#d69741",
          "#a0d641",
          "#41d657",
          "#41d6cc"
        ]
      },
      "font": {
        "display": "Cormorant Garamond",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "radial",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.54,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 0.65,
        "sub": 1.25
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "major",
        "tempo": 58,
        "root": 231.41,
        "rhythm": "drone",
        "brightness": 0.855,
        "seed": 1851
      }
    },
    "cobalt": {
      "name": "Cobalt Atelier",
      "bn": "cobalt blue gallery",
      "dark": true,
      "c": {
        "bg": [
          "#f6f9f0",
          "#e2ecca",
          "#afdc92"
        ],
        "ink": "#1d1829",
        "sub": "#273986",
        "accent": "#30c81c",
        "accentL": "#9fe895",
        "accentD": "#218315",
        "accent2": "#273986",
        "onAccent": "#1d1829",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "94,217,78",
        "vig": "35,35,55",
        "palette": [
          "#a9d641",
          "#41d64e",
          "#41d6c3",
          "#4175d6",
          "#8241d6",
          "#d641b6"
        ]
      },
      "font": {
        "display": "DM Serif Display",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.71,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 0.8,
        "sub": 0.65
      },
      "bgm": {
        "genre": "bell",
        "mode": "lydian",
        "tempo": 69,
        "root": 94.41,
        "rhythm": "pulse",
        "brightness": 0.12,
        "seed": 1888
      }
    },
    "papercut": {
      "name": "Paper Cut Theatre",
      "bn": "layered paper silhouettes",
      "dark": false,
      "c": {
        "bg": [
          "#f0f3f9",
          "#cad8ec",
          "#929adc"
        ],
        "ink": "#292218",
        "sub": "#863027",
        "accent": "#3b1cc8",
        "accentL": "#a495e8",
        "accentD": "#291583",
        "accent2": "#863027",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "103,78,217",
        "vig": "35,35,55",
        "palette": [
          "#417ed6",
          "#7a41d6",
          "#d641be",
          "#d64149",
          "#d6ae41",
          "#8ad641"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "subtle",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.88,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 0.95,
        "sub": 0.77
      },
      "bgm": {
        "genre": "marimba",
        "mode": "pentatonic",
        "tempo": 80,
        "root": 107.41,
        "rhythm": "ostinato",
        "brightness": 0.225,
        "seed": 1925
      }
    },
    "frostedglass": {
      "name": "Frosted Glass",
      "bn": "translucent glass panels",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f1",
          "#eccace",
          "#dca092"
        ],
        "ink": "#182927",
        "sub": "#27864b",
        "accent": "#c86d1c",
        "accentL": "#e8bc95",
        "accentD": "#834915",
        "accent2": "#27864b",
        "onAccent": "#182927",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,143,78",
        "vig": "35,35,55",
        "palette": [
          "#d64152",
          "#d6a541",
          "#93d641",
          "#41d664",
          "#41d3d6",
          "#415ed6"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "radial",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 1.05,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 1.1,
        "sub": 0.89
      },
      "bgm": {
        "genre": "celesta",
        "mode": "major",
        "tempo": 91,
        "root": 120.41,
        "rhythm": "arpeggio",
        "brightness": 0.33,
        "seed": 1962
      }
    },
    "wildflower": {
      "name": "Wildflower Field",
      "bn": "meadow illustration",
      "dark": true,
      "c": {
        "bg": [
          "#f0f9f2",
          "#caecd0",
          "#92dcb6"
        ],
        "ink": "#291826",
        "sub": "#672786",
        "accent": "#1cc89f",
        "accentL": "#95e8d4",
        "accentD": "#158369",
        "accent2": "#672786",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,184",
        "vig": "35,35,55",
        "palette": [
          "#41d65c",
          "#41d6d1",
          "#4167d6",
          "#9041d6",
          "#d641a8",
          "#d64f41"
        ]
      },
      "font": {
        "display": "IBM Plex Sans",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "waves",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "none",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 1.22,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.25,
        "sub": 1.01
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "major",
        "tempo": 102,
        "root": 133.41,
        "rhythm": "waltz",
        "brightness": 0.435,
        "seed": 1999
      }
    },
    "blackvelvet": {
      "name": "Black Velvet",
      "bn": "luxury dark velvet",
      "dark": false,
      "c": {
        "bg": [
          "#f4f0f9",
          "#dacaec",
          "#cb92dc"
        ],
        "ink": "#212918",
        "sub": "#868327",
        "accent": "#c81cbf",
        "accentL": "#e895e4",
        "accentD": "#83157d",
        "accent2": "#868327",
        "onAccent": "#212918",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,210",
        "vig": "35,35,55",
        "palette": [
          "#8741d6",
          "#d641b1",
          "#d64741",
          "#d6bc41",
          "#7cd641",
          "#41d67b"
        ]
      },
      "font": {
        "display": "Bodoni Moda",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "topo",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "subtle",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.2,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 0.35,
        "sub": 1.13
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 113,
        "root": 146.41,
        "rhythm": "drone",
        "brightness": 0.54,
        "seed": 2036
      }
    },
    "sunprint": {
      "name": "Sunprint Cyanotype",
      "bn": "cyanotype photographic art",
      "dark": false,
      "c": {
        "bg": [
          "#f9f7f0",
          "#ece4ca",
          "#d8dc92"
        ],
        "ink": "#181c29",
        "sub": "#276d86",
        "accent": "#8dc81c",
        "accentL": "#cce895",
        "accentD": "#5d8315",
        "accent2": "#276d86",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "169,217,78",
        "vig": "35,35,55",
        "palette": [
          "#d6b341",
          "#85d641",
          "#41d672",
          "#41c6d6",
          "#4151d6",
          "#a641d6"
        ]
      },
      "font": {
        "display": "Manrope",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "radial",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.37,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 0.5,
        "sub": 1.25
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "dorian",
        "tempo": 124,
        "root": 159.41,
        "rhythm": "pulse",
        "brightness": 0.645,
        "seed": 2073
      }
    },
    "kineticred": {
      "name": "Kinetic Red",
      "bn": "bold red kinetic typography",
      "dark": true,
      "c": {
        "bg": [
          "#f0f8f9",
          "#caeaec",
          "#92c2dc"
        ],
        "ink": "#291918",
        "sub": "#862751",
        "accent": "#1c5bc8",
        "accentL": "#95b3e8",
        "accentD": "#153d83",
        "accent2": "#862751",
        "onAccent": "#291918",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,128,217",
        "vig": "35,35,55",
        "palette": [
          "#41ced6",
          "#4159d6",
          "#9e41d6",
          "#d6419a",
          "#d65d41",
          "#d6d241"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "none",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.54,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 0.65,
        "sub": 0.65
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "mixolydian",
        "tempo": 135,
        "root": 172.41,
        "rhythm": "syncopated",
        "brightness": 0.75,
        "seed": 2110
      }
    },
    "citrus": {
      "name": "Citrus Splash",
      "bn": "bright citrus shapes",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f6",
          "#eccae0",
          "#dc92ac"
        ],
        "ink": "#18291e",
        "sub": "#358627",
        "accent": "#c81c28",
        "accentL": "#e8959b",
        "accentD": "#83151d",
        "accent2": "#358627",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,88",
        "vig": "35,35,55",
        "palette": [
          "#d641a3",
          "#d65441",
          "#d6c941",
          "#6fd641",
          "#41d689",
          "#41afd6"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "subtle",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.71,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 0.8,
        "sub": 0.77
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "major",
        "tempo": 63,
        "root": 185.41,
        "rhythm": "pulse",
        "brightness": 0.855,
        "seed": 2147
      }
    },
    "geode": {
      "name": "Geode Crystal",
      "bn": "crystalline mineral layers",
      "dark": false,
      "c": {
        "bg": [
          "#f3f9f0",
          "#d6ecca",
          "#97dc92"
        ],
        "ink": "#231829",
        "sub": "#342786",
        "accent": "#1cc842",
        "accentL": "#95e8a8",
        "accentD": "#15832d",
        "accent2": "#342786",
        "onAccent": "#231829",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,109",
        "vig": "35,35,55",
        "palette": [
          "#77d641",
          "#41d680",
          "#41b8d6",
          "#4143d6",
          "#b441d6",
          "#d64184"
        ]
      },
      "font": {
        "display": "Libre Baskerville",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "mesh",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "radial",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.88,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 0.95,
        "sub": 0.89
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "lydian",
        "tempo": 74,
        "root": 198.41,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 2184
      }
    },
    "rainywindow": {
      "name": "Rainy Window",
      "bn": "rain streaks and reflections",
      "dark": true,
      "c": {
        "bg": [
          "#f0f1f9",
          "#caccec",
          "#a392dc"
        ],
        "ink": "#292818",
        "sub": "#864f27",
        "accent": "#741cc8",
        "accentL": "#c095e8",
        "accentD": "#4d1583",
        "accent2": "#864f27",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "149,78,217",
        "vig": "35,35,55",
        "palette": [
          "#414cd6",
          "#ab41d6",
          "#d6418c",
          "#d66b41",
          "#cdd641",
          "#58d641"
        ]
      },
      "font": {
        "display": "Sora",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.05,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 1.1,
        "sub": 1.01
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "minor",
        "tempo": 85,
        "root": 211.41,
        "rhythm": "drone",
        "brightness": 0.225,
        "seed": 2221
      }
    },
    "fable": {
      "name": "Storybook Fable",
      "bn": "illustrated storybook",
      "dark": false,
      "c": {
        "bg": [
          "#f9f2f0",
          "#ecd1ca",
          "#dcb992"
        ],
        "ink": "#182529",
        "sub": "#27866b",
        "accent": "#c8a71c",
        "accentL": "#e8d895",
        "accentD": "#836e15",
        "accent2": "#27866b",
        "onAccent": "#182529",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,190,78",
        "vig": "35,35,55",
        "palette": [
          "#d66241",
          "#d6d641",
          "#61d641",
          "#41d696",
          "#41a1d6",
          "#5641d6"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "subtle",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 1.22,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 1.25,
        "sub": 1.13
      },
      "bgm": {
        "genre": "harp",
        "mode": "major",
        "tempo": 96,
        "root": 224.41,
        "rhythm": "waltz",
        "brightness": 0.33,
        "seed": 2258
      }
    },
    "signalwave": {
      "name": "Signal Wave",
      "bn": "oscilloscope signal graphics",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f4",
          "#caecdb",
          "#92dcce"
        ],
        "ink": "#291820",
        "sub": "#862785",
        "accent": "#1cb8c8",
        "accentL": "#95e0e8",
        "accentD": "#157883",
        "accent2": "#862785",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,204,217",
        "vig": "35,35,55",
        "palette": [
          "#41d68e",
          "#41aad6",
          "#4d41d6",
          "#c241d6",
          "#d64176",
          "#d68141"
        ]
      },
      "font": {
        "display": "Cormorant Garamond",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "radial",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.2,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.35,
        "sub": 1.25
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "dorian",
        "tempo": 107,
        "root": 87.41,
        "rhythm": "syncopated",
        "brightness": 0.435,
        "seed": 2295
      }
    },
    "oldmoney": {
      "name": "Old Money Editorial",
      "bn": "quiet luxury editorial",
      "dark": true,
      "c": {
        "bg": [
          "#f7f0f9",
          "#e5caec",
          "#dc92d4"
        ],
        "ink": "#1c2918",
        "sub": "#698627",
        "accent": "#c81c86",
        "accentL": "#e895c8",
        "accentD": "#831558",
        "accent2": "#698627",
        "onAccent": "#1c2918",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,163",
        "vig": "35,35,55",
        "palette": [
          "#b941d6",
          "#d6417f",
          "#d67941",
          "#bfd641",
          "#4ad641",
          "#41d6ad"
        ]
      },
      "font": {
        "display": "DM Serif Display",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "none",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.37,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 0.5,
        "sub": 0.65
      },
      "bgm": {
        "genre": "piano",
        "mode": "minor",
        "tempo": 118,
        "root": 100.41,
        "rhythm": "ostinato",
        "brightness": 0.54,
        "seed": 2332
      }
    },
    "sundial": {
      "name": "Sundial Brass",
      "bn": "antique astronomy brass",
      "dark": false,
      "c": {
        "bg": [
          "#f8f9f0",
          "#e9ecca",
          "#bfdc92"
        ],
        "ink": "#1a1829",
        "sub": "#274d86",
        "accent": "#53c81c",
        "accentL": "#b0e895",
        "accentD": "#388315",
        "accent2": "#274d86",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "122,217,78",
        "vig": "35,35,55",
        "palette": [
          "#c8d641",
          "#53d641",
          "#41d6a4",
          "#4194d6",
          "#6341d6",
          "#d641d4"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "subtle",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.54,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 0.65,
        "sub": 0.77
      },
      "bgm": {
        "genre": "organ",
        "mode": "mixolydian",
        "tempo": 129,
        "root": 113.41,
        "rhythm": "waltz",
        "brightness": 0.645,
        "seed": 2369
      }
    },
    "cherrychrome": {
      "name": "Cherry Chrome",
      "bn": "red chrome pop",
      "dark": false,
      "c": {
        "bg": [
          "#f0f5f9",
          "#cadfec",
          "#92a9dc"
        ],
        "ink": "#291f18",
        "sub": "#862731",
        "accent": "#1c21c8",
        "accentL": "#9598e8",
        "accentD": "#151883",
        "accent2": "#862731",
        "onAccent": "#291f18",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,82,217",
        "vig": "35,35,55",
        "palette": [
          "#419cd6",
          "#5b41d6",
          "#d041d6",
          "#d64168",
          "#d68f41",
          "#a9d641"
        ]
      },
      "font": {
        "display": "Playfair Display",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "radial",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.71,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 0.8,
        "sub": 0.89
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "minor",
        "tempo": 57,
        "root": 126.41,
        "rhythm": "pulse",
        "brightness": 0.75,
        "seed": 2406
      }
    },
    "cloisonne": {
      "name": "Cloisonne Enamel",
      "bn": "jewel-like enamel outlines",
      "dark": true,
      "c": {
        "bg": [
          "#f9f0f3",
          "#eccad5",
          "#dc9293"
        ],
        "ink": "#182924",
        "sub": "#278638",
        "accent": "#c84a1c",
        "accentL": "#e8ab95",
        "accentD": "#833215",
        "accent2": "#278638",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,114,78",
        "vig": "35,35,55",
        "palette": [
          "#d64171",
          "#d68641",
          "#b2d641",
          "#41d646",
          "#41d6ba",
          "#417dd6"
        ]
      },
      "font": {
        "display": "IBM Plex Sans",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "waves",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "none",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.88,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 0.95,
        "sub": 1.01
      },
      "bgm": {
        "genre": "bell",
        "mode": "pentatonic",
        "tempo": 68,
        "root": 139.41,
        "rhythm": "arpeggio",
        "brightness": 0.855,
        "seed": 2443
      }
    },
    "nightgarden": {
      "name": "Night Garden",
      "bn": "nocturnal botanical",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f0",
          "#cbecca",
          "#92dca6"
        ],
        "ink": "#281829",
        "sub": "#542786",
        "accent": "#1cc87c",
        "accentL": "#95e8c3",
        "accentD": "#158352",
        "accent2": "#542786",
        "onAccent": "#281829",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,155",
        "vig": "35,35,55",
        "palette": [
          "#45d641",
          "#41d6b2",
          "#4186d6",
          "#7141d6",
          "#d641c7",
          "#d64152"
        ]
      },
      "font": {
        "display": "Bodoni Moda",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "topo",
        "frame": "thin",
        "orn": "diamond",
        "chip": "glass",
        "rule": "orn",
        "rays": "subtle",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 1.05,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.78,
        "bright": 1.1,
        "sub": 1.13
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "dorian",
        "tempo": 79,
        "root": 152.41,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 2480
      }
    },
    "chalkboard": {
      "name": "Chalkboard Studio",
      "bn": "chalk and hand lettering",
      "dark": false,
      "c": {
        "bg": [
          "#f2f0f9",
          "#d3caec",
          "#bc92dc"
        ],
        "ink": "#252918",
        "sub": "#866f27",
        "accent": "#ae1cc8",
        "accentL": "#dc95e8",
        "accentD": "#721583",
        "accent2": "#866f27",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "196,78,217",
        "vig": "35,35,55",
        "palette": [
          "#6841d6",
          "#d641cf",
          "#d6415a",
          "#d69d41",
          "#9bd641",
          "#41d65c"
        ]
      },
      "font": {
        "display": "Manrope",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "editorial",
        "orn": "square",
        "chip": "solid",
        "rule": "line",
        "rays": "radial",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.22,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 0.85,
        "bright": 1.25,
        "sub": 1.25
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "mixolydian",
        "tempo": 90,
        "root": 165.41,
        "rhythm": "pulse",
        "brightness": 0.225,
        "seed": 2517
      }
    },
    "topographic": {
      "name": "Topographic Lines",
      "bn": "contour-map landscape",
      "dark": true,
      "c": {
        "bg": [
          "#f9f5f0",
          "#ecddca",
          "#dcd192"
        ],
        "ink": "#182029",
        "sub": "#278186",
        "accent": "#b0c81c",
        "accentL": "#dde895",
        "accentD": "#748315",
        "accent2": "#278186",
        "onAccent": "#182029",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "198,217,78",
        "vig": "35,35,55",
        "palette": [
          "#d69441",
          "#a4d641",
          "#41d653",
          "#41d6c8",
          "#4170d6",
          "#8841d6"
        ]
      },
      "font": {
        "display": "Fraunces",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "spark",
        "chip": "outline",
        "rule": "dots",
        "rays": "none",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.92,
        "bright": 0.35,
        "sub": 0.65
      },
      "bgm": {
        "genre": "handpan",
        "mode": "minor",
        "tempo": 101,
        "root": 178.41,
        "rhythm": "ostinato",
        "brightness": 0.33,
        "seed": 2554
      }
    },
    "prismatica": {
      "name": "Prismatica",
      "bn": "prismatic light refraction",
      "dark": false,
      "c": {
        "bg": [
          "#f0f9f7",
          "#caece7",
          "#92d1dc"
        ],
        "ink": "#29181b",
        "sub": "#862765",
        "accent": "#1c7ec8",
        "accentL": "#95c5e8",
        "accentD": "#155483",
        "accent2": "#862765",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,157,217",
        "vig": "35,35,55",
        "palette": [
          "#41d6c0",
          "#4178d6",
          "#7f41d6",
          "#d641b9",
          "#d64144",
          "#d6b341"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "double",
        "orn": "star",
        "chip": "paper",
        "rule": "double",
        "rays": "subtle",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 0.37,
        "motion": "snappy",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.5,
        "sub": 0.77
      },
      "bgm": {
        "genre": "celesta",
        "mode": "lydian",
        "tempo": 112,
        "root": 191.41,
        "rhythm": "arpeggio",
        "brightness": 0.435,
        "seed": 2591
      }
    },
    "vinyljazz": {
      "name": "Vinyl Jazz Club",
      "bn": "warm jazz record sleeve",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f7",
          "#eccae7",
          "#dc92bc"
        ],
        "ink": "#18291b",
        "sub": "#498627",
        "accent": "#c81c4c",
        "accentL": "#e895ac",
        "accentD": "#831534",
        "accent2": "#498627",
        "onAccent": "#18291b",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,78,116",
        "vig": "35,35,55",
        "palette": [
          "#d641c2",
          "#d6414d",
          "#d6aa41",
          "#8dd641",
          "#41d66a",
          "#41ced6"
        ]
      },
      "font": {
        "display": "Libre Baskerville",
        "body": "Manrope",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "mesh",
        "frame": "rounded",
        "orn": "tri",
        "chip": "glass",
        "rule": "orn",
        "rays": "radial",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.54,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.06,
        "bright": 0.65,
        "sub": 0.89
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "dorian",
        "tempo": 123,
        "root": 204.41,
        "rhythm": "waltz",
        "brightness": 0.54,
        "seed": 2628
      }
    },
    "sugarcube": {
      "name": "Sugarcube Pop",
      "bn": "bright candy geometry",
      "dark": true,
      "c": {
        "bg": [
          "#f5f9f0",
          "#ddecca",
          "#a6dc92"
        ],
        "ink": "#201829",
        "sub": "#272d86",
        "accent": "#1cc81f",
        "accentL": "#95e896",
        "accentD": "#158316",
        "accent2": "#272d86",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "78,217,80",
        "vig": "35,35,55",
        "palette": [
          "#96d641",
          "#41d661",
          "#41d6d6",
          "#4162d6",
          "#9541d6",
          "#d641a3"
        ]
      },
      "font": {
        "display": "Sora",
        "body": "Inter",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "technical",
        "orn": "circle",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.71,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.13,
        "bright": 0.8,
        "sub": 1.01
      },
      "bgm": {
        "genre": "marimba",
        "mode": "major",
        "tempo": 134,
        "root": 217.41,
        "rhythm": "syncopated",
        "brightness": 0.645,
        "seed": 2665
      }
    },
    "obsidian": {
      "name": "Obsidian & Gold",
      "bn": "obsidian luxury",
      "dark": false,
      "c": {
        "bg": [
          "#f0f2f9",
          "#cad3ec",
          "#9492dc"
        ],
        "ink": "#292418",
        "sub": "#863c27",
        "accent": "#511cc8",
        "accentL": "#af95e8",
        "accentD": "#371583",
        "accent2": "#863c27",
        "onAccent": "#292418",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "120,78,217",
        "vig": "35,35,55",
        "palette": [
          "#416bd6",
          "#8d41d6",
          "#d641ab",
          "#d64c41",
          "#d6c141",
          "#77d641"
        ]
      },
      "font": {
        "display": "Archivo",
        "body": "Space Grotesk",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "corner",
        "orn": "moon",
        "chip": "outline",
        "rule": "dots",
        "rays": "subtle",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.88,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.2,
        "bright": 0.95,
        "sub": 1.13
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "minor",
        "tempo": 62,
        "root": 230.41,
        "rhythm": "drone",
        "brightness": 0.75,
        "seed": 2702
      }
    },
    "kinfolk": {
      "name": "Kinfolk Natural",
      "bn": "warm natural minimal",
      "dark": false,
      "c": {
        "bg": [
          "#f9f0f0",
          "#eccaca",
          "#dca992"
        ],
        "ink": "#182929",
        "sub": "#278658",
        "accent": "#c8831c",
        "accentL": "#e8c795",
        "accentD": "#835715",
        "accent2": "#278658",
        "onAccent": "#ffffff",
        "chip": "rgba(255,255,255,0.72)",
        "halo": "245,240,255",
        "glow": "217,161,78",
        "vig": "35,35,55",
        "palette": [
          "#d64341",
          "#d6b841",
          "#80d641",
          "#41d678",
          "#41c0d6",
          "#414bd6"
        ]
      },
      "font": {
        "display": "Cormorant Garamond",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "deco",
        "orn": "drop",
        "chip": "paper",
        "rule": "double",
        "rays": "radial",
        "particles": "none",
        "arch": "angled",
        "upper": false,
        "ls": 1.05,
        "motion": "reveal",
        "spot": true
      },
      "sfx": {
        "pitch": 1.27,
        "bright": 1.1,
        "sub": 1.25
      },
      "bgm": {
        "genre": "guitar",
        "mode": "pentatonic",
        "tempo": 73,
        "root": 93.41,
        "rhythm": "pulse",
        "brightness": 0.855,
        "seed": 2739
      }
    },
    "atlasa": {
      "name": "Atlas A — Mapmaking",
      "bn": "Atlas A — mapmaking",
      "dark": true,
      "c": {
        "bg": [
          "#6b4747",
          "#382c29",
          "#291c20"
        ],
        "ink": "#f7f4ed",
        "sub": "#b28f59",
        "accent": "#42ebd6",
        "accentL": "#f5b1a2",
        "accentD": "#a9b84d",
        "accent2": "#a9b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,37,37",
        "glow": "65,234,214",
        "vig": "0,0,0",
        "palette": [
          "#42ebd6",
          "#a9b84d",
          "#b28f59",
          "#f5b1a2",
          "#4c51d9",
          "#53c740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.45,
        "sub": 0.65
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 52,
        "root": 73.42,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10000
      }
    },
    "atlasb": {
      "name": "Atlas B — Mapmaking",
      "bn": "Atlas B — mapmaking",
      "dark": false,
      "c": {
        "bg": [
          "#6fd68d",
          "#65a384",
          "#2a492a"
        ],
        "ink": "#171923",
        "sub": "#59b2a9",
        "accent": "#eb42ce",
        "accentL": "#a2f5c9",
        "accentD": "#4d8ab8",
        "accent2": "#4d8ab8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,163,107",
        "glow": "234,65,205",
        "vig": "70,45,20",
        "palette": [
          "#eb42ce",
          "#4d8ab8",
          "#59b2a9",
          "#a2f5c9",
          "#d96f4c",
          "#5440c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.37,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.56,
        "sub": 0.77
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 65,
        "root": 90.73,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10001
      }
    },
    "atlasc": {
      "name": "Atlas C — Mapmaking",
      "bn": "Atlas C — mapmaking",
      "dark": true,
      "c": {
        "bg": [
          "#4f296b",
          "#321c38",
          "#191229"
        ],
        "ink": "#f7f4ed",
        "sub": "#b259a2",
        "accent": "#9ceb42",
        "accentL": "#e1a2f5",
        "accentD": "#b84d6b",
        "accent2": "#b84d6b",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "41,21,56",
        "glow": "156,234,65",
        "vig": "0,0,0",
        "palette": [
          "#9ceb42",
          "#b84d6b",
          "#b259a2",
          "#e1a2f5",
          "#4cd998",
          "#c77c40"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 0.54,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.67,
        "sub": 0.89
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 78,
        "root": 108.04,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10002
      }
    },
    "atlasd": {
      "name": "Atlas D — Mapmaking",
      "bn": "Atlas D — mapmaking",
      "dark": false,
      "c": {
        "bg": [
          "#d6c238",
          "#9ba343",
          "#493619"
        ],
        "ink": "#171923",
        "sub": "#88b259",
        "accent": "#426beb",
        "accentL": "#f0f5a2",
        "accentD": "#4db84f",
        "accent2": "#4db84f",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,148,42",
        "glow": "65,107,234",
        "vig": "70,45,20",
        "palette": [
          "#426beb",
          "#4db84f",
          "#88b259",
          "#f0f5a2",
          "#c24cd9",
          "#40c7a3"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "fw": 12,
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 0.71,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.78,
        "sub": 1.01
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 91,
        "root": 125.35,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10003
      }
    },
    "atlase": {
      "name": "Atlas E — Mapmaking",
      "bn": "Atlas E — mapmaking",
      "dark": true,
      "c": {
        "bg": [
          "#0f5c6b",
          "#122a38",
          "#092926"
        ],
        "ink": "#f7f4ed",
        "sub": "#596eb2",
        "accent": "#eb4a42",
        "accentL": "#a2d8f5",
        "accentD": "#6e4db8",
        "accent2": "#6e4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,48,56",
        "glow": "234,73,65",
        "vig": "0,0,0",
        "palette": [
          "#eb4a42",
          "#6e4db8",
          "#596eb2",
          "#a2d8f5",
          "#c7d94c",
          "#c740c3"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "fw": 2,
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 0.88,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.89,
        "sub": 1.13
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 104,
        "root": 142.66,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10004
      }
    },
    "atlasf": {
      "name": "Atlas F — Mapmaking",
      "bn": "Atlas F — mapmaking",
      "dark": false,
      "c": {
        "bg": [
          "#d68db5",
          "#a37786",
          "#493345"
        ],
        "ink": "#171923",
        "sub": "#b25f59",
        "accent": "#42eb7b",
        "accentL": "#f5a2c0",
        "accentD": "#b88d4d",
        "accent2": "#b88d4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,107,137",
        "glow": "65,234,122",
        "vig": "70,45,20",
        "palette": [
          "#42eb7b",
          "#b88d4d",
          "#b25f59",
          "#f5a2c0",
          "#4c9ed9",
          "#9cc740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 1.05,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.0,
        "sub": 1.25
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 117,
        "root": 159.97,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10005
      }
    },
    "atlasg": {
      "name": "Atlas G — Mapmaking",
      "bn": "Atlas G — mapmaking",
      "dark": true,
      "c": {
        "bg": [
          "#456b38",
          "#233823",
          "#202917"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b279",
        "accent": "#ac42eb",
        "accentL": "#a7f5a2",
        "accentD": "#4db8ac",
        "accent2": "#4db8ac",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "35,56,29",
        "glow": "172,65,234",
        "vig": "0,0,0",
        "palette": [
          "#ac42eb",
          "#4db8ac",
          "#59b279",
          "#a7f5a2",
          "#d94c75",
          "#4074c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 1.22,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.11,
        "sub": 1.37
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 130,
        "root": 177.28,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10006
      }
    },
    "atlash": {
      "name": "Atlas H — Mapmaking",
      "bn": "Atlas H — mapmaking",
      "dark": false,
      "c": {
        "bg": [
          "#5751d6",
          "#6752a3",
          "#202a49"
        ],
        "ink": "#171923",
        "sub": "#9359b2",
        "accent": "#ebde42",
        "accentL": "#b4a2f5",
        "accentD": "#b84da4",
        "accent2": "#b84da4",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "66,62,163",
        "glow": "234,221,65",
        "vig": "70,45,20",
        "palette": [
          "#ebde42",
          "#b84da4",
          "#9359b2",
          "#b4a2f5",
          "#4cd94c",
          "#c7404d"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 1.39,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.22,
        "sub": 0.65
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 52,
        "root": 194.59,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10007
      }
    },
    "atlasi": {
      "name": "Atlas I — Mapmaking",
      "bn": "Atlas I — mapmaking",
      "dark": true,
      "c": {
        "bg": [
          "#6b361c",
          "#382917",
          "#290f0e"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2ad59",
        "accent": "#42c6eb",
        "accentL": "#f5cca2",
        "accentD": "#85b84d",
        "accent2": "#85b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,28,14",
        "glow": "65,198,234",
        "vig": "0,0,0",
        "palette": [
          "#42c6eb",
          "#85b84d",
          "#b2ad59",
          "#f5cca2",
          "#754cd9",
          "#40c75a"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 1.56,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.33,
        "sub": 0.77
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 65,
        "root": 211.9,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10008
      }
    },
    "atlasj": {
      "name": "Atlas J — Mapmaking",
      "bn": "Atlas J — mapmaking",
      "dark": false,
      "c": {
        "bg": [
          "#1ed691",
          "#33a391",
          "#114925"
        ],
        "ink": "#171923",
        "sub": "#599eb2",
        "accent": "#eb4295",
        "accentL": "#a2f5e5",
        "accentD": "#4d66b8",
        "accent2": "#4d66b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,163,110",
        "glow": "234,65,149",
        "vig": "70,45,20",
        "palette": [
          "#eb4295",
          "#4d66b8",
          "#599eb2",
          "#a2f5e5",
          "#d99e4c",
          "#8140c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 0.2,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.44,
        "sub": 0.89
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 78,
        "root": 79.21,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10009
      }
    },
    "dialoguea": {
      "name": "Dialogue A — Conversation",
      "bn": "Dialogue A — conversation",
      "dark": true,
      "c": {
        "bg": [
          "#6b4767",
          "#382933",
          "#271c29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25974",
        "accent": "#45eb42",
        "accentL": "#f5a2dd",
        "accentD": "#b8674d",
        "accent2": "#b8674d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,37,54",
        "glow": "68,234,65",
        "vig": "0,0,0",
        "palette": [
          "#45eb42",
          "#b8674d",
          "#b25974",
          "#f5a2dd",
          "#4cd0d9",
          "#c7c240"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 0.37,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.55,
        "sub": 1.01
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 91,
        "root": 96.52,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10010
      }
    },
    "dialogueb": {
      "name": "Dialogue B — Conversation",
      "bn": "Dialogue B — conversation",
      "dark": false,
      "c": {
        "bg": [
          "#aed66f",
          "#7da365",
          "#46492a"
        ],
        "ink": "#171923",
        "sub": "#5ab259",
        "accent": "#7042eb",
        "accentL": "#c5f5a2",
        "accentD": "#4db886",
        "accent2": "#4db886",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "132,163,84",
        "glow": "111,65,234",
        "vig": "70,45,20",
        "palette": [
          "#7042eb",
          "#4db886",
          "#5ab259",
          "#c5f5a2",
          "#d94ca7",
          "#40a5c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 0.54,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.45,
        "sub": 1.13
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 104,
        "root": 113.83,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10011
      }
    },
    "dialoguec": {
      "label": "Editorial Swiss",
      "dark": true,
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 0.71,
        "motion": "stagger",
        "spot": false
      },
      "c": {
        "bg": [
          "#293e6b",
          "#1c1f38",
          "#121f29"
        ],
        "ink": "#f7f4ed",
        "sub": "#7359b2",
        "accent": "#eba142",
        "accentL": "#a2adf5",
        "accentD": "#a54db8",
        "accent2": "#a54db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,32,56",
        "glow": "234,161,65",
        "vig": "0,0,0",
        "palette": [
          "#eba142",
          "#a54db8",
          "#7359b2",
          "#a2adf5",
          "#7ed94c",
          "#c7407d"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "name": "Dialogue C — Conversation",
      "bn": "Dialogue C — conversation",
      "sfx": {
        "pitch": 1.26,
        "bright": 0.56,
        "sub": 1.25
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 117,
        "root": 131.14,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10012
      }
    },
    "dialogued": {
      "label": "Cyberpunk",
      "dark": false,
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 0.88,
        "motion": "pulse",
        "spot": true
      },
      "c": {
        "bg": [
          "#d6383b",
          "#a35543",
          "#491927"
        ],
        "ink": "#171923",
        "sub": "#b28d59",
        "accent": "#42ebd2",
        "accentL": "#f5afa2",
        "accentD": "#abb84d",
        "accent2": "#abb84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,42,45",
        "glow": "65,234,210",
        "vig": "70,45,20",
        "palette": [
          "#42ebd2",
          "#abb84d",
          "#b28d59",
          "#f5afa2",
          "#4c55d9",
          "#56c740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Dialogue D — Conversation",
      "bn": "Dialogue D — conversation",
      "sfx": {
        "pitch": 0.72,
        "bright": 0.67,
        "sub": 1.37
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 130,
        "root": 148.45,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10013
      }
    },
    "dialoguee": {
      "label": "Forest Field",
      "dark": true,
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 1.05,
        "motion": "float",
        "spot": true
      },
      "c": {
        "bg": [
          "#0f6b28",
          "#123824",
          "#092909"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b2a7",
        "accent": "#eb42d2",
        "accentL": "#a2f5c7",
        "accentD": "#4d8cb8",
        "accent2": "#4d8cb8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,56,20",
        "glow": "234,65,209",
        "vig": "0,0,0",
        "palette": [
          "#eb42d2",
          "#4d8cb8",
          "#59b2a7",
          "#a2f5c7",
          "#d96c4c",
          "#5140c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Dialogue E — Conversation",
      "bn": "Dialogue E — conversation",
      "sfx": {
        "pitch": 0.765,
        "bright": 0.78,
        "sub": 0.65
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 52,
        "root": 165.76,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10014
      }
    },
    "dialoguef": {
      "label": "Blueprint",
      "dark": false,
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 1.22,
        "motion": "parallax",
        "spot": false
      },
      "c": {
        "bg": [
          "#b68dd6",
          "#9977a3",
          "#393349"
        ],
        "ink": "#171923",
        "sub": "#b259a4",
        "accent": "#a0eb42",
        "accentL": "#dfa2f5",
        "accentD": "#b84d6d",
        "accent2": "#b84d6d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "138,107,163",
        "glow": "160,234,65",
        "vig": "70,45,20",
        "palette": [
          "#a0eb42",
          "#b84d6d",
          "#b259a4",
          "#dfa2f5",
          "#4cd995",
          "#c77840"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "name": "Dialogue F — Conversation",
      "bn": "Dialogue F — conversation",
      "sfx": {
        "pitch": 0.81,
        "bright": 0.89,
        "sub": 0.77
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 65,
        "root": 183.07,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10015
      }
    },
    "dialogueg": {
      "label": "Candy Pop",
      "dark": true,
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 1.39,
        "motion": "rise",
        "spot": true
      },
      "c": {
        "bg": [
          "#6b6338",
          "#373823",
          "#292117"
        ],
        "ink": "#f7f4ed",
        "sub": "#8ab259",
        "accent": "#426feb",
        "accentL": "#f2f5a2",
        "accentD": "#4eb84d",
        "accent2": "#4eb84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,52,29",
        "glow": "65,110,234",
        "vig": "0,0,0",
        "palette": [
          "#426feb",
          "#4eb84d",
          "#8ab259",
          "#f2f5a2",
          "#be4cd9",
          "#40c7a0"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Dialogue G — Conversation",
      "bn": "Dialogue G — conversation",
      "sfx": {
        "pitch": 0.855,
        "bright": 1.0,
        "sub": 0.89
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 78,
        "root": 200.38,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10016
      }
    },
    "dialogueh": {
      "label": "Volcanic",
      "dark": false,
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 1.56,
        "motion": "snap",
        "spot": true
      },
      "c": {
        "bg": [
          "#51c3d6",
          "#5287a3",
          "#204944"
        ],
        "ink": "#171923",
        "sub": "#5970b2",
        "accent": "#eb4642",
        "accentL": "#a2daf5",
        "accentD": "#6b4db8",
        "accent2": "#6b4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,148,163",
        "glow": "234,69,65",
        "vig": "70,45,20",
        "palette": [
          "#eb4642",
          "#6b4db8",
          "#5970b2",
          "#a2daf5",
          "#cad94c",
          "#c740c6"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Dialogue H — Conversation",
      "bn": "Dialogue H — conversation",
      "sfx": {
        "pitch": 0.9,
        "bright": 1.11,
        "sub": 1.01
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 91,
        "root": 217.69,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10017
      }
    },
    "dialoguei": {
      "label": "Arctic Glass",
      "dark": true,
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 0.2,
        "motion": "drift",
        "spot": false
      },
      "c": {
        "bg": [
          "#6b1c49",
          "#381723",
          "#290e24"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25c59",
        "accent": "#42eb77",
        "accentL": "#f5a2c2",
        "accentD": "#b88a4d",
        "accent2": "#b88a4d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,14,38",
        "glow": "65,234,119",
        "vig": "0,0,0",
        "palette": [
          "#42eb77",
          "#b88a4d",
          "#b25c59",
          "#f5a2c2",
          "#4ca1d9",
          "#9fc740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "name": "Dialogue I — Conversation",
      "bn": "Dialogue I — conversation",
      "sfx": {
        "pitch": 0.945,
        "bright": 1.22,
        "sub": 1.13
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 104,
        "root": 85.0,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10018
      }
    },
    "dialoguej": {
      "label": "Newspaper",
      "dark": false,
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 0.37,
        "motion": "orbit",
        "spot": true
      },
      "c": {
        "bg": [
          "#50d61e",
          "#3aa333",
          "#2f4911"
        ],
        "ink": "#171923",
        "sub": "#59b276",
        "accent": "#a842eb",
        "accentL": "#a9f5a2",
        "accentD": "#4db8a9",
        "accent2": "#4db8a9",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "61,163,22",
        "glow": "168,65,234",
        "vig": "70,45,20",
        "palette": [
          "#a842eb",
          "#4db8a9",
          "#59b276",
          "#a9f5a2",
          "#d94c78",
          "#4077c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Dialogue J — Conversation",
      "bn": "Dialogue J — conversation",
      "sfx": {
        "pitch": 0.99,
        "bright": 1.33,
        "sub": 1.25
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 117,
        "root": 102.31,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10019
      }
    },
    "scholara": {
      "label": "Royal Blue",
      "dark": true,
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.54,
        "motion": "smooth",
        "spot": true
      },
      "c": {
        "bg": [
          "#4e476b",
          "#2f2938",
          "#1c1d29"
        ],
        "ink": "#f7f4ed",
        "sub": "#a159b2",
        "accent": "#ddeb42",
        "accentL": "#c1a2f5",
        "accentD": "#b84d93",
        "accent2": "#b84d93",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "40,37,56",
        "glow": "220,234,65",
        "vig": "0,0,0",
        "palette": [
          "#ddeb42",
          "#b84d93",
          "#a159b2",
          "#c1a2f5",
          "#4cd963",
          "#c74840"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Scholar A — Learning",
      "bn": "Scholar A — learning",
      "sfx": {
        "pitch": 1.035,
        "bright": 1.44,
        "sub": 1.37
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 130,
        "root": 119.62,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10020
      }
    },
    "scholarb": {
      "label": "Retro Print",
      "dark": false,
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.71,
        "motion": "kinetic",
        "spot": false
      },
      "c": {
        "bg": [
          "#d6a26f",
          "#a39165",
          "#49312a"
        ],
        "ink": "#171923",
        "sub": "#aab259",
        "accent": "#42abeb",
        "accentL": "#f5daa2",
        "accentD": "#74b84d",
        "accent2": "#74b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,123,84",
        "glow": "65,171,234",
        "vig": "70,45,20",
        "palette": [
          "#42abeb",
          "#74b84d",
          "#aab259",
          "#f5daa2",
          "#8c4cd9",
          "#40c770"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "name": "Scholar B — Learning",
      "bn": "Scholar B — learning",
      "sfx": {
        "pitch": 1.08,
        "bright": 1.55,
        "sub": 0.65
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 52,
        "root": 136.93,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10021
      }
    },
    "scholarc": {
      "label": "Minimal Studio",
      "dark": true,
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 0.88,
        "motion": "stagger",
        "spot": true
      },
      "c": {
        "bg": [
          "#296b5d",
          "#1c3838",
          "#12291e"
        ],
        "ink": "#f7f4ed",
        "sub": "#5990b2",
        "accent": "#eb427a",
        "accentL": "#a2f5f2",
        "accentD": "#4d55b8",
        "accent2": "#4d55b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,56,48",
        "glow": "234,65,122",
        "vig": "0,0,0",
        "palette": [
          "#eb427a",
          "#4d55b8",
          "#5990b2",
          "#a2f5f2",
          "#d9b54c",
          "#9740c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Scholar C — Learning",
      "bn": "Scholar C — learning",
      "sfx": {
        "pitch": 1.125,
        "bright": 0.45,
        "sub": 0.77
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 65,
        "root": 154.24,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10022
      }
    },
    "scholard": {
      "label": "Cosmic Dream",
      "dark": false,
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 1.05,
        "motion": "pulse",
        "spot": true
      },
      "c": {
        "bg": [
          "#d638ca",
          "#a34387",
          "#401949"
        ],
        "ink": "#171923",
        "sub": "#b25976",
        "accent": "#49eb42",
        "accentL": "#f5a2df",
        "accentD": "#b8644d",
        "accent2": "#b8644d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,42,153",
        "glow": "72,234,65",
        "vig": "70,45,20",
        "palette": [
          "#49eb42",
          "#b8644d",
          "#b25976",
          "#f5a2df",
          "#4cd3d9",
          "#c7bf40"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Scholar D — Learning",
      "bn": "Scholar D — learning",
      "sfx": {
        "pitch": 1.17,
        "bright": 0.56,
        "sub": 0.89
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 78,
        "root": 171.55,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10023
      }
    },
    "scholare": {
      "name": "Scholar E — Learning",
      "bn": "Scholar E — learning",
      "dark": true,
      "c": {
        "bg": [
          "#496b0f",
          "#223812",
          "#262909"
        ],
        "ink": "#f7f4ed",
        "sub": "#5cb259",
        "accent": "#6c42eb",
        "accentL": "#c7f5a2",
        "accentD": "#4db883",
        "accent2": "#4db883",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "38,56,7",
        "glow": "107,65,234",
        "vig": "0,0,0",
        "palette": [
          "#6c42eb",
          "#4db883",
          "#5cb259",
          "#c7f5a2",
          "#d94caa",
          "#40a8c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 1.22,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.67,
        "sub": 1.01
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 91,
        "root": 188.86,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10024
      }
    },
    "scholarf": {
      "name": "Scholar F — Learning",
      "bn": "Scholar F — learning",
      "dark": false,
      "c": {
        "bg": [
          "#8da6d6",
          "#777da3",
          "#334149"
        ],
        "ink": "#171923",
        "sub": "#7159b2",
        "accent": "#eb9d42",
        "accentL": "#a2aff5",
        "accentD": "#a24db8",
        "accent2": "#a24db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,126,163",
        "glow": "234,157,65",
        "vig": "70,45,20",
        "palette": [
          "#eb9d42",
          "#a24db8",
          "#7159b2",
          "#a2aff5",
          "#81d94c",
          "#c74080"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 1.39,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.78,
        "sub": 1.13
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 104,
        "root": 206.17,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10025
      }
    },
    "scholarg": {
      "name": "Scholar G — Learning",
      "bn": "Scholar G — learning",
      "dark": true,
      "c": {
        "bg": [
          "#6b383a",
          "#382623",
          "#29171d"
        ],
        "ink": "#f7f4ed",
        "sub": "#b28b59",
        "accent": "#42ebce",
        "accentL": "#f5ada2",
        "accentD": "#aeb84d",
        "accent2": "#aeb84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,29,30",
        "glow": "65,234,206",
        "vig": "0,0,0",
        "palette": [
          "#42ebce",
          "#aeb84d",
          "#b28b59",
          "#f5ada2",
          "#4c58d9",
          "#59c740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 1.56,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.89,
        "sub": 1.25
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 117,
        "root": 73.48,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10026
      }
    },
    "scholarh": {
      "name": "Scholar H — Learning",
      "bn": "Scholar H — learning",
      "dark": false,
      "c": {
        "bg": [
          "#51d672",
          "#52a377",
          "#214920"
        ],
        "ink": "#171923",
        "sub": "#59b2a5",
        "accent": "#eb42d5",
        "accentL": "#a2f5c5",
        "accentD": "#4d8fb8",
        "accent2": "#4d8fb8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,163,86",
        "glow": "234,65,213",
        "vig": "70,45,20",
        "palette": [
          "#eb42d5",
          "#4d8fb8",
          "#59b2a5",
          "#a2f5c5",
          "#d9694c",
          "#4e40c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.2,
        "motion": "snap",
        "spot": false
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.0,
        "sub": 1.37
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 90.79,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10027
      }
    },
    "scholari": {
      "name": "Scholar I — Learning",
      "bn": "Scholar I — learning",
      "dark": true,
      "c": {
        "bg": [
          "#461c6b",
          "#301738",
          "#150e29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b259a6",
        "accent": "#a4eb42",
        "accentL": "#dda2f5",
        "accentD": "#b84d70",
        "accent2": "#b84d70",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "36,14,56",
        "glow": "164,234,65",
        "vig": "0,0,0",
        "palette": [
          "#a4eb42",
          "#b84d70",
          "#b259a6",
          "#dda2f5",
          "#4cd992",
          "#c77540"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 0.37,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.11,
        "sub": 0.65
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 52,
        "root": 108.1,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10028
      }
    },
    "scholarj": {
      "name": "Scholar J — Learning",
      "bn": "Scholar J — learning",
      "dark": false,
      "c": {
        "bg": [
          "#d6b71e",
          "#9fa333",
          "#493011"
        ],
        "ink": "#171923",
        "sub": "#8cb259",
        "accent": "#4273eb",
        "accentL": "#f4f5a2",
        "accentD": "#50b84d",
        "accent2": "#50b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,139,22",
        "glow": "65,114,234",
        "vig": "70,45,20",
        "palette": [
          "#4273eb",
          "#50b84d",
          "#8cb259",
          "#f4f5a2",
          "#bb4cd9",
          "#40c79d"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 0.54,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.22,
        "sub": 0.77
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 65,
        "root": 125.41,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10029
      }
    },
    "chroniclea": {
      "name": "Chronicle A — History",
      "bn": "Chronicle A — history",
      "dark": true,
      "c": {
        "bg": [
          "#47606b",
          "#293038",
          "#1c2829"
        ],
        "ink": "#f7f4ed",
        "sub": "#5962b2",
        "accent": "#eb6142",
        "accentL": "#a2cdf5",
        "accentD": "#7c4db8",
        "accent2": "#7c4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,50,56",
        "glow": "234,96,65",
        "vig": "0,0,0",
        "palette": [
          "#eb6142",
          "#7c4db8",
          "#5962b2",
          "#a2cdf5",
          "#b4d94c",
          "#c740b1"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 0.71,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.33,
        "sub": 0.89
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 78,
        "root": 142.72,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10030
      }
    },
    "chronicleb": {
      "name": "Chronicle B — History",
      "bn": "Chronicle B — history",
      "dark": false,
      "c": {
        "bg": [
          "#d66f99",
          "#a36571",
          "#492a3f"
        ],
        "ink": "#171923",
        "sub": "#b26b59",
        "accent": "#42eb92",
        "accentL": "#f5a2b4",
        "accentD": "#b89b4d",
        "accent2": "#b89b4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,84,116",
        "glow": "65,234,146",
        "vig": "70,45,20",
        "palette": [
          "#42eb92",
          "#b89b4d",
          "#b26b59",
          "#f5a2b4",
          "#4c8ad9",
          "#89c740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.88,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.44,
        "sub": 1.01
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 91,
        "root": 160.03,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10031
      }
    },
    "chroniclec": {
      "name": "Chronicle C — History",
      "bn": "Chronicle C — history",
      "dark": true,
      "c": {
        "bg": [
          "#306b29",
          "#1c381f",
          "#1b2912"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b285",
        "accent": "#c342eb",
        "accentL": "#a2f5a7",
        "accentD": "#4db5b8",
        "accent2": "#4db5b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "25,56,21",
        "glow": "195,65,234",
        "vig": "0,0,0",
        "palette": [
          "#c342eb",
          "#4db5b8",
          "#59b285",
          "#a2f5a7",
          "#d94c61",
          "#4062c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 1.05,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.55,
        "sub": 1.13
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 104,
        "root": 177.34,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10032
      }
    },
    "chronicled": {
      "name": "Chronicle D — History",
      "bn": "Chronicle D — history",
      "dark": false,
      "c": {
        "bg": [
          "#5438d6",
          "#6843a3",
          "#191d49"
        ],
        "ink": "#171923",
        "sub": "#9f59b2",
        "accent": "#e1eb42",
        "accentL": "#bfa2f5",
        "accentD": "#b84d96",
        "accent2": "#b84d96",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "64,42,163",
        "glow": "224,234,65",
        "vig": "70,45,20",
        "palette": [
          "#e1eb42",
          "#b84d96",
          "#9f59b2",
          "#bfa2f5",
          "#4cd95f",
          "#c74540"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 1.22,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.45,
        "sub": 1.25
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 117,
        "root": 194.65,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10033
      }
    },
    "chroniclee": {
      "name": "Chronicle E — History",
      "bn": "Chronicle E — history",
      "dark": true,
      "c": {
        "bg": [
          "#6b3a0f",
          "#382c12",
          "#291009"
        ],
        "ink": "#f7f4ed",
        "sub": "#acb259",
        "accent": "#42afeb",
        "accentL": "#f5d8a2",
        "accentD": "#77b84d",
        "accent2": "#77b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,30,7",
        "glow": "65,175,234",
        "vig": "0,0,0",
        "palette": [
          "#42afeb",
          "#77b84d",
          "#acb259",
          "#f5d8a2",
          "#894cd9",
          "#40c76c"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 1.39,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.56,
        "sub": 1.37
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 130,
        "root": 211.96,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10034
      }
    },
    "chroniclef": {
      "name": "Chronicle F — History",
      "bn": "Chronicle F — history",
      "dark": false,
      "c": {
        "bg": [
          "#8dd6c5",
          "#77a3a2",
          "#33493e"
        ],
        "ink": "#171923",
        "sub": "#5992b2",
        "accent": "#eb427e",
        "accentL": "#a2f5f0",
        "accentD": "#4d57b8",
        "accent2": "#4d57b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,163,150",
        "glow": "234,65,126",
        "vig": "70,45,20",
        "palette": [
          "#eb427e",
          "#4d57b8",
          "#5992b2",
          "#a2f5f0",
          "#d9b24c",
          "#9440c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 1.56,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.67,
        "sub": 0.65
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 52,
        "root": 79.27,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10035
      }
    },
    "chronicleg": {
      "name": "Chronicle G — History",
      "bn": "Chronicle G — history",
      "dark": true,
      "c": {
        "bg": [
          "#6b3868",
          "#382332",
          "#251729"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25978",
        "accent": "#4deb42",
        "accentL": "#f5a2e1",
        "accentD": "#b8624d",
        "accent2": "#b8624d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,29,54",
        "glow": "76,234,65",
        "vig": "0,0,0",
        "palette": [
          "#4deb42",
          "#b8624d",
          "#b25978",
          "#f5a2e1",
          "#4cd7d9",
          "#c7bb40"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 0.2,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.78,
        "sub": 0.77
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 65,
        "root": 96.58,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10036
      }
    },
    "chronicleh": {
      "name": "Chronicle H — History",
      "bn": "Chronicle H — history",
      "dark": false,
      "c": {
        "bg": [
          "#a8d651",
          "#76a352",
          "#464920"
        ],
        "ink": "#171923",
        "sub": "#5eb259",
        "accent": "#6842eb",
        "accentL": "#c9f5a2",
        "accentD": "#4db881",
        "accent2": "#4db881",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "128,163,62",
        "glow": "103,65,234",
        "vig": "70,45,20",
        "palette": [
          "#6842eb",
          "#4db881",
          "#5eb259",
          "#c9f5a2",
          "#d94cae",
          "#40abc7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.37,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.89,
        "sub": 0.89
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 78,
        "root": 113.89,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10037
      }
    },
    "chroniclei": {
      "name": "Chronicle I — History",
      "bn": "Chronicle I — history",
      "dark": true,
      "c": {
        "bg": [
          "#1c396b",
          "#171c38",
          "#0e1f29"
        ],
        "ink": "#f7f4ed",
        "sub": "#6f59b2",
        "accent": "#eb9942",
        "accentL": "#a2b1f5",
        "accentD": "#a04db8",
        "accent2": "#a04db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,29,56",
        "glow": "234,153,65",
        "vig": "0,0,0",
        "palette": [
          "#eb9942",
          "#a04db8",
          "#6f59b2",
          "#a2b1f5",
          "#84d94c",
          "#c74084"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 0.54,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.0,
        "sub": 1.01
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 91,
        "root": 131.2,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10038
      }
    },
    "chroniclej": {
      "name": "Chronicle J — History",
      "bn": "Chronicle J — history",
      "dark": false,
      "c": {
        "bg": [
          "#d61e2b",
          "#a34333",
          "#491124"
        ],
        "ink": "#171923",
        "sub": "#b28959",
        "accent": "#42ebcb",
        "accentL": "#f5aba2",
        "accentD": "#b0b84d",
        "accent2": "#b0b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,22,32",
        "glow": "65,234,202",
        "vig": "70,45,20",
        "palette": [
          "#42ebcb",
          "#b0b84d",
          "#b28959",
          "#f5aba2",
          "#4c5bd9",
          "#5cc740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 0.71,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.11,
        "sub": 1.13
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 104,
        "root": 148.51,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10039
      }
    },
    "orbita": {
      "name": "Orbit A — Science",
      "bn": "Orbit A — science",
      "dark": true,
      "c": {
        "bg": [
          "#476b55",
          "#293832",
          "#1c291e"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b2b2",
        "accent": "#eb42ba",
        "accentL": "#a2f5d2",
        "accentD": "#4d7eb8",
        "accent2": "#4d7eb8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,56,44",
        "glow": "234,65,186",
        "vig": "0,0,0",
        "palette": [
          "#eb42ba",
          "#4d7eb8",
          "#59b2b2",
          "#a2f5d2",
          "#d97f4c",
          "#6440c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 0.88,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.22,
        "sub": 1.25
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 117,
        "root": 165.82,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10040
      }
    },
    "orbitb": {
      "name": "Orbit B — Science",
      "bn": "Orbit B — science",
      "dark": false,
      "c": {
        "bg": [
          "#b76fd6",
          "#9d65a3",
          "#372a49"
        ],
        "ink": "#171923",
        "sub": "#b25998",
        "accent": "#89eb42",
        "accentL": "#eba2f5",
        "accentD": "#b84d5e",
        "accent2": "#b84d5e",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "139,84,163",
        "glow": "137,234,65",
        "vig": "70,45,20",
        "palette": [
          "#89eb42",
          "#b84d5e",
          "#b25998",
          "#eba2f5",
          "#4cd9a8",
          "#c78b40"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 1.05,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.33,
        "sub": 1.37
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 130,
        "root": 183.13,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10041
      }
    },
    "orbitc": {
      "name": "Orbit C — Science",
      "bn": "Orbit C — science",
      "dark": true,
      "c": {
        "bg": [
          "#6b6a29",
          "#33381c",
          "#292212"
        ],
        "ink": "#f7f4ed",
        "sub": "#7eb259",
        "accent": "#4258eb",
        "accentL": "#e7f5a2",
        "accentD": "#4db85b",
        "accent2": "#4db85b",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,55,21",
        "glow": "65,87,234",
        "vig": "0,0,0",
        "palette": [
          "#4258eb",
          "#4db85b",
          "#7eb259",
          "#e7f5a2",
          "#d24cd9",
          "#40c7b2"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 1.22,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.44,
        "sub": 0.65
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 52,
        "root": 200.44,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10042
      }
    },
    "orbitd": {
      "name": "Orbit D — Science",
      "bn": "Orbit D — science",
      "dark": false,
      "c": {
        "bg": [
          "#38aad6",
          "#4374a3",
          "#194949"
        ],
        "ink": "#171923",
        "sub": "#5964b2",
        "accent": "#eb5d42",
        "accentL": "#a2cef5",
        "accentD": "#7a4db8",
        "accent2": "#7a4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,129,163",
        "glow": "234,92,65",
        "vig": "70,45,20",
        "palette": [
          "#eb5d42",
          "#7a4db8",
          "#5964b2",
          "#a2cef5",
          "#b7d94c",
          "#c740b4"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 1.39,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.55,
        "sub": 0.77
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 65,
        "root": 217.75,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10043
      }
    },
    "orbite": {
      "name": "Orbit E — Science",
      "bn": "Orbit E — science",
      "dark": true,
      "c": {
        "bg": [
          "#6b0f36",
          "#38121a",
          "#29091f"
        ],
        "ink": "#f7f4ed",
        "sub": "#b26959",
        "accent": "#42eb8e",
        "accentL": "#f5a2b6",
        "accentD": "#b8994d",
        "accent2": "#b8994d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,7,28",
        "glow": "65,234,142",
        "vig": "0,0,0",
        "palette": [
          "#42eb8e",
          "#b8994d",
          "#b26959",
          "#f5a2b6",
          "#4c8ed9",
          "#8cc740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 1.56,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.45,
        "sub": 0.89
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 78,
        "root": 85.06,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10044
      }
    },
    "orbitf": {
      "name": "Orbit F — Science",
      "bn": "Orbit F — science",
      "dark": false,
      "c": {
        "bg": [
          "#97d68d",
          "#77a37a",
          "#3c4933"
        ],
        "ink": "#171923",
        "sub": "#59b283",
        "accent": "#bf42eb",
        "accentL": "#a2f5a5",
        "accentD": "#4db7b8",
        "accent2": "#4db7b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "115,163,107",
        "glow": "191,65,234",
        "vig": "70,45,20",
        "palette": [
          "#bf42eb",
          "#4db7b8",
          "#59b283",
          "#a2f5a5",
          "#d94c65",
          "#4065c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 0.2,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.56,
        "sub": 1.01
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 91,
        "root": 102.37,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10045
      }
    },
    "orbitg": {
      "name": "Orbit G — Science",
      "bn": "Orbit G — science",
      "dark": true,
      "c": {
        "bg": [
          "#40386b",
          "#2a2338",
          "#171929"
        ],
        "ink": "#f7f4ed",
        "sub": "#9d59b2",
        "accent": "#e5eb42",
        "accentL": "#bea2f5",
        "accentD": "#b84d98",
        "accent2": "#b84d98",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "33,29,56",
        "glow": "228,234,65",
        "vig": "0,0,0",
        "palette": [
          "#e5eb42",
          "#b84d98",
          "#9d59b2",
          "#bea2f5",
          "#4cd95c",
          "#c74240"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 0.37,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.67,
        "sub": 1.13
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 104,
        "root": 119.68,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10046
      }
    },
    "orbith": {
      "name": "Orbit H — Science",
      "bn": "Orbit H — science",
      "dark": false,
      "c": {
        "bg": [
          "#d68d51",
          "#a38752",
          "#492820"
        ],
        "ink": "#171923",
        "sub": "#aeb259",
        "accent": "#42b3eb",
        "accentL": "#f5d6a2",
        "accentD": "#79b84d",
        "accent2": "#79b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,107,62",
        "glow": "65,179,234",
        "vig": "70,45,20",
        "palette": [
          "#42b3eb",
          "#79b84d",
          "#aeb259",
          "#f5d6a2",
          "#854cd9",
          "#40c769"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 0.54,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.78,
        "sub": 1.25
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 117,
        "root": 136.99,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10047
      }
    },
    "orbiti": {
      "name": "Orbit I — Science",
      "bn": "Orbit I — science",
      "dark": true,
      "c": {
        "bg": [
          "#1c6b56",
          "#173836",
          "#0e291a"
        ],
        "ink": "#f7f4ed",
        "sub": "#5994b2",
        "accent": "#eb4282",
        "accentL": "#a2f5ee",
        "accentD": "#4d5ab8",
        "accent2": "#4d5ab8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,56,45",
        "glow": "234,65,129",
        "vig": "0,0,0",
        "palette": [
          "#eb4282",
          "#4d5ab8",
          "#5994b2",
          "#a2f5ee",
          "#d9ae4c",
          "#9140c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 0.71,
        "motion": "drift",
        "spot": false
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.89,
        "sub": 1.37
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 130,
        "root": 154.3,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10048
      }
    },
    "orbitj": {
      "name": "Orbit J — Science",
      "bn": "Orbit J — science",
      "dark": false,
      "c": {
        "bg": [
          "#d61ed0",
          "#a33388",
          "#3c1149"
        ],
        "ink": "#171923",
        "sub": "#b2597a",
        "accent": "#51eb42",
        "accentL": "#f5a2e3",
        "accentD": "#b85f4d",
        "accent2": "#b85f4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,22,158",
        "glow": "80,234,65",
        "vig": "70,45,20",
        "palette": [
          "#51eb42",
          "#b85f4d",
          "#b2597a",
          "#f5a2e3",
          "#4cd9d8",
          "#c7b840"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 0.88,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.0,
        "sub": 0.65
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 52,
        "root": 171.61,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10049
      }
    },
    "signala": {
      "name": "Signal A — Technology",
      "bn": "Signal A — technology",
      "dark": true,
      "c": {
        "bg": [
          "#596b47",
          "#2d3829",
          "#26291c"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b263",
        "accent": "#8342eb",
        "accentL": "#bcf5a2",
        "accentD": "#4db892",
        "accent2": "#4db892",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "46,56,37",
        "glow": "130,65,234",
        "vig": "0,0,0",
        "palette": [
          "#8342eb",
          "#4db892",
          "#59b263",
          "#bcf5a2",
          "#d94c97",
          "#4095c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.05,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.11,
        "sub": 0.77
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 65,
        "root": 188.92,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10050
      }
    },
    "signalb": {
      "name": "Signal B — Technology",
      "bn": "Signal B — technology",
      "dark": false,
      "c": {
        "bg": [
          "#6f84d6",
          "#6565a3",
          "#2a3949"
        ],
        "ink": "#171923",
        "sub": "#7d59b2",
        "accent": "#ebb442",
        "accentL": "#a2a3f5",
        "accentD": "#b14db8",
        "accent2": "#b14db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,100,163",
        "glow": "234,180,65",
        "vig": "70,45,20",
        "palette": [
          "#ebb442",
          "#b14db8",
          "#7d59b2",
          "#a2a3f5",
          "#6ed94c",
          "#c7406e"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 1.22,
        "motion": "kinetic",
        "spot": false
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.22,
        "sub": 0.89
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 78,
        "root": 206.23,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10051
      }
    },
    "signalc": {
      "name": "Signal C — Technology",
      "bn": "Signal C — technology",
      "dark": true,
      "c": {
        "bg": [
          "#6b2f29",
          "#38251c",
          "#291216"
        ],
        "ink": "#f7f4ed",
        "sub": "#b29759",
        "accent": "#42ebe6",
        "accentL": "#f5b8a2",
        "accentD": "#9fb84d",
        "accent2": "#9fb84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,24,21",
        "glow": "65,234,229",
        "vig": "0,0,0",
        "palette": [
          "#42ebe6",
          "#9fb84d",
          "#b29759",
          "#f5b8a2",
          "#534cd9",
          "#46c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 1.39,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.33,
        "sub": 1.01
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 91,
        "root": 73.54,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10052
      }
    },
    "signald": {
      "name": "Signal D — Technology",
      "bn": "Signal D — technology",
      "dark": false,
      "c": {
        "bg": [
          "#38d674",
          "#43a37c",
          "#19491e"
        ],
        "ink": "#171923",
        "sub": "#59b2b1",
        "accent": "#eb42be",
        "accentL": "#a2f5d0",
        "accentD": "#4d80b8",
        "accent2": "#4d80b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,163,88",
        "glow": "234,65,190",
        "vig": "70,45,20",
        "palette": [
          "#eb42be",
          "#4d80b8",
          "#59b2b1",
          "#a2f5d0",
          "#d97c4c",
          "#6040c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 1.56,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.44,
        "sub": 1.13
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 104,
        "root": 90.85,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10053
      }
    },
    "signale": {
      "name": "Signal E — Technology",
      "bn": "Signal E — technology",
      "dark": true,
      "c": {
        "bg": [
          "#4d0f6b",
          "#341238",
          "#160929"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2599a",
        "accent": "#8deb42",
        "accentL": "#e9a2f5",
        "accentD": "#b84d61",
        "accent2": "#b84d61",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "40,7,56",
        "glow": "141,234,65",
        "vig": "0,0,0",
        "palette": [
          "#8deb42",
          "#b84d61",
          "#b2599a",
          "#e9a2f5",
          "#4cd9a5",
          "#c78840"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 0.2,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.55,
        "sub": 1.25
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 117,
        "root": 108.16,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10054
      }
    },
    "signalf": {
      "name": "Signal F — Technology",
      "bn": "Signal F — technology",
      "dark": false,
      "c": {
        "bg": [
          "#d6d48d",
          "#9ba377",
          "#494333"
        ],
        "ink": "#171923",
        "sub": "#80b259",
        "accent": "#425ceb",
        "accentL": "#e9f5a2",
        "accentD": "#4db858",
        "accent2": "#4db858",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,161,107",
        "glow": "65,91,234",
        "vig": "70,45,20",
        "palette": [
          "#425ceb",
          "#4db858",
          "#80b259",
          "#e9f5a2",
          "#ce4cd9",
          "#40c7af"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 0.37,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.45,
        "sub": 1.37
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 130,
        "root": 125.47,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10055
      }
    },
    "signalg": {
      "name": "Signal G — Technology",
      "bn": "Signal G — technology",
      "dark": true,
      "c": {
        "bg": [
          "#385e6b",
          "#232e38",
          "#172929"
        ],
        "ink": "#f7f4ed",
        "sub": "#5966b2",
        "accent": "#eb5942",
        "accentL": "#a2d0f5",
        "accentD": "#774db8",
        "accent2": "#774db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,49,56",
        "glow": "234,88,65",
        "vig": "0,0,0",
        "palette": [
          "#eb5942",
          "#774db8",
          "#5966b2",
          "#a2d0f5",
          "#bad94c",
          "#c740b7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 0.54,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.56,
        "sub": 0.65
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 52,
        "root": 142.78,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10056
      }
    },
    "signalh": {
      "name": "Signal H — Technology",
      "bn": "Signal H — technology",
      "dark": false,
      "c": {
        "bg": [
          "#d6518d",
          "#a35266",
          "#49203e"
        ],
        "ink": "#171923",
        "sub": "#b26759",
        "accent": "#42eb8a",
        "accentL": "#f5a2b8",
        "accentD": "#b8964d",
        "accent2": "#b8964d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,62,107",
        "glow": "65,234,138",
        "vig": "70,45,20",
        "palette": [
          "#42eb8a",
          "#b8964d",
          "#b26759",
          "#f5a2b8",
          "#4c91d9",
          "#90c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.71,
        "motion": "snap",
        "spot": false
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.67,
        "sub": 0.77
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 65,
        "root": 160.09,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10057
      }
    },
    "signali": {
      "name": "Signal I — Technology",
      "bn": "Signal I — technology",
      "dark": true,
      "c": {
        "bg": [
          "#286b1c",
          "#173819",
          "#19290e"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b281",
        "accent": "#bb42eb",
        "accentL": "#a2f5a3",
        "accentD": "#4db8b6",
        "accent2": "#4db8b6",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,56,14",
        "glow": "187,65,234",
        "vig": "0,0,0",
        "palette": [
          "#bb42eb",
          "#4db8b6",
          "#59b281",
          "#a2f5a3",
          "#d94c68",
          "#4068c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 0.88,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.78,
        "sub": 0.89
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 78,
        "root": 177.4,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10058
      }
    },
    "signalj": {
      "name": "Signal J — Technology",
      "bn": "Signal J — technology",
      "dark": false,
      "c": {
        "bg": [
          "#361ed6",
          "#5933a3",
          "#111849"
        ],
        "ink": "#171923",
        "sub": "#9b59b2",
        "accent": "#e8eb42",
        "accentL": "#bca2f5",
        "accentD": "#b84d9b",
        "accent2": "#b84d9b",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "41,22,163",
        "glow": "232,234,65",
        "vig": "70,45,20",
        "palette": [
          "#e8eb42",
          "#b84d9b",
          "#9b59b2",
          "#bca2f5",
          "#4cd959",
          "#c74041"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 1.05,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.89,
        "sub": 1.01
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 91,
        "root": 194.71,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10059
      }
    },
    "canvasa": {
      "name": "Canvas A — Art",
      "bn": "Canvas A — art",
      "dark": true,
      "c": {
        "bg": [
          "#6b5d47",
          "#383529",
          "#29211c"
        ],
        "ink": "#f7f4ed",
        "sub": "#a0b259",
        "accent": "#4298eb",
        "accentL": "#f5e3a2",
        "accentD": "#68b84d",
        "accent2": "#68b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,48,37",
        "glow": "65,152,234",
        "vig": "0,0,0",
        "palette": [
          "#4298eb",
          "#68b84d",
          "#a0b259",
          "#f5e3a2",
          "#9c4cd9",
          "#40c77f"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 1.22,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.0,
        "sub": 1.13
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 104,
        "root": 212.02,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10060
      }
    },
    "canvasb": {
      "name": "Canvas B — Art",
      "bn": "Canvas B — art",
      "dark": false,
      "c": {
        "bg": [
          "#6fd6cc",
          "#659ca3",
          "#2a493e"
        ],
        "ink": "#171923",
        "sub": "#5986b2",
        "accent": "#eb4267",
        "accentL": "#a2eef5",
        "accentD": "#514db8",
        "accent2": "#514db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,163,155",
        "glow": "234,65,102",
        "vig": "70,45,20",
        "palette": [
          "#eb4267",
          "#514db8",
          "#5986b2",
          "#a2eef5",
          "#d9c54c",
          "#a640c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 1.39,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.11,
        "sub": 1.25
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 117,
        "root": 79.33,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10061
      }
    },
    "canvasc": {
      "name": "Canvas C — Art",
      "bn": "Canvas C — art",
      "dark": true,
      "c": {
        "bg": [
          "#6b295e",
          "#381c2d",
          "#271229"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2596c",
        "accent": "#42eb4e",
        "accentL": "#f5a2d6",
        "accentD": "#b8704d",
        "accent2": "#b8704d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,21,49",
        "glow": "65,234,77",
        "vig": "0,0,0",
        "palette": [
          "#42eb4e",
          "#b8704d",
          "#b2596c",
          "#f5a2d6",
          "#4cc3d9",
          "#c0c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 1.56,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.22,
        "sub": 1.37
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 130,
        "root": 96.64,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10062
      }
    },
    "canvasd": {
      "name": "Canvas D — Art",
      "bn": "Canvas D — art",
      "dark": false,
      "c": {
        "bg": [
          "#8ad638",
          "#60a343",
          "#3f4919"
        ],
        "ink": "#171923",
        "sub": "#59b261",
        "accent": "#7f42eb",
        "accentL": "#bef5a2",
        "accentD": "#4db88f",
        "accent2": "#4db88f",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "104,163,42",
        "glow": "127,65,234",
        "vig": "70,45,20",
        "palette": [
          "#7f42eb",
          "#4db88f",
          "#59b261",
          "#bef5a2",
          "#d94c9a",
          "#4098c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 0.2,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.33,
        "sub": 0.65
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 52,
        "root": 113.95,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10063
      }
    },
    "canvase": {
      "name": "Canvas E — Art",
      "bn": "Canvas E — art",
      "dark": true,
      "c": {
        "bg": [
          "#0f246b",
          "#121238",
          "#091929"
        ],
        "ink": "#f7f4ed",
        "sub": "#7b59b2",
        "accent": "#ebb042",
        "accentL": "#a2a5f5",
        "accentD": "#af4db8",
        "accent2": "#af4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,18,56",
        "glow": "234,176,65",
        "vig": "0,0,0",
        "palette": [
          "#ebb042",
          "#af4db8",
          "#7b59b2",
          "#a2a5f5",
          "#71d94c",
          "#c74071"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 0.37,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.44,
        "sub": 0.77
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 65,
        "root": 131.26,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10064
      }
    },
    "canvasf": {
      "name": "Canvas F — Art",
      "bn": "Canvas F — art",
      "dark": false,
      "c": {
        "bg": [
          "#d6928d",
          "#a38377",
          "#493338"
        ],
        "ink": "#171923",
        "sub": "#b29559",
        "accent": "#42ebe2",
        "accentL": "#f5b6a2",
        "accentD": "#a2b84d",
        "accent2": "#a2b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,111,107",
        "glow": "65,234,225",
        "vig": "70,45,20",
        "palette": [
          "#42ebe2",
          "#a2b84d",
          "#b29559",
          "#f5b6a2",
          "#504cd9",
          "#4ac740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 0.54,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.55,
        "sub": 0.89
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 78,
        "root": 148.57,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10065
      }
    },
    "canvasg": {
      "name": "Canvas G — Art",
      "bn": "Canvas G — art",
      "dark": true,
      "c": {
        "bg": [
          "#386b4a",
          "#23382f",
          "#172919"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b2af",
        "accent": "#eb42c2",
        "accentL": "#a2f5ce",
        "accentD": "#4d83b8",
        "accent2": "#4d83b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,56,38",
        "glow": "234,65,194",
        "vig": "0,0,0",
        "palette": [
          "#eb42c2",
          "#4d83b8",
          "#59b2af",
          "#a2f5ce",
          "#d9794c",
          "#5d40c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 0.71,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.45,
        "sub": 1.01
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 91,
        "root": 165.88,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10066
      }
    },
    "canvash": {
      "name": "Canvas H — Art",
      "bn": "Canvas H — art",
      "dark": false,
      "c": {
        "bg": [
          "#a851d6",
          "#9852a3",
          "#302049"
        ],
        "ink": "#171923",
        "sub": "#b2599c",
        "accent": "#91eb42",
        "accentL": "#e7a2f5",
        "accentD": "#b84d63",
        "accent2": "#b84d63",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "127,62,163",
        "glow": "145,234,65",
        "vig": "70,45,20",
        "palette": [
          "#91eb42",
          "#b84d63",
          "#b2599c",
          "#e7a2f5",
          "#4cd9a2",
          "#c78540"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.88,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.56,
        "sub": 1.13
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 104,
        "root": 183.19,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10067
      }
    },
    "canvasi": {
      "name": "Canvas I — Art",
      "bn": "Canvas I — art",
      "dark": true,
      "c": {
        "bg": [
          "#6b671c",
          "#333817",
          "#29200e"
        ],
        "ink": "#f7f4ed",
        "sub": "#82b259",
        "accent": "#4260eb",
        "accentL": "#ebf5a2",
        "accentD": "#4db856",
        "accent2": "#4db856",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,53,14",
        "glow": "65,95,234",
        "vig": "0,0,0",
        "palette": [
          "#4260eb",
          "#4db856",
          "#82b259",
          "#ebf5a2",
          "#cb4cd9",
          "#40c7ac"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 1.05,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.67,
        "sub": 1.25
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 117,
        "root": 200.5,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10068
      }
    },
    "canvasj": {
      "name": "Canvas J — Art",
      "bn": "Canvas J — art",
      "dark": false,
      "c": {
        "bg": [
          "#1eabd6",
          "#3371a3",
          "#114947"
        ],
        "ink": "#171923",
        "sub": "#5968b2",
        "accent": "#eb5542",
        "accentL": "#a2d2f5",
        "accentD": "#754db8",
        "accent2": "#754db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,130,163",
        "glow": "234,84,65",
        "vig": "70,45,20",
        "palette": [
          "#eb5542",
          "#754db8",
          "#5968b2",
          "#a2d2f5",
          "#bdd94c",
          "#c740ba"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 1.22,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.78,
        "sub": 1.37
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 217.81,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10069
      }
    },
    "foruma": {
      "name": "Forum A — Community",
      "bn": "Forum A — community",
      "dark": true,
      "c": {
        "bg": [
          "#6b4751",
          "#38292a",
          "#291c23"
        ],
        "ink": "#f7f4ed",
        "sub": "#b27559",
        "accent": "#42eba5",
        "accentL": "#f5a2ab",
        "accentD": "#b8a84d",
        "accent2": "#b8a84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,37,42",
        "glow": "65,234,165",
        "vig": "0,0,0",
        "palette": [
          "#42eba5",
          "#b8a84d",
          "#b27559",
          "#f5a2ab",
          "#4c7ad9",
          "#7ac740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 1.39,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.89,
        "sub": 0.65
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 52,
        "root": 85.12,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10070
      }
    },
    "forumb": {
      "name": "Forum B — Community",
      "bn": "Forum B — community",
      "dark": false,
      "c": {
        "bg": [
          "#6fd66f",
          "#65a372",
          "#32492a"
        ],
        "ink": "#171923",
        "sub": "#59b28f",
        "accent": "#d642eb",
        "accentL": "#a2f5b1",
        "accentD": "#4da9b8",
        "accent2": "#4da9b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,163,84",
        "glow": "214,65,234",
        "vig": "70,45,20",
        "palette": [
          "#d642eb",
          "#4da9b8",
          "#59b28f",
          "#a2f5b1",
          "#d94c51",
          "#4052c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 1.56,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.0,
        "sub": 0.77
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 65,
        "root": 102.43,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10071
      }
    },
    "forumc": {
      "name": "Forum C — Community",
      "bn": "Forum C — community",
      "dark": true,
      "c": {
        "bg": [
          "#3c296b",
          "#2a1c38",
          "#131229"
        ],
        "ink": "#f7f4ed",
        "sub": "#a959b2",
        "accent": "#cdeb42",
        "accentL": "#c9a2f5",
        "accentD": "#b84d8a",
        "accent2": "#b84d8a",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "31,21,56",
        "glow": "205,234,65",
        "vig": "0,0,0",
        "palette": [
          "#cdeb42",
          "#b84d8a",
          "#a959b2",
          "#c9a2f5",
          "#4cd96f",
          "#c75440"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 0.2,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.11,
        "sub": 0.89
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 78,
        "root": 119.74,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10072
      }
    },
    "forumd": {
      "name": "Forum D — Community",
      "bn": "Forum D — community",
      "dark": false,
      "c": {
        "bg": [
          "#d69438",
          "#a38f43",
          "#492819"
        ],
        "ink": "#171923",
        "sub": "#a2b259",
        "accent": "#429ceb",
        "accentL": "#f5e1a2",
        "accentD": "#6ab84d",
        "accent2": "#6ab84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,113,42",
        "glow": "65,156,234",
        "vig": "70,45,20",
        "palette": [
          "#429ceb",
          "#6ab84d",
          "#a2b259",
          "#f5e1a2",
          "#994cd9",
          "#40c77c"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 0.37,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.22,
        "sub": 1.01
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 91,
        "root": 137.05,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10073
      }
    },
    "forume": {
      "name": "Forum E — Community",
      "bn": "Forum E — community",
      "dark": true,
      "c": {
        "bg": [
          "#0f6b60",
          "#123538",
          "#09291c"
        ],
        "ink": "#f7f4ed",
        "sub": "#5988b2",
        "accent": "#eb426b",
        "accentL": "#a2f0f5",
        "accentD": "#4f4db8",
        "accent2": "#4f4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,56,50",
        "glow": "234,65,106",
        "vig": "0,0,0",
        "palette": [
          "#eb426b",
          "#4f4db8",
          "#5988b2",
          "#a2f0f5",
          "#d9c24c",
          "#a340c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 0.54,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.33,
        "sub": 1.13
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 104,
        "root": 154.36,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10074
      }
    },
    "forumf": {
      "name": "Forum F — Community",
      "bn": "Forum F — community",
      "dark": false,
      "c": {
        "bg": [
          "#d68dca",
          "#a37792",
          "#473349"
        ],
        "ink": "#171923",
        "sub": "#b2596e",
        "accent": "#42eb4a",
        "accentL": "#f5a2d8",
        "accentD": "#b86e4d",
        "accent2": "#b86e4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,107,153",
        "glow": "65,234,73",
        "vig": "70,45,20",
        "palette": [
          "#42eb4a",
          "#b86e4d",
          "#b2596e",
          "#f5a2d8",
          "#4cc7d9",
          "#c3c740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 0.71,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.44,
        "sub": 1.25
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 117,
        "root": 171.67,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10075
      }
    },
    "forumg": {
      "name": "Forum G — Community",
      "bn": "Forum G — community",
      "dark": true,
      "c": {
        "bg": [
          "#536b38",
          "#2a3823",
          "#252917"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b25f",
        "accent": "#7b42eb",
        "accentL": "#c0f5a2",
        "accentD": "#4db88d",
        "accent2": "#4db88d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "43,56,29",
        "glow": "123,65,234",
        "vig": "0,0,0",
        "palette": [
          "#7b42eb",
          "#4db88d",
          "#59b25f",
          "#c0f5a2",
          "#d94c9e",
          "#409cc7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 0.88,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.55,
        "sub": 1.37
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 130,
        "root": 188.98,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10076
      }
    },
    "forumh": {
      "name": "Forum H — Community",
      "bn": "Forum H — community",
      "dark": false,
      "c": {
        "bg": [
          "#5172d6",
          "#5255a3",
          "#203649"
        ],
        "ink": "#171923",
        "sub": "#7959b2",
        "accent": "#ebac42",
        "accentL": "#a2a7f5",
        "accentD": "#ac4db8",
        "accent2": "#ac4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,87,163",
        "glow": "234,172,65",
        "vig": "70,45,20",
        "palette": [
          "#ebac42",
          "#ac4db8",
          "#7959b2",
          "#a2a7f5",
          "#74d94c",
          "#c74074"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 1.05,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.45,
        "sub": 0.65
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 52,
        "root": 206.29,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10077
      }
    },
    "forumi": {
      "name": "Forum I — Community",
      "bn": "Forum I — community",
      "dark": true,
      "c": {
        "bg": [
          "#6b1f1c",
          "#381f17",
          "#290e14"
        ],
        "ink": "#f7f4ed",
        "sub": "#b29359",
        "accent": "#42ebde",
        "accentL": "#f5b4a2",
        "accentD": "#a4b84d",
        "accent2": "#a4b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,16,14",
        "glow": "65,234,221",
        "vig": "0,0,0",
        "palette": [
          "#42ebde",
          "#a4b84d",
          "#b29359",
          "#f5b4a2",
          "#4c4cd9",
          "#4dc740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 1.22,
        "motion": "drift",
        "spot": false
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.56,
        "sub": 0.77
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 65,
        "root": 73.6,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10078
      }
    },
    "forumj": {
      "name": "Forum J — Community",
      "bn": "Forum J — community",
      "dark": false,
      "c": {
        "bg": [
          "#1ed65c",
          "#33a370",
          "#114914"
        ],
        "ink": "#171923",
        "sub": "#59b2ad",
        "accent": "#eb42c6",
        "accentL": "#a2f5cc",
        "accentD": "#4d85b8",
        "accent2": "#4d85b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,163,69",
        "glow": "234,65,198",
        "vig": "70,45,20",
        "palette": [
          "#eb42c6",
          "#4d85b8",
          "#59b2ad",
          "#a2f5cc",
          "#d9754c",
          "#5a40c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 1.39,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.67,
        "sub": 0.89
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 78,
        "root": 90.91,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10079
      }
    },
    "fieldnotea": {
      "name": "Fieldnote A — Documentary",
      "bn": "Fieldnote A — documentary",
      "dark": true,
      "c": {
        "bg": [
          "#64476b",
          "#382938",
          "#231c29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2598e",
        "accent": "#76eb42",
        "accentL": "#f4a2f5",
        "accentD": "#b84d52",
        "accent2": "#b84d52",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "52,37,56",
        "glow": "117,234,65",
        "vig": "0,0,0",
        "palette": [
          "#76eb42",
          "#b84d52",
          "#b2598e",
          "#f4a2f5",
          "#4cd9b8",
          "#c79a40"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.56,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.78,
        "sub": 1.01
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 91,
        "root": 108.22,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10080
      }
    },
    "fieldnoteb": {
      "name": "Fieldnote B — Documentary",
      "bn": "Fieldnote B — documentary",
      "dark": false,
      "c": {
        "bg": [
          "#ccd66f",
          "#90a365",
          "#49442a"
        ],
        "ink": "#171923",
        "sub": "#74b259",
        "accent": "#4245eb",
        "accentL": "#ddf5a2",
        "accentD": "#4db867",
        "accent2": "#4db867",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "155,163,84",
        "glow": "65,68,234",
        "vig": "70,45,20",
        "palette": [
          "#4245eb",
          "#4db867",
          "#74b259",
          "#ddf5a2",
          "#d94cd0",
          "#40c7c2"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.2,
        "motion": "kinetic",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.89,
        "sub": 1.13
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 104,
        "root": 125.53,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10081
      }
    },
    "fieldnotec": {
      "name": "Fieldnote C — Documentary",
      "bn": "Fieldnote C — documentary",
      "dark": true,
      "c": {
        "bg": [
          "#29516b",
          "#1c2738",
          "#122629"
        ],
        "ink": "#f7f4ed",
        "sub": "#595ab2",
        "accent": "#eb7042",
        "accentL": "#a2c5f5",
        "accentD": "#864db8",
        "accent2": "#864db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,42,56",
        "glow": "234,111,65",
        "vig": "0,0,0",
        "palette": [
          "#eb7042",
          "#864db8",
          "#595ab2",
          "#a2c5f5",
          "#a7d94c",
          "#c740a5"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 0.37,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.0,
        "sub": 1.25
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 117,
        "root": 142.84,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10082
      }
    },
    "fieldnoted": {
      "name": "Fieldnote D — Documentary",
      "bn": "Fieldnote D — documentary",
      "dark": false,
      "c": {
        "bg": [
          "#d6386a",
          "#a3434d",
          "#491935"
        ],
        "ink": "#171923",
        "sub": "#b27359",
        "accent": "#42eba1",
        "accentL": "#f5a2ad",
        "accentD": "#b8a54d",
        "accent2": "#b8a54d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,42,80",
        "glow": "65,234,161",
        "vig": "70,45,20",
        "palette": [
          "#42eba1",
          "#b8a54d",
          "#b27359",
          "#f5a2ad",
          "#4c7ed9",
          "#7dc740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 0.54,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.11,
        "sub": 1.37
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 130,
        "root": 160.15,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10083
      }
    },
    "fieldnotee": {
      "name": "Fieldnote E — Documentary",
      "bn": "Fieldnote E — documentary",
      "dark": true,
      "c": {
        "bg": [
          "#116b0f",
          "#123819",
          "#122909"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b28d",
        "accent": "#d342eb",
        "accentL": "#a2f5af",
        "accentD": "#4dabb8",
        "accent2": "#4dabb8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "8,56,7",
        "glow": "210,65,234",
        "vig": "0,0,0",
        "palette": [
          "#d342eb",
          "#4dabb8",
          "#59b28d",
          "#a2f5af",
          "#d94c55",
          "#4056c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 0.71,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.22,
        "sub": 0.65
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 52,
        "root": 177.46,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10084
      }
    },
    "fieldnotef": {
      "name": "Fieldnote F — Documentary",
      "bn": "Fieldnote F — documentary",
      "dark": false,
      "c": {
        "bg": [
          "#a18dd6",
          "#8c77a3",
          "#333349"
        ],
        "ink": "#171923",
        "sub": "#a759b2",
        "accent": "#d1eb42",
        "accentL": "#c7a2f5",
        "accentD": "#b84d8c",
        "accent2": "#b84d8c",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "122,107,163",
        "glow": "209,234,65",
        "vig": "70,45,20",
        "palette": [
          "#d1eb42",
          "#b84d8c",
          "#a759b2",
          "#c7a2f5",
          "#4cd96c",
          "#c75140"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 0.88,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.33,
        "sub": 0.77
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 65,
        "root": 194.77,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10085
      }
    },
    "fieldnoteg": {
      "name": "Fieldnote G — Documentary",
      "bn": "Fieldnote G — documentary",
      "dark": true,
      "c": {
        "bg": [
          "#6b5538",
          "#383323",
          "#291c17"
        ],
        "ink": "#f7f4ed",
        "sub": "#a4b259",
        "accent": "#42a0eb",
        "accentL": "#f5dfa2",
        "accentD": "#6db84d",
        "accent2": "#6db84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,44,29",
        "glow": "65,160,234",
        "vig": "0,0,0",
        "palette": [
          "#42a0eb",
          "#6db84d",
          "#a4b259",
          "#f5dfa2",
          "#954cd9",
          "#40c779"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 1.05,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.44,
        "sub": 0.89
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 78,
        "root": 212.08,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10086
      }
    },
    "fieldnoteh": {
      "name": "Fieldnote H — Documentary",
      "bn": "Fieldnote H — documentary",
      "dark": false,
      "c": {
        "bg": [
          "#51d6c3",
          "#529ea3",
          "#204938"
        ],
        "ink": "#171923",
        "sub": "#598ab2",
        "accent": "#eb426f",
        "accentL": "#a2f2f5",
        "accentD": "#4d4eb8",
        "accent2": "#4d4eb8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,163,148",
        "glow": "234,65,110",
        "vig": "70,45,20",
        "palette": [
          "#eb426f",
          "#4d4eb8",
          "#598ab2",
          "#a2f2f5",
          "#d9be4c",
          "#a040c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 1.22,
        "motion": "snap",
        "spot": false
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.55,
        "sub": 1.01
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 91,
        "root": 79.39,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10087
      }
    },
    "fieldnotei": {
      "name": "Fieldnote I — Documentary",
      "bn": "Fieldnote I — documentary",
      "dark": true,
      "c": {
        "bg": [
          "#6b1c60",
          "#38172c",
          "#250e29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25970",
        "accent": "#42eb46",
        "accentL": "#f5a2da",
        "accentD": "#b86b4d",
        "accent2": "#b86b4d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,14,50",
        "glow": "65,234,69",
        "vig": "0,0,0",
        "palette": [
          "#42eb46",
          "#b86b4d",
          "#b25970",
          "#f5a2da",
          "#4ccad9",
          "#c6c740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 1.39,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.45,
        "sub": 1.13
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 104,
        "root": 96.7,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10088
      }
    },
    "fieldnotej": {
      "name": "Fieldnote J — Documentary",
      "bn": "Fieldnote J — documentary",
      "dark": false,
      "c": {
        "bg": [
          "#86d61e",
          "#5ba333",
          "#404911"
        ],
        "ink": "#171923",
        "sub": "#59b25d",
        "accent": "#7742eb",
        "accentL": "#c1f5a2",
        "accentD": "#4db88b",
        "accent2": "#4db88b",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "101,163,22",
        "glow": "119,65,234",
        "vig": "70,45,20",
        "palette": [
          "#7742eb",
          "#4db88b",
          "#59b25d",
          "#c1f5a2",
          "#d94ca1",
          "#409fc7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 1.56,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.56,
        "sub": 1.25
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 117,
        "root": 114.01,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10089
      }
    },
    "studioa": {
      "name": "Studio A — Creative",
      "bn": "Studio A — creative",
      "dark": true,
      "c": {
        "bg": [
          "#474a6b",
          "#2b2938",
          "#1c2129"
        ],
        "ink": "#f7f4ed",
        "sub": "#8759b2",
        "accent": "#ebc742",
        "accentL": "#a9a2f5",
        "accentD": "#b84db2",
        "accent2": "#b84db2",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,38,56",
        "glow": "234,199,65",
        "vig": "0,0,0",
        "palette": [
          "#ebc742",
          "#b84db2",
          "#8759b2",
          "#a9a2f5",
          "#5ed94c",
          "#c7405f"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.67,
        "sub": 1.37
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 130,
        "root": 131.32,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10090
      }
    },
    "studiob": {
      "name": "Studio B — Creative",
      "bn": "Studio B — creative",
      "dark": false,
      "c": {
        "bg": [
          "#d6846f",
          "#a37e65",
          "#492a2c"
        ],
        "ink": "#171923",
        "sub": "#b2a159",
        "accent": "#42ddeb",
        "accentL": "#f5c1a2",
        "accentD": "#93b84d",
        "accent2": "#93b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,100,84",
        "glow": "65,220,234",
        "vig": "70,45,20",
        "palette": [
          "#42ddeb",
          "#93b84d",
          "#b2a159",
          "#f5c1a2",
          "#634cd9",
          "#40c748"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.37,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.78,
        "sub": 0.65
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 52,
        "root": 148.63,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10091
      }
    },
    "studioc": {
      "name": "Studio C — Creative",
      "bn": "Studio C — creative",
      "dark": true,
      "c": {
        "bg": [
          "#296b4a",
          "#1c3830",
          "#122917"
        ],
        "ink": "#f7f4ed",
        "sub": "#59aab2",
        "accent": "#eb42ab",
        "accentL": "#a2f5da",
        "accentD": "#4d74b8",
        "accent2": "#4d74b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,56,38",
        "glow": "234,65,171",
        "vig": "0,0,0",
        "palette": [
          "#eb42ab",
          "#4d74b8",
          "#59aab2",
          "#a2f5da",
          "#d98c4c",
          "#7040c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 0.54,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.89,
        "sub": 0.77
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 65,
        "root": 165.94,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10092
      }
    },
    "studiod": {
      "name": "Studio D — Creative",
      "bn": "Studio D — creative",
      "dark": false,
      "c": {
        "bg": [
          "#b438d6",
          "#a343a3",
          "#321949"
        ],
        "ink": "#171923",
        "sub": "#b25990",
        "accent": "#7aeb42",
        "accentL": "#f2a2f5",
        "accentD": "#b84d55",
        "accent2": "#b84d55",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "137,42,163",
        "glow": "121,234,65",
        "vig": "70,45,20",
        "palette": [
          "#7aeb42",
          "#b84d55",
          "#b25990",
          "#f2a2f5",
          "#4cd9b5",
          "#c79740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 0.71,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.0,
        "sub": 0.89
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 78,
        "root": 183.25,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10093
      }
    },
    "studioe": {
      "name": "Studio E — Creative",
      "bn": "Studio E — creative",
      "dark": true,
      "c": {
        "bg": [
          "#646b0f",
          "#2d3812",
          "#292309"
        ],
        "ink": "#f7f4ed",
        "sub": "#76b259",
        "accent": "#4249eb",
        "accentL": "#dff5a2",
        "accentD": "#4db864",
        "accent2": "#4db864",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "52,56,7",
        "glow": "65,72,234",
        "vig": "0,0,0",
        "palette": [
          "#4249eb",
          "#4db864",
          "#76b259",
          "#dff5a2",
          "#d94cd3",
          "#40c7bf"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 0.88,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.11,
        "sub": 1.01
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 91,
        "root": 200.56,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10094
      }
    },
    "studiof": {
      "name": "Studio F — Creative",
      "bn": "Studio F — creative",
      "dark": false,
      "c": {
        "bg": [
          "#8dbbd6",
          "#7789a3",
          "#334749"
        ],
        "ink": "#171923",
        "sub": "#595cb2",
        "accent": "#eb6c42",
        "accentL": "#a2c7f5",
        "accentD": "#834db8",
        "accent2": "#834db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,142,163",
        "glow": "234,108,65",
        "vig": "70,45,20",
        "palette": [
          "#eb6c42",
          "#834db8",
          "#595cb2",
          "#a2c7f5",
          "#aad94c",
          "#c740a8"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 1.05,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.22,
        "sub": 1.13
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 104,
        "root": 217.87,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10095
      }
    },
    "studiog": {
      "name": "Studio G — Creative",
      "bn": "Studio G — creative",
      "dark": true,
      "c": {
        "bg": [
          "#6b3849",
          "#382325",
          "#291722"
        ],
        "ink": "#f7f4ed",
        "sub": "#b27159",
        "accent": "#42eb9d",
        "accentL": "#f5a2af",
        "accentD": "#b8a34d",
        "accent2": "#b8a34d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,29,38",
        "glow": "65,234,157",
        "vig": "0,0,0",
        "palette": [
          "#42eb9d",
          "#b8a34d",
          "#b27159",
          "#f5a2af",
          "#4c81d9",
          "#80c740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 1.22,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.33,
        "sub": 1.25
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 117,
        "root": 85.18,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10096
      }
    },
    "studioh": {
      "name": "Studio H — Creative",
      "bn": "Studio H — creative",
      "dark": false,
      "c": {
        "bg": [
          "#57d651",
          "#52a360",
          "#2d4920"
        ],
        "ink": "#171923",
        "sub": "#59b28b",
        "accent": "#cf42eb",
        "accentL": "#a2f5ad",
        "accentD": "#4daeb8",
        "accent2": "#4daeb8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "66,163,62",
        "glow": "206,65,234",
        "vig": "70,45,20",
        "palette": [
          "#cf42eb",
          "#4daeb8",
          "#59b28b",
          "#a2f5ad",
          "#d94c58",
          "#4059c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 1.39,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.44,
        "sub": 1.37
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 130,
        "root": 102.49,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10097
      }
    },
    "studioi": {
      "name": "Studio I — Creative",
      "bn": "Studio I — creative",
      "dark": true,
      "c": {
        "bg": [
          "#2f1c6b",
          "#261738",
          "#0e0e29"
        ],
        "ink": "#f7f4ed",
        "sub": "#a559b2",
        "accent": "#d5eb42",
        "accentL": "#c5a2f5",
        "accentD": "#b84d8e",
        "accent2": "#b84d8e",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "24,14,56",
        "glow": "213,234,65",
        "vig": "0,0,0",
        "palette": [
          "#d5eb42",
          "#b84d8e",
          "#a559b2",
          "#c5a2f5",
          "#4cd969",
          "#c74e40"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 1.56,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.55,
        "sub": 0.65
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 52,
        "root": 119.8,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10098
      }
    },
    "studioj": {
      "name": "Studio J — Creative",
      "bn": "Studio J — creative",
      "dark": false,
      "c": {
        "bg": [
          "#d6811e",
          "#a38733",
          "#492011"
        ],
        "ink": "#171923",
        "sub": "#a6b259",
        "accent": "#42a4eb",
        "accentL": "#f5dda2",
        "accentD": "#6fb84d",
        "accent2": "#6fb84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,98,22",
        "glow": "65,164,234",
        "vig": "70,45,20",
        "palette": [
          "#42a4eb",
          "#6fb84d",
          "#a6b259",
          "#f5dda2",
          "#924cd9",
          "#40c775"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "fw": 12,
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 0.2,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.45,
        "sub": 0.77
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 65,
        "root": 137.11,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10099
      }
    },
    "pulsea": {
      "name": "Pulse A — Current Affairs",
      "bn": "Pulse A — current affairs",
      "dark": true,
      "c": {
        "bg": [
          "#476b6b",
          "#293538",
          "#1c2926"
        ],
        "ink": "#f7f4ed",
        "sub": "#597cb2",
        "accent": "#eb4254",
        "accentL": "#a2e5f5",
        "accentD": "#5d4db8",
        "accent2": "#5d4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,55,56",
        "glow": "234,65,83",
        "vig": "0,0,0",
        "palette": [
          "#eb4254",
          "#5d4db8",
          "#597cb2",
          "#a2e5f5",
          "#d9d54c",
          "#b640c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "fw": 2,
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 0.37,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.56,
        "sub": 0.89
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 78,
        "root": 154.42,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10100
      }
    },
    "pulseb": {
      "name": "Pulse B — Current Affairs",
      "bn": "Pulse B — current affairs",
      "dark": false,
      "c": {
        "bg": [
          "#d66fb7",
          "#a36583",
          "#492a48"
        ],
        "ink": "#171923",
        "sub": "#b25962",
        "accent": "#42eb61",
        "accentL": "#f5a2cc",
        "accentD": "#b87c4d",
        "accent2": "#b87c4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,84,139",
        "glow": "65,234,96",
        "vig": "70,45,20",
        "palette": [
          "#42eb61",
          "#b87c4d",
          "#b25962",
          "#f5a2cc",
          "#4cb3d9",
          "#b1c740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 0.54,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.67,
        "sub": 1.01
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 91,
        "root": 171.73,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10101
      }
    },
    "pulsec": {
      "name": "Pulse C — Current Affairs",
      "bn": "Pulse C — current affairs",
      "dark": true,
      "c": {
        "bg": [
          "#436b29",
          "#22381c",
          "#212912"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b26b",
        "accent": "#9242eb",
        "accentL": "#b4f5a2",
        "accentD": "#4db89c",
        "accent2": "#4db89c",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "35,56,21",
        "glow": "146,65,234",
        "vig": "0,0,0",
        "palette": [
          "#9242eb",
          "#4db89c",
          "#59b26b",
          "#b4f5a2",
          "#d94c8a",
          "#4089c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 0.71,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.78,
        "sub": 1.13
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 104,
        "root": 189.04,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10102
      }
    },
    "pulsed": {
      "name": "Pulse D — Current Affairs",
      "bn": "Pulse D — current affairs",
      "dark": false,
      "c": {
        "bg": [
          "#3849d6",
          "#4c43a3",
          "#192b49"
        ],
        "ink": "#171923",
        "sub": "#8559b2",
        "accent": "#ebc342",
        "accentL": "#a7a2f5",
        "accentD": "#b84db5",
        "accent2": "#b84db5",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,55,163",
        "glow": "234,195,65",
        "vig": "70,45,20",
        "palette": [
          "#ebc342",
          "#b84db5",
          "#8559b2",
          "#a7a2f5",
          "#61d94c",
          "#c74062"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 0.88,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.89,
        "sub": 1.25
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 117,
        "root": 206.35,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10103
      }
    },
    "pulsee": {
      "name": "Pulse E — Current Affairs",
      "bn": "Pulse E — current affairs",
      "dark": true,
      "c": {
        "bg": [
          "#6b200f",
          "#382112",
          "#29090c"
        ],
        "ink": "#f7f4ed",
        "sub": "#b29f59",
        "accent": "#42e0eb",
        "accentL": "#f5c0a2",
        "accentD": "#96b84d",
        "accent2": "#96b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,16,7",
        "glow": "65,224,234",
        "vig": "0,0,0",
        "palette": [
          "#42e0eb",
          "#96b84d",
          "#b29f59",
          "#f5c0a2",
          "#604cd9",
          "#40c745"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 1.05,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.0,
        "sub": 1.37
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 130,
        "root": 73.66,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10104
      }
    },
    "pulsef": {
      "name": "Pulse F — Current Affairs",
      "bn": "Pulse F — current affairs",
      "dark": false,
      "c": {
        "bg": [
          "#8dd6b0",
          "#77a395",
          "#334938"
        ],
        "ink": "#171923",
        "sub": "#59acb2",
        "accent": "#eb42af",
        "accentL": "#a2f5d8",
        "accentD": "#4d76b8",
        "accent2": "#4d76b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,163,133",
        "glow": "234,65,175",
        "vig": "70,45,20",
        "palette": [
          "#eb42af",
          "#4d76b8",
          "#59acb2",
          "#a2f5d8",
          "#d9894c",
          "#6d40c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 1.22,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.11,
        "sub": 0.65
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 52,
        "root": 90.97,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10105
      }
    },
    "pulseg": {
      "name": "Pulse G — Current Affairs",
      "bn": "Pulse G — current affairs",
      "dark": true,
      "c": {
        "bg": [
          "#5f386b",
          "#382338",
          "#201729"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25992",
        "accent": "#7eeb42",
        "accentL": "#f0a2f5",
        "accentD": "#b84d57",
        "accent2": "#b84d57",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "49,29,56",
        "glow": "125,234,65",
        "vig": "0,0,0",
        "palette": [
          "#7eeb42",
          "#b84d57",
          "#b25992",
          "#f0a2f5",
          "#4cd9b2",
          "#c79440"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 1.39,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.22,
        "sub": 0.77
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 65,
        "root": 108.28,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10106
      }
    },
    "pulseh": {
      "name": "Pulse H — Current Affairs",
      "bn": "Pulse H — current affairs",
      "dark": false,
      "c": {
        "bg": [
          "#cfd651",
          "#8ea352",
          "#494120"
        ],
        "ink": "#171923",
        "sub": "#78b259",
        "accent": "#424deb",
        "accentL": "#e1f5a2",
        "accentD": "#4db862",
        "accent2": "#4db862",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "157,163,62",
        "glow": "65,76,234",
        "vig": "70,45,20",
        "palette": [
          "#424deb",
          "#4db862",
          "#78b259",
          "#e1f5a2",
          "#d94cd7",
          "#40c7bb"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 1.56,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.33,
        "sub": 0.89
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 78,
        "root": 125.59,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10107
      }
    },
    "pulsei": {
      "label": "Editorial Swiss",
      "dark": true,
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 0.2,
        "motion": "drift",
        "spot": false
      },
      "c": {
        "bg": [
          "#1c506b",
          "#172638",
          "#0e2729"
        ],
        "ink": "#f7f4ed",
        "sub": "#595eb2",
        "accent": "#eb6842",
        "accentL": "#a2c9f5",
        "accentD": "#814db8",
        "accent2": "#814db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,41,56",
        "glow": "234,104,65",
        "vig": "0,0,0",
        "palette": [
          "#eb6842",
          "#814db8",
          "#595eb2",
          "#a2c9f5",
          "#add94c",
          "#c740ab"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "name": "Pulse I — Current Affairs",
      "bn": "Pulse I — current affairs",
      "sfx": {
        "pitch": 0.9,
        "bright": 1.44,
        "sub": 1.01
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 91,
        "root": 142.9,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10108
      }
    },
    "pulsej": {
      "label": "Cyberpunk",
      "dark": false,
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 0.37,
        "motion": "orbit",
        "spot": true
      },
      "c": {
        "bg": [
          "#d61e60",
          "#a33344",
          "#491134"
        ],
        "ink": "#171923",
        "sub": "#b26f59",
        "accent": "#42eb99",
        "accentL": "#f5a2b1",
        "accentD": "#b8a04d",
        "accent2": "#b8a04d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,22,73",
        "glow": "65,234,153",
        "vig": "70,45,20",
        "palette": [
          "#42eb99",
          "#b8a04d",
          "#b26f59",
          "#f5a2b1",
          "#4c84d9",
          "#83c740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Pulse J — Current Affairs",
      "bn": "Pulse J — current affairs",
      "sfx": {
        "pitch": 0.945,
        "bright": 1.55,
        "sub": 1.13
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 104,
        "root": 160.21,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10109
      }
    },
    "archivea": {
      "label": "Forest Field",
      "dark": true,
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 0.54,
        "motion": "smooth",
        "spot": true
      },
      "c": {
        "bg": [
          "#476b4b",
          "#29382e",
          "#1e291c"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b299",
        "accent": "#ea42eb",
        "accentL": "#a2f5ba",
        "accentD": "#4d9db8",
        "accent2": "#4d9db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,56,39",
        "glow": "233,65,234",
        "vig": "0,0,0",
        "palette": [
          "#ea42eb",
          "#4d9db8",
          "#59b299",
          "#a2f5ba",
          "#d9564c",
          "#4043c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Archive A — Research",
      "bn": "Archive A — research",
      "sfx": {
        "pitch": 0.99,
        "bright": 0.45,
        "sub": 1.25
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 117,
        "root": 177.52,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10110
      }
    },
    "archiveb": {
      "label": "Blueprint",
      "dark": false,
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.71,
        "motion": "kinetic",
        "spot": false
      },
      "c": {
        "bg": [
          "#996fd6",
          "#8b65a3",
          "#2e2a49"
        ],
        "ink": "#171923",
        "sub": "#b259b2",
        "accent": "#baeb42",
        "accentL": "#d2a2f5",
        "accentD": "#b84d7d",
        "accent2": "#b84d7d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "116,84,163",
        "glow": "186,234,65",
        "vig": "70,45,20",
        "palette": [
          "#baeb42",
          "#b84d7d",
          "#b259b2",
          "#d2a2f5",
          "#4cd97f",
          "#c76440"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "name": "Archive B — Research",
      "bn": "Archive B — research",
      "sfx": {
        "pitch": 1.035,
        "bright": 0.56,
        "sub": 1.37
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 194.83,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10111
      }
    },
    "archivec": {
      "label": "Candy Pop",
      "dark": true,
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 0.88,
        "motion": "stagger",
        "spot": true
      },
      "c": {
        "bg": [
          "#6b5729",
          "#38361c",
          "#291c12"
        ],
        "ink": "#f7f4ed",
        "sub": "#98b259",
        "accent": "#4289eb",
        "accentL": "#f5eba2",
        "accentD": "#5eb84d",
        "accent2": "#5eb84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,45,21",
        "glow": "65,136,234",
        "vig": "0,0,0",
        "palette": [
          "#4289eb",
          "#5eb84d",
          "#98b259",
          "#f5eba2",
          "#a94cd9",
          "#40c78b"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Archive C — Research",
      "bn": "Archive C — research",
      "sfx": {
        "pitch": 1.08,
        "bright": 0.67,
        "sub": 0.65
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 52,
        "root": 212.14,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10112
      }
    },
    "archived": {
      "label": "Volcanic",
      "dark": false,
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 1.05,
        "motion": "pulse",
        "spot": true
      },
      "c": {
        "bg": [
          "#38d6d5",
          "#4390a3",
          "#19493c"
        ],
        "ink": "#171923",
        "sub": "#597eb2",
        "accent": "#eb4258",
        "accentL": "#a2e7f5",
        "accentD": "#5b4db8",
        "accent2": "#5b4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,163,161",
        "glow": "234,65,87",
        "vig": "70,45,20",
        "palette": [
          "#eb4258",
          "#5b4db8",
          "#597eb2",
          "#a2e7f5",
          "#d9d24c",
          "#b340c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Archive D — Research",
      "bn": "Archive D — research",
      "sfx": {
        "pitch": 1.125,
        "bright": 0.78,
        "sub": 0.77
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 65,
        "root": 79.45,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10113
      }
    },
    "archivee": {
      "label": "Arctic Glass",
      "dark": true,
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 1.22,
        "motion": "float",
        "spot": false
      },
      "c": {
        "bg": [
          "#6b0f51",
          "#381225",
          "#290928"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25964",
        "accent": "#42eb5d",
        "accentL": "#f5a2ce",
        "accentD": "#b87a4d",
        "accent2": "#b87a4d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,7,42",
        "glow": "65,234,92",
        "vig": "0,0,0",
        "palette": [
          "#42eb5d",
          "#b87a4d",
          "#b25964",
          "#f5a2ce",
          "#4cb7d9",
          "#b4c740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "name": "Archive E — Research",
      "bn": "Archive E — research",
      "sfx": {
        "pitch": 1.17,
        "bright": 0.89,
        "sub": 0.89
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 78,
        "root": 96.76,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10114
      }
    },
    "archivef": {
      "label": "Newspaper",
      "dark": false,
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 1.39,
        "motion": "parallax",
        "spot": true
      },
      "c": {
        "bg": [
          "#acd68d",
          "#80a377",
          "#434933"
        ],
        "ink": "#171923",
        "sub": "#59b269",
        "accent": "#8e42eb",
        "accentL": "#b6f5a2",
        "accentD": "#4db899",
        "accent2": "#4db899",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "131,163,107",
        "glow": "142,65,234",
        "vig": "70,45,20",
        "palette": [
          "#8e42eb",
          "#4db899",
          "#59b269",
          "#b6f5a2",
          "#d94c8e",
          "#408cc7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Archive F — Research",
      "bn": "Archive F — research",
      "sfx": {
        "pitch": 1.215,
        "bright": 1.0,
        "sub": 1.01
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 91,
        "root": 114.07,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10115
      }
    },
    "archiveg": {
      "label": "Royal Blue",
      "dark": true,
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 1.56,
        "motion": "rise",
        "spot": true
      },
      "c": {
        "bg": [
          "#383f6b",
          "#242338",
          "#171e29"
        ],
        "ink": "#f7f4ed",
        "sub": "#8359b2",
        "accent": "#ebc042",
        "accentL": "#a5a2f5",
        "accentD": "#b84db7",
        "accent2": "#b84db7",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,32,56",
        "glow": "234,191,65",
        "vig": "0,0,0",
        "palette": [
          "#ebc042",
          "#b84db7",
          "#8359b2",
          "#a5a2f5",
          "#65d94c",
          "#c74065"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Archive G — Research",
      "bn": "Archive G — research",
      "sfx": {
        "pitch": 1.26,
        "bright": 1.11,
        "sub": 1.13
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 104,
        "root": 131.38,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10116
      }
    },
    "archiveh": {
      "label": "Retro Print",
      "dark": false,
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.2,
        "motion": "snap",
        "spot": false
      },
      "c": {
        "bg": [
          "#d66651",
          "#a37052",
          "#492025"
        ],
        "ink": "#171923",
        "sub": "#b29d59",
        "accent": "#42e4eb",
        "accentL": "#f5bea2",
        "accentD": "#98b84d",
        "accent2": "#98b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,77,62",
        "glow": "65,228,234",
        "vig": "70,45,20",
        "palette": [
          "#42e4eb",
          "#98b84d",
          "#b29d59",
          "#f5bea2",
          "#5c4cd9",
          "#40c742"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "name": "Archive H — Research",
      "bn": "Archive H — research",
      "sfx": {
        "pitch": 0.72,
        "bright": 1.22,
        "sub": 1.25
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 117,
        "root": 148.69,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10117
      }
    },
    "archivei": {
      "label": "Minimal Studio",
      "dark": true,
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 0.37,
        "motion": "drift",
        "spot": true
      },
      "c": {
        "bg": [
          "#1c6b3f",
          "#17382d",
          "#0e2912"
        ],
        "ink": "#f7f4ed",
        "sub": "#59aeb2",
        "accent": "#eb42b3",
        "accentL": "#a2f5d6",
        "accentD": "#4d79b8",
        "accent2": "#4d79b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,56,33",
        "glow": "234,65,179",
        "vig": "0,0,0",
        "palette": [
          "#eb42b3",
          "#4d79b8",
          "#59aeb2",
          "#a2f5d6",
          "#d9854c",
          "#6940c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "name": "Archive I — Research",
      "bn": "Archive I — research",
      "sfx": {
        "pitch": 0.765,
        "bright": 1.33,
        "sub": 1.37
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 130,
        "root": 166.0,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10118
      }
    },
    "archivej": {
      "label": "Cosmic Dream",
      "dark": false,
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 0.54,
        "motion": "orbit",
        "spot": true
      },
      "c": {
        "bg": [
          "#a61ed6",
          "#9e33a3",
          "#2b1149"
        ],
        "ink": "#171923",
        "sub": "#b25994",
        "accent": "#82eb42",
        "accentL": "#eea2f5",
        "accentD": "#b84d5a",
        "accent2": "#b84d5a",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "126,22,163",
        "glow": "129,234,65",
        "vig": "70,45,20",
        "palette": [
          "#82eb42",
          "#b84d5a",
          "#b25994",
          "#eea2f5",
          "#4cd9af",
          "#c79140"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "name": "Archive J — Research",
      "bn": "Archive J — research",
      "sfx": {
        "pitch": 0.81,
        "bright": 1.44,
        "sub": 0.65
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 52,
        "root": 183.31,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10119
      }
    },
    "compassa": {
      "name": "Compass A — Exploration",
      "bn": "Compass A — exploration",
      "dark": true,
      "c": {
        "bg": [
          "#636b47",
          "#323829",
          "#29281c"
        ],
        "ink": "#f7f4ed",
        "sub": "#6ab259",
        "accent": "#5242eb",
        "accentL": "#d4f5a2",
        "accentD": "#4db873",
        "accent2": "#4db873",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "51,56,37",
        "glow": "81,65,234",
        "vig": "0,0,0",
        "palette": [
          "#5242eb",
          "#4db873",
          "#6ab259",
          "#d4f5a2",
          "#d94cc0",
          "#40bdc7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 0.71,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.55,
        "sub": 0.77
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 65,
        "root": 200.62,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10120
      }
    },
    "compassb": {
      "name": "Compass B — Exploration",
      "bn": "Compass B — exploration",
      "dark": false,
      "c": {
        "bg": [
          "#6fa2d6",
          "#6576a3",
          "#2a4249"
        ],
        "ink": "#171923",
        "sub": "#6359b2",
        "accent": "#eb8342",
        "accentL": "#a2bcf5",
        "accentD": "#924db8",
        "accent2": "#924db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,123,163",
        "glow": "234,131,65",
        "vig": "70,45,20",
        "palette": [
          "#eb8342",
          "#924db8",
          "#6359b2",
          "#a2bcf5",
          "#97d94c",
          "#c74095"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.88,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.45,
        "sub": 0.89
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 78,
        "root": 217.93,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10121
      }
    },
    "compassc": {
      "name": "Compass C — Exploration",
      "bn": "Compass C — exploration",
      "dark": true,
      "c": {
        "bg": [
          "#6b2936",
          "#381d1c",
          "#29121d"
        ],
        "ink": "#f7f4ed",
        "sub": "#b27d59",
        "accent": "#42ebb4",
        "accentL": "#f5a2a3",
        "accentD": "#b8b14d",
        "accent2": "#b8b14d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,21,28",
        "glow": "65,234,180",
        "vig": "0,0,0",
        "palette": [
          "#42ebb4",
          "#b8b14d",
          "#b27d59",
          "#f5a2a3",
          "#4c6ed9",
          "#6ec740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 1.05,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.56,
        "sub": 1.01
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 91,
        "root": 85.24,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10122
      }
    },
    "compassd": {
      "name": "Compass D — Exploration",
      "bn": "Compass D — exploration",
      "dark": false,
      "c": {
        "bg": [
          "#38d646",
          "#43a360",
          "#214919"
        ],
        "ink": "#171923",
        "sub": "#59b297",
        "accent": "#e642eb",
        "accentL": "#a2f5b8",
        "accentD": "#4d9fb8",
        "accent2": "#4d9fb8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,163,53",
        "glow": "229,65,234",
        "vig": "70,45,20",
        "palette": [
          "#e642eb",
          "#4d9fb8",
          "#59b297",
          "#a2f5b8",
          "#d9534c",
          "#4046c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 1.22,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.67,
        "sub": 1.13
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 104,
        "root": 102.55,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10123
      }
    },
    "compasse": {
      "name": "Compass E — Exploration",
      "bn": "Compass E — exploration",
      "dark": true,
      "c": {
        "bg": [
          "#320f6b",
          "#281238",
          "#0d0929"
        ],
        "ink": "#f7f4ed",
        "sub": "#b159b2",
        "accent": "#beeb42",
        "accentL": "#d0a2f5",
        "accentD": "#b84d80",
        "accent2": "#b84d80",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "26,7,56",
        "glow": "190,234,65",
        "vig": "0,0,0",
        "palette": [
          "#beeb42",
          "#b84d80",
          "#b159b2",
          "#d0a2f5",
          "#4cd97c",
          "#c76040"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 1.39,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.78,
        "sub": 1.25
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 117,
        "root": 119.86,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10124
      }
    },
    "compassf": {
      "name": "Compass F — Exploration",
      "bn": "Compass F — exploration",
      "dark": false,
      "c": {
        "bg": [
          "#d6be8d",
          "#a39e77",
          "#493c33"
        ],
        "ink": "#171923",
        "sub": "#9ab259",
        "accent": "#428deb",
        "accentL": "#f5e9a2",
        "accentD": "#61b84d",
        "accent2": "#61b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,145,107",
        "glow": "65,140,234",
        "vig": "70,45,20",
        "palette": [
          "#428deb",
          "#61b84d",
          "#9ab259",
          "#f5e9a2",
          "#a54cd9",
          "#40c788"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 1.56,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.89,
        "sub": 1.37
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 130,
        "root": 137.17,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10125
      }
    },
    "compassg": {
      "name": "Compass G — Exploration",
      "bn": "Compass G — exploration",
      "dark": true,
      "c": {
        "bg": [
          "#386b69",
          "#233438",
          "#172923"
        ],
        "ink": "#f7f4ed",
        "sub": "#5980b2",
        "accent": "#eb425c",
        "accentL": "#a2e9f5",
        "accentD": "#584db8",
        "accent2": "#584db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,56,55",
        "glow": "234,65,91",
        "vig": "0,0,0",
        "palette": [
          "#eb425c",
          "#584db8",
          "#5980b2",
          "#a2e9f5",
          "#d9ce4c",
          "#af40c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 0.2,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.0,
        "sub": 0.65
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 52,
        "root": 154.48,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10126
      }
    },
    "compassh": {
      "name": "Compass H — Exploration",
      "bn": "Compass H — exploration",
      "dark": false,
      "c": {
        "bg": [
          "#d651b4",
          "#a3527d",
          "#492049"
        ],
        "ink": "#171923",
        "sub": "#b25966",
        "accent": "#42eb59",
        "accentL": "#f5a2d0",
        "accentD": "#b8784d",
        "accent2": "#b8784d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,62,137",
        "glow": "65,234,89",
        "vig": "70,45,20",
        "palette": [
          "#42eb59",
          "#b8784d",
          "#b25966",
          "#f5a2d0",
          "#4cbad9",
          "#b7c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.37,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.11,
        "sub": 0.77
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 65,
        "root": 171.79,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10127
      }
    },
    "compassi": {
      "name": "Compass I — Exploration",
      "bn": "Compass I — exploration",
      "dark": true,
      "c": {
        "bg": [
          "#406b1c",
          "#1f3817",
          "#21290e"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b267",
        "accent": "#8a42eb",
        "accentL": "#b8f5a2",
        "accentD": "#4db897",
        "accent2": "#4db897",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "33,56,14",
        "glow": "138,65,234",
        "vig": "0,0,0",
        "palette": [
          "#8a42eb",
          "#4db897",
          "#59b267",
          "#b8f5a2",
          "#d94c91",
          "#408fc7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 0.54,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.22,
        "sub": 0.89
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 78,
        "root": 189.1,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10128
      }
    },
    "compassj": {
      "name": "Compass J — Exploration",
      "bn": "Compass J — exploration",
      "dark": false,
      "c": {
        "bg": [
          "#1e3bd6",
          "#3933a3",
          "#112949"
        ],
        "ink": "#171923",
        "sub": "#8159b2",
        "accent": "#ebbc42",
        "accentL": "#a3a2f5",
        "accentD": "#b64db8",
        "accent2": "#b64db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,45,163",
        "glow": "234,187,65",
        "vig": "70,45,20",
        "palette": [
          "#ebbc42",
          "#b64db8",
          "#8159b2",
          "#a3a2f5",
          "#68d94c",
          "#c74068"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 0.71,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.33,
        "sub": 1.01
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 91,
        "root": 206.41,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10129
      }
    },
    "thesisa": {
      "name": "Thesis A — Analysis",
      "bn": "Thesis A — analysis",
      "dark": true,
      "c": {
        "bg": [
          "#6b5247",
          "#383129",
          "#291d1c"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2ab59",
        "accent": "#42c9eb",
        "accentL": "#f5cba2",
        "accentD": "#87b84d",
        "accent2": "#87b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,43,37",
        "glow": "65,201,234",
        "vig": "0,0,0",
        "palette": [
          "#42c9eb",
          "#87b84d",
          "#b2ab59",
          "#f5cba2",
          "#734cd9",
          "#40c758"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 0.88,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.44,
        "sub": 1.13
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 104,
        "root": 73.72,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10130
      }
    },
    "thesisb": {
      "name": "Thesis B — Analysis",
      "bn": "Thesis B — analysis",
      "dark": false,
      "c": {
        "bg": [
          "#6fd6ae",
          "#65a398",
          "#2a4934"
        ],
        "ink": "#171923",
        "sub": "#59a0b2",
        "accent": "#eb4298",
        "accentL": "#a2f5e3",
        "accentD": "#4d68b8",
        "accent2": "#4d68b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,163,132",
        "glow": "234,65,152",
        "vig": "70,45,20",
        "palette": [
          "#eb4298",
          "#4d68b8",
          "#59a0b2",
          "#a2f5e3",
          "#d99c4c",
          "#7f40c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 1.05,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.55,
        "sub": 1.25
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 117,
        "root": 91.03,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10131
      }
    },
    "thesisc": {
      "name": "Thesis C — Analysis",
      "bn": "Thesis C — analysis",
      "dark": true,
      "c": {
        "bg": [
          "#64296b",
          "#381c35",
          "#201229"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25986",
        "accent": "#67eb42",
        "accentL": "#f5a2ee",
        "accentD": "#b8514d",
        "accent2": "#b8514d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "52,21,56",
        "glow": "102,234,65",
        "vig": "0,0,0",
        "palette": [
          "#67eb42",
          "#b8514d",
          "#b25986",
          "#f5a2ee",
          "#4cd9c5",
          "#c7a640"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 1.22,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.45,
        "sub": 1.37
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 130,
        "root": 108.34,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10132
      }
    },
    "thesisd": {
      "name": "Thesis D — Analysis",
      "bn": "Thesis D — analysis",
      "dark": false,
      "c": {
        "bg": [
          "#b8d638",
          "#7ca343",
          "#494619"
        ],
        "ink": "#171923",
        "sub": "#6cb259",
        "accent": "#4e42eb",
        "accentL": "#d6f5a2",
        "accentD": "#4db870",
        "accent2": "#4db870",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "139,163,42",
        "glow": "77,65,234",
        "vig": "70,45,20",
        "palette": [
          "#4e42eb",
          "#4db870",
          "#6cb259",
          "#d6f5a2",
          "#d94cc3",
          "#40c0c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 1.39,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.56,
        "sub": 0.65
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 52,
        "root": 125.65,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10133
      }
    },
    "thesise": {
      "name": "Thesis E — Analysis",
      "bn": "Thesis E — analysis",
      "dark": true,
      "c": {
        "bg": [
          "#0f3f6b",
          "#121d38",
          "#092229"
        ],
        "ink": "#f7f4ed",
        "sub": "#6159b2",
        "accent": "#eb7f42",
        "accentL": "#a2bef5",
        "accentD": "#904db8",
        "accent2": "#904db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,32,56",
        "glow": "234,127,65",
        "vig": "0,0,0",
        "palette": [
          "#eb7f42",
          "#904db8",
          "#6159b2",
          "#a2bef5",
          "#9ad94c",
          "#c74098"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 1.56,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.67,
        "sub": 0.77
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 65,
        "root": 142.96,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10134
      }
    },
    "thesisf": {
      "name": "Thesis F — Analysis",
      "bn": "Thesis F — analysis",
      "dark": false,
      "c": {
        "bg": [
          "#d68d9e",
          "#a37777",
          "#49333e"
        ],
        "ink": "#171923",
        "sub": "#b27b59",
        "accent": "#42ebb0",
        "accentL": "#f5a2a5",
        "accentD": "#b8af4d",
        "accent2": "#b8af4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,107,120",
        "glow": "65,234,176",
        "vig": "70,45,20",
        "palette": [
          "#42ebb0",
          "#b8af4d",
          "#b27b59",
          "#f5a2a5",
          "#4c71d9",
          "#71c740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 0.2,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.78,
        "sub": 0.89
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 78,
        "root": 160.27,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10135
      }
    },
    "thesisg": {
      "name": "Thesis G — Analysis",
      "bn": "Thesis G — analysis",
      "dark": true,
      "c": {
        "bg": [
          "#386b3b",
          "#233829",
          "#1b2917"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b295",
        "accent": "#e242eb",
        "accentL": "#a2f5b6",
        "accentD": "#4da1b8",
        "accent2": "#4da1b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,56,30",
        "glow": "225,65,234",
        "vig": "0,0,0",
        "palette": [
          "#e242eb",
          "#4da1b8",
          "#59b295",
          "#a2f5b6",
          "#d9504c",
          "#4049c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 0.37,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.89,
        "sub": 1.01
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 91,
        "root": 177.58,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10136
      }
    },
    "thesish": {
      "name": "Thesis H — Analysis",
      "bn": "Thesis H — analysis",
      "dark": false,
      "c": {
        "bg": [
          "#8151d6",
          "#8052a3",
          "#242049"
        ],
        "ink": "#171923",
        "sub": "#af59b2",
        "accent": "#c2eb42",
        "accentL": "#cea2f5",
        "accentD": "#b84d82",
        "accent2": "#b84d82",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "98,62,163",
        "glow": "194,234,65",
        "vig": "70,45,20",
        "palette": [
          "#c2eb42",
          "#b84d82",
          "#af59b2",
          "#cea2f5",
          "#4cd979",
          "#c75d40"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 0.54,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.0,
        "sub": 1.13
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 104,
        "root": 194.89,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10137
      }
    },
    "thesisi": {
      "name": "Thesis I — Analysis",
      "bn": "Thesis I — analysis",
      "dark": true,
      "c": {
        "bg": [
          "#6b4f1c",
          "#383317",
          "#29180e"
        ],
        "ink": "#f7f4ed",
        "sub": "#9cb259",
        "accent": "#4291eb",
        "accentL": "#f5e7a2",
        "accentD": "#63b84d",
        "accent2": "#63b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,41,14",
        "glow": "65,144,234",
        "vig": "0,0,0",
        "palette": [
          "#4291eb",
          "#63b84d",
          "#9cb259",
          "#f5e7a2",
          "#a24cd9",
          "#40c785"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 0.71,
        "motion": "drift",
        "spot": false
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.11,
        "sub": 1.25
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 117,
        "root": 212.2,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10138
      }
    },
    "thesisj": {
      "name": "Thesis J — Analysis",
      "bn": "Thesis J — analysis",
      "dark": false,
      "c": {
        "bg": [
          "#1ed6cc",
          "#3392a3",
          "#114937"
        ],
        "ink": "#171923",
        "sub": "#5982b2",
        "accent": "#eb4260",
        "accentL": "#a2ebf5",
        "accentD": "#564db8",
        "accent2": "#564db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,163,155",
        "glow": "234,65,95",
        "vig": "70,45,20",
        "palette": [
          "#eb4260",
          "#564db8",
          "#5982b2",
          "#a2ebf5",
          "#d9cb4c",
          "#ac40c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 0.88,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.22,
        "sub": 1.37
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 130,
        "root": 79.51,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10139
      }
    },
    "storybooka": {
      "name": "Storybook A — Storytelling",
      "bn": "Storybook A — storytelling",
      "dark": true,
      "c": {
        "bg": [
          "#6b475c",
          "#38292f",
          "#291c27"
        ],
        "ink": "#f7f4ed",
        "sub": "#b25b59",
        "accent": "#42eb74",
        "accentL": "#f5a2c3",
        "accentD": "#b8894d",
        "accent2": "#b8894d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,37,48",
        "glow": "65,234,116",
        "vig": "0,0,0",
        "palette": [
          "#42eb74",
          "#b8894d",
          "#b25b59",
          "#f5a2c3",
          "#4ca3d9",
          "#a1c740"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.05,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.33,
        "sub": 0.65
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 52,
        "root": 96.82,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10140
      }
    },
    "storybookb": {
      "name": "Storybook B — Storytelling",
      "bn": "Storybook B — storytelling",
      "dark": false,
      "c": {
        "bg": [
          "#8dd66f",
          "#6aa365",
          "#3b492a"
        ],
        "ink": "#171923",
        "sub": "#59b275",
        "accent": "#a542eb",
        "accentL": "#abf5a2",
        "accentD": "#4db8a8",
        "accent2": "#4db8a8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,163,84",
        "glow": "165,65,234",
        "vig": "70,45,20",
        "palette": [
          "#a542eb",
          "#4db8a8",
          "#59b275",
          "#abf5a2",
          "#d94c7a",
          "#407ac7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 1.22,
        "motion": "kinetic",
        "spot": false
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.44,
        "sub": 0.77
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 65,
        "root": 114.13,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10141
      }
    },
    "storybookc": {
      "name": "Storybook C — Storytelling",
      "bn": "Storybook C — storytelling",
      "dark": true,
      "c": {
        "bg": [
          "#29296b",
          "#221c38",
          "#121829"
        ],
        "ink": "#f7f4ed",
        "sub": "#8f59b2",
        "accent": "#ebd742",
        "accentL": "#b1a2f5",
        "accentD": "#b84da9",
        "accent2": "#b84da9",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,21,56",
        "glow": "234,214,65",
        "vig": "0,0,0",
        "palette": [
          "#ebd742",
          "#b84da9",
          "#8f59b2",
          "#b1a2f5",
          "#51d94c",
          "#c74052"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 1.39,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.55,
        "sub": 0.89
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 78,
        "root": 131.44,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10142
      }
    },
    "storybookd": {
      "name": "Storybook D — Storytelling",
      "bn": "Storybook D — storytelling",
      "dark": false,
      "c": {
        "bg": [
          "#d66638",
          "#a37343",
          "#491a19"
        ],
        "ink": "#171923",
        "sub": "#b2a959",
        "accent": "#42cdeb",
        "accentL": "#f5c9a2",
        "accentD": "#89b84d",
        "accent2": "#89b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,77,42",
        "glow": "65,205,234",
        "vig": "70,45,20",
        "palette": [
          "#42cdeb",
          "#89b84d",
          "#b2a959",
          "#f5c9a2",
          "#704cd9",
          "#40c754"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 1.56,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.45,
        "sub": 1.01
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 91,
        "root": 148.75,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10143
      }
    },
    "storybooke": {
      "name": "Storybook E — Storytelling",
      "bn": "Storybook E — storytelling",
      "dark": true,
      "c": {
        "bg": [
          "#0f6b45",
          "#123830",
          "#092913"
        ],
        "ink": "#f7f4ed",
        "sub": "#59a2b2",
        "accent": "#eb429c",
        "accentL": "#a2f5e1",
        "accentD": "#4d6ab8",
        "accent2": "#4d6ab8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "7,56,36",
        "glow": "234,65,156",
        "vig": "0,0,0",
        "palette": [
          "#eb429c",
          "#4d6ab8",
          "#59a2b2",
          "#a2f5e1",
          "#d9994c",
          "#7c40c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 0.2,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.56,
        "sub": 1.13
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 104,
        "root": 166.06,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10144
      }
    },
    "storybookf": {
      "name": "Storybook F — Storytelling",
      "bn": "Storybook F — storytelling",
      "dark": false,
      "c": {
        "bg": [
          "#cd8dd6",
          "#a3779f",
          "#413349"
        ],
        "ink": "#171923",
        "sub": "#b25988",
        "accent": "#6beb42",
        "accentL": "#f5a2f0",
        "accentD": "#b84f4d",
        "accent2": "#b84f4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "156,107,163",
        "glow": "106,234,65",
        "vig": "70,45,20",
        "palette": [
          "#6beb42",
          "#b84f4d",
          "#b25988",
          "#f5a2f0",
          "#4cd9c2",
          "#c7a340"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 0.37,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.67,
        "sub": 1.25
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 117,
        "root": 183.37,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10145
      }
    },
    "storybookg": {
      "name": "Storybook G — Storytelling",
      "bn": "Storybook G — storytelling",
      "dark": true,
      "c": {
        "bg": [
          "#626b38",
          "#303823",
          "#292717"
        ],
        "ink": "#f7f4ed",
        "sub": "#6eb259",
        "accent": "#4a42eb",
        "accentL": "#d8f5a2",
        "accentD": "#4db86e",
        "accent2": "#4db86e",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "51,56,29",
        "glow": "73,65,234",
        "vig": "0,0,0",
        "palette": [
          "#4a42eb",
          "#4db86e",
          "#6eb259",
          "#d8f5a2",
          "#d94cc7",
          "#40c3c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 0.54,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.78,
        "sub": 1.37
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 130,
        "root": 200.68,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10146
      }
    },
    "storybookh": {
      "name": "Storybook H — Storytelling",
      "bn": "Storybook H — storytelling",
      "dark": false,
      "c": {
        "bg": [
          "#5199d6",
          "#526da3",
          "#204249"
        ],
        "ink": "#171923",
        "sub": "#5f59b2",
        "accent": "#eb7b42",
        "accentL": "#a2bff5",
        "accentD": "#8d4db8",
        "accent2": "#8d4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,116,163",
        "glow": "234,123,65",
        "vig": "70,45,20",
        "palette": [
          "#eb7b42",
          "#8d4db8",
          "#5f59b2",
          "#a2bff5",
          "#9dd94c",
          "#c7409c"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 0.71,
        "motion": "snap",
        "spot": false
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.89,
        "sub": 0.65
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 52,
        "root": 217.99,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10147
      }
    },
    "storybooki": {
      "name": "Storybook I — Storytelling",
      "bn": "Storybook I — storytelling",
      "dark": true,
      "c": {
        "bg": [
          "#6b1c2f",
          "#381718",
          "#290e1c"
        ],
        "ink": "#f7f4ed",
        "sub": "#b27959",
        "accent": "#42ebad",
        "accentL": "#f5a2a7",
        "accentD": "#b8ac4d",
        "accent2": "#b8ac4d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,14,24",
        "glow": "65,234,172",
        "vig": "0,0,0",
        "palette": [
          "#42ebad",
          "#b8ac4d",
          "#b27959",
          "#f5a2a7",
          "#4c74d9",
          "#74c740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 0.88,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.0,
        "sub": 0.77
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 65,
        "root": 85.3,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10148
      }
    },
    "storybookj": {
      "name": "Storybook J — Storytelling",
      "bn": "Storybook J — storytelling",
      "dark": false,
      "c": {
        "bg": [
          "#1ed626",
          "#33a34f",
          "#1d4911"
        ],
        "ink": "#171923",
        "sub": "#59b293",
        "accent": "#de42eb",
        "accentL": "#a2f5b4",
        "accentD": "#4da4b8",
        "accent2": "#4da4b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,163,29",
        "glow": "221,65,234",
        "vig": "70,45,20",
        "palette": [
          "#de42eb",
          "#4da4b8",
          "#59b293",
          "#a2f5b4",
          "#d94c4c",
          "#404dc7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 1.05,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.11,
        "sub": 0.89
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 78,
        "root": 102.61,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10149
      }
    },
    "blueprinta": {
      "name": "Blueprint A — Explanation",
      "bn": "Blueprint A — explanation",
      "dark": true,
      "c": {
        "bg": [
          "#5a476b",
          "#342938",
          "#1f1c29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b259a8",
        "accent": "#a7eb42",
        "accentL": "#dca2f5",
        "accentD": "#b84d71",
        "accent2": "#b84d71",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "46,37,56",
        "glow": "167,234,65",
        "vig": "0,0,0",
        "palette": [
          "#a7eb42",
          "#b84d71",
          "#b259a8",
          "#dca2f5",
          "#4cd98f",
          "#c77340"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 1.22,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.22,
        "sub": 1.01
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 91,
        "root": 119.92,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10150
      }
    },
    "blueprintb": {
      "name": "Blueprint B — Explanation",
      "bn": "Blueprint B — explanation",
      "dark": false,
      "c": {
        "bg": [
          "#d6c36f",
          "#a2a365",
          "#493b2a"
        ],
        "ink": "#171923",
        "sub": "#8eb259",
        "accent": "#4276eb",
        "accentL": "#f5f4a2",
        "accentD": "#52b84d",
        "accent2": "#52b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,148,84",
        "glow": "65,117,234",
        "vig": "70,45,20",
        "palette": [
          "#4276eb",
          "#52b84d",
          "#8eb259",
          "#f5f4a2",
          "#b94cd9",
          "#40c79a"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 1.39,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.33,
        "sub": 1.13
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 104,
        "root": 137.23,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10151
      }
    },
    "blueprintc": {
      "name": "Blueprint C — Explanation",
      "bn": "Blueprint C — explanation",
      "dark": true,
      "c": {
        "bg": [
          "#29646b",
          "#1c2f38",
          "#122925"
        ],
        "ink": "#f7f4ed",
        "sub": "#5974b2",
        "accent": "#eb4245",
        "accentL": "#a2ddf5",
        "accentD": "#674db8",
        "accent2": "#674db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,52,56",
        "glow": "234,65,68",
        "vig": "0,0,0",
        "palette": [
          "#eb4245",
          "#674db8",
          "#5974b2",
          "#a2ddf5",
          "#d0d94c",
          "#c240c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 1.56,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 1.44,
        "sub": 1.25
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 117,
        "root": 154.54,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10152
      }
    },
    "blueprintd": {
      "name": "Blueprint D — Explanation",
      "bn": "Blueprint D — explanation",
      "dark": false,
      "c": {
        "bg": [
          "#d63898",
          "#a34369",
          "#491943"
        ],
        "ink": "#171923",
        "sub": "#b2595a",
        "accent": "#42eb70",
        "accentL": "#f5a2c5",
        "accentD": "#b8864d",
        "accent2": "#b8864d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,42,115",
        "glow": "65,234,112",
        "vig": "70,45,20",
        "palette": [
          "#42eb70",
          "#b8864d",
          "#b2595a",
          "#f5a2c5",
          "#4ca7d9",
          "#a4c740"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 0.2,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.55,
        "sub": 1.37
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 171.85,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10153
      }
    },
    "blueprinte": {
      "name": "Blueprint E — Explanation",
      "bn": "Blueprint E — explanation",
      "dark": true,
      "c": {
        "bg": [
          "#2c6b0f",
          "#153812",
          "#1c2909"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b273",
        "accent": "#a142eb",
        "accentL": "#adf5a2",
        "accentD": "#4db8a5",
        "accent2": "#4db8a5",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "22,56,7",
        "glow": "161,65,234",
        "vig": "0,0,0",
        "palette": [
          "#a142eb",
          "#4db8a5",
          "#59b273",
          "#adf5a2",
          "#d94c7e",
          "#407dc7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 0.37,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.45,
        "sub": 0.65
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 52,
        "root": 189.16,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10154
      }
    },
    "blueprintf": {
      "name": "Blueprint F — Explanation",
      "bn": "Blueprint F — explanation",
      "dark": false,
      "c": {
        "bg": [
          "#8d8fd6",
          "#7f77a3",
          "#333a49"
        ],
        "ink": "#171923",
        "sub": "#8d59b2",
        "accent": "#ebd342",
        "accentL": "#afa2f5",
        "accentD": "#b84dab",
        "accent2": "#b84dab",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,108,163",
        "glow": "234,210,65",
        "vig": "70,45,20",
        "palette": [
          "#ebd342",
          "#b84dab",
          "#8d59b2",
          "#afa2f5",
          "#55d94c",
          "#c74056"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 0.54,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.56,
        "sub": 0.77
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 65,
        "root": 206.47,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10155
      }
    },
    "blueprintg": {
      "name": "Blueprint G — Explanation",
      "bn": "Blueprint G — explanation",
      "dark": true,
      "c": {
        "bg": [
          "#6b4638",
          "#382d23",
          "#291717"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2a759",
        "accent": "#42d1eb",
        "accentL": "#f5c7a2",
        "accentD": "#8cb84d",
        "accent2": "#8cb84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,36,29",
        "glow": "65,209,234",
        "vig": "0,0,0",
        "palette": [
          "#42d1eb",
          "#8cb84d",
          "#b2a759",
          "#f5c7a2",
          "#6c4cd9",
          "#40c751"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 0.71,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.67,
        "sub": 0.89
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 78,
        "root": 73.78,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10156
      }
    },
    "blueprinth": {
      "name": "Blueprint H — Explanation",
      "bn": "Blueprint H — explanation",
      "dark": false,
      "c": {
        "bg": [
          "#51d69c",
          "#52a391",
          "#20492c"
        ],
        "ink": "#171923",
        "sub": "#59a4b2",
        "accent": "#eb42a0",
        "accentL": "#a2f5df",
        "accentD": "#4d6db8",
        "accent2": "#4d6db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "62,163,118",
        "glow": "234,65,159",
        "vig": "70,45,20",
        "palette": [
          "#eb42a0",
          "#4d6db8",
          "#59a4b2",
          "#a2f5df",
          "#d9954c",
          "#7940c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 0.88,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 0.78,
        "sub": 1.01
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 91,
        "root": 91.09,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10157
      }
    },
    "blueprinti": {
      "name": "Blueprint I — Explanation",
      "bn": "Blueprint I — explanation",
      "dark": true,
      "c": {
        "bg": [
          "#601c6b",
          "#381736",
          "#1d0e29"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2598a",
        "accent": "#6feb42",
        "accentL": "#f5a2f2",
        "accentD": "#b84d4e",
        "accent2": "#b84d4e",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "50,14,56",
        "glow": "110,234,65",
        "vig": "0,0,0",
        "palette": [
          "#6feb42",
          "#b84d4e",
          "#b2598a",
          "#f5a2f2",
          "#4cd9bf",
          "#c7a040"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 1.05,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 0.89,
        "sub": 1.13
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 104,
        "root": 108.4,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10158
      }
    },
    "blueprintj": {
      "name": "Blueprint J — Explanation",
      "bn": "Blueprint J — explanation",
      "dark": false,
      "c": {
        "bg": [
          "#bbd61e",
          "#7ba333",
          "#494211"
        ],
        "ink": "#171923",
        "sub": "#70b259",
        "accent": "#4642eb",
        "accentL": "#daf5a2",
        "accentD": "#4db86c",
        "accent2": "#4db86c",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "142,163,22",
        "glow": "70,65,234",
        "vig": "70,45,20",
        "palette": [
          "#4642eb",
          "#4db86c",
          "#70b259",
          "#daf5a2",
          "#d94cca",
          "#40c6c7"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 1.22,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.0,
        "sub": 1.25
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 117,
        "root": 125.71,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10159
      }
    },
    "monumenta": {
      "name": "Monument A — Culture",
      "bn": "Monument A — culture",
      "dark": true,
      "c": {
        "bg": [
          "#47546b",
          "#292b38",
          "#1c2429"
        ],
        "ink": "#f7f4ed",
        "sub": "#6d59b2",
        "accent": "#eb9642",
        "accentL": "#a2b2f5",
        "accentD": "#9e4db8",
        "accent2": "#9e4db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,44,56",
        "glow": "234,150,65",
        "vig": "0,0,0",
        "palette": [
          "#eb9642",
          "#9e4db8",
          "#6d59b2",
          "#a2b2f5",
          "#87d94c",
          "#c74086"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 1.39,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.11,
        "sub": 1.37
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 130,
        "root": 143.02,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10160
      }
    },
    "monumentb": {
      "name": "Monument B — Culture",
      "bn": "Monument B — culture",
      "dark": false,
      "c": {
        "bg": [
          "#d66f78",
          "#a36c65",
          "#492a35"
        ],
        "ink": "#171923",
        "sub": "#b28759",
        "accent": "#42ebc8",
        "accentL": "#f5a9a2",
        "accentD": "#b2b84d",
        "accent2": "#b2b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,84,91",
        "glow": "65,234,199",
        "vig": "70,45,20",
        "palette": [
          "#42ebc8",
          "#b2b84d",
          "#b28759",
          "#f5a9a2",
          "#4c5ed9",
          "#5ec740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 1.56,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.22,
        "sub": 0.65
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 52,
        "root": 160.33,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10161
      }
    },
    "monumentc": {
      "name": "Monument C — Culture",
      "bn": "Monument C — culture",
      "dark": true,
      "c": {
        "bg": [
          "#296b36",
          "#1c3828",
          "#142912"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b2a1",
        "accent": "#eb42dc",
        "accentL": "#a2f5c2",
        "accentD": "#4d93b8",
        "accent2": "#4d93b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "21,56,28",
        "glow": "234,65,220",
        "vig": "0,0,0",
        "palette": [
          "#eb42dc",
          "#4d93b8",
          "#59b2a1",
          "#a2f5c2",
          "#d9634c",
          "#4840c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 0.2,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.33,
        "sub": 0.77
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 65,
        "root": 177.64,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10162
      }
    },
    "monumentd": {
      "name": "Monument D — Culture",
      "bn": "Monument D — culture",
      "dark": false,
      "c": {
        "bg": [
          "#8638d6",
          "#8743a3",
          "#241949"
        ],
        "ink": "#171923",
        "sub": "#b259aa",
        "accent": "#abeb42",
        "accentL": "#daa2f5",
        "accentD": "#b84d74",
        "accent2": "#b84d74",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "102,42,163",
        "glow": "171,234,65",
        "vig": "70,45,20",
        "palette": [
          "#abeb42",
          "#b84d74",
          "#b259aa",
          "#daa2f5",
          "#4cd98c",
          "#c77040"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 0.37,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 1.44,
        "sub": 0.89
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 78,
        "root": 194.95,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10163
      }
    },
    "monumente": {
      "name": "Monument E — Culture",
      "bn": "Monument E — culture",
      "dark": true,
      "c": {
        "bg": [
          "#6b580f",
          "#383812",
          "#291a09"
        ],
        "ink": "#f7f4ed",
        "sub": "#90b259",
        "accent": "#427aeb",
        "accentL": "#f5f2a2",
        "accentD": "#55b84d",
        "accent2": "#55b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,45,7",
        "glow": "65,121,234",
        "vig": "0,0,0",
        "palette": [
          "#427aeb",
          "#55b84d",
          "#90b259",
          "#f5f2a2",
          "#b54cd9",
          "#40c797"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 0.54,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 1.55,
        "sub": 1.01
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 91,
        "root": 212.26,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10164
      }
    },
    "monumentf": {
      "name": "Monument F — Culture",
      "bn": "Monument F — culture",
      "dark": false,
      "c": {
        "bg": [
          "#8dd0d6",
          "#7796a3",
          "#334945"
        ],
        "ink": "#171923",
        "sub": "#5976b2",
        "accent": "#eb4248",
        "accentL": "#a2dff5",
        "accentD": "#654db8",
        "accent2": "#654db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,158,163",
        "glow": "234,65,72",
        "vig": "70,45,20",
        "palette": [
          "#eb4248",
          "#654db8",
          "#5976b2",
          "#a2dff5",
          "#d3d94c",
          "#bf40c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 0.71,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.45,
        "sub": 1.13
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 104,
        "root": 79.57,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10165
      }
    },
    "monumentg": {
      "name": "Monument G — Culture",
      "bn": "Monument G — culture",
      "dark": true,
      "c": {
        "bg": [
          "#6b3858",
          "#38232c",
          "#291727"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2595c",
        "accent": "#42eb6c",
        "accentL": "#f5a2c7",
        "accentD": "#b8844d",
        "accent2": "#b8844d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,29,46",
        "glow": "65,234,108",
        "vig": "0,0,0",
        "palette": [
          "#42eb6c",
          "#b8844d",
          "#b2595c",
          "#f5a2c7",
          "#4caad9",
          "#a8c740"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 0.88,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.56,
        "sub": 1.25
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 117,
        "root": 96.88,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10166
      }
    },
    "monumenth": {
      "name": "Monument H — Culture",
      "bn": "Monument H — culture",
      "dark": false,
      "c": {
        "bg": [
          "#7ed651",
          "#5da352",
          "#394920"
        ],
        "ink": "#171923",
        "sub": "#59b271",
        "accent": "#9d42eb",
        "accentL": "#aff5a2",
        "accentD": "#4db8a3",
        "accent2": "#4db8a3",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "96,163,62",
        "glow": "157,65,234",
        "vig": "70,45,20",
        "palette": [
          "#9d42eb",
          "#4db8a3",
          "#59b271",
          "#aff5a2",
          "#d94c81",
          "#4080c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 1.05,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.67,
        "sub": 1.37
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 130,
        "root": 114.19,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10167
      }
    },
    "monumenti": {
      "name": "Monument I — Culture",
      "bn": "Monument I — culture",
      "dark": true,
      "c": {
        "bg": [
          "#1c1f6b",
          "#1c1738",
          "#0e1629"
        ],
        "ink": "#f7f4ed",
        "sub": "#8b59b2",
        "accent": "#ebcf42",
        "accentL": "#ada2f5",
        "accentD": "#b84dad",
        "accent2": "#b84dad",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,16,56",
        "glow": "234,206,65",
        "vig": "0,0,0",
        "palette": [
          "#ebcf42",
          "#b84dad",
          "#8b59b2",
          "#ada2f5",
          "#58d94c",
          "#c74059"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 1.22,
        "motion": "drift",
        "spot": false
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 0.78,
        "sub": 0.65
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 52,
        "root": 131.5,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10168
      }
    },
    "monumentj": {
      "name": "Monument J — Culture",
      "bn": "Monument J — culture",
      "dark": false,
      "c": {
        "bg": [
          "#d64b1e",
          "#a36633",
          "#491112"
        ],
        "ink": "#171923",
        "sub": "#b2a559",
        "accent": "#42d5eb",
        "accentL": "#f5c5a2",
        "accentD": "#8eb84d",
        "accent2": "#8eb84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,57,22",
        "glow": "65,213,234",
        "vig": "70,45,20",
        "palette": [
          "#42d5eb",
          "#8eb84d",
          "#b2a559",
          "#f5c5a2",
          "#694cd9",
          "#40c74e"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 1.39,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 0.89,
        "sub": 0.77
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 65,
        "root": 148.81,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10169
      }
    },
    "spectruma": {
      "name": "Spectrum A — Ideas",
      "bn": "Spectrum A — ideas",
      "dark": true,
      "c": {
        "bg": [
          "#476b61",
          "#293837",
          "#1c2922"
        ],
        "ink": "#f7f4ed",
        "sub": "#5996b2",
        "accent": "#eb4285",
        "accentL": "#a2f5ed",
        "accentD": "#4d5cb8",
        "accent2": "#4d5cb8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "37,56,50",
        "glow": "234,65,132",
        "vig": "0,0,0",
        "palette": [
          "#eb4285",
          "#4d5cb8",
          "#5996b2",
          "#a2f5ed",
          "#d9ac4c",
          "#8e40c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "pill",
        "rule": "line",
        "rays": "none",
        "particles": "dust",
        "arch": "none",
        "upper": false,
        "ls": 1.56,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.0,
        "sub": 0.89
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 78,
        "root": 166.12,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10170
      }
    },
    "spectrumb": {
      "name": "Spectrum B — Ideas",
      "bn": "Spectrum B — ideas",
      "dark": false,
      "c": {
        "bg": [
          "#d66fd5",
          "#a36595",
          "#412a49"
        ],
        "ink": "#171923",
        "sub": "#b2597c",
        "accent": "#54eb42",
        "accentL": "#f5a2e5",
        "accentD": "#b85d4d",
        "accent2": "#b85d4d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,84,162",
        "glow": "83,234,65",
        "vig": "70,45,20",
        "palette": [
          "#54eb42",
          "#b85d4d",
          "#b2597c",
          "#f5a2e5",
          "#4cd9d5",
          "#c7b640"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "paper",
        "rule": "orn",
        "rays": "rings",
        "particles": "dot",
        "arch": "arch",
        "upper": true,
        "ls": 0.2,
        "motion": "kinetic",
        "spot": false
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.11,
        "sub": 1.01
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 91,
        "root": 183.43,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10171
      }
    },
    "spectrumc": {
      "name": "Spectrum C — Ideas",
      "bn": "Spectrum C — ideas",
      "dark": true,
      "c": {
        "bg": [
          "#576b29",
          "#2a381c",
          "#282912"
        ],
        "ink": "#f7f4ed",
        "sub": "#62b259",
        "accent": "#6142eb",
        "accentL": "#ccf5a2",
        "accentD": "#4db87d",
        "accent2": "#4db87d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "45,56,21",
        "glow": "97,65,234",
        "vig": "0,0,0",
        "palette": [
          "#6142eb",
          "#4db87d",
          "#62b259",
          "#ccf5a2",
          "#d94cb3",
          "#40b1c7"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "solid",
        "rule": "double",
        "rays": "sunburst",
        "particles": "confetti",
        "arch": "circle",
        "upper": false,
        "ls": 0.37,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.22,
        "sub": 1.13
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 104,
        "root": 200.74,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10172
      }
    },
    "spectrumd": {
      "name": "Spectrum D — Ideas",
      "bn": "Spectrum D — ideas",
      "dark": false,
      "c": {
        "bg": [
          "#3878d6",
          "#4355a3",
          "#193949"
        ],
        "ink": "#171923",
        "sub": "#6b59b2",
        "accent": "#eb9242",
        "accentL": "#a2b4f5",
        "accentD": "#9c4db8",
        "accent2": "#9c4db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,91,163",
        "glow": "234,146,65",
        "vig": "70,45,20",
        "palette": [
          "#eb9242",
          "#9c4db8",
          "#6b59b2",
          "#a2b4f5",
          "#8ad94c",
          "#c74089"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "outline",
        "rule": "none",
        "rays": "beam",
        "particles": "star",
        "arch": "rounded",
        "upper": true,
        "ls": 0.54,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.33,
        "sub": 1.25
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 117,
        "root": 218.05,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10173
      }
    },
    "spectrume": {
      "name": "Spectrum E — Ideas",
      "bn": "Spectrum E — ideas",
      "dark": true,
      "c": {
        "bg": [
          "#6b0f19",
          "#381512",
          "#290915"
        ],
        "ink": "#f7f4ed",
        "sub": "#b28559",
        "accent": "#42ebc4",
        "accentL": "#f5a7a2",
        "accentD": "#b4b84d",
        "accent2": "#b4b84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,7,13",
        "glow": "65,234,195",
        "vig": "0,0,0",
        "palette": [
          "#42ebc4",
          "#b4b84d",
          "#b28559",
          "#f5a7a2",
          "#4c61d9",
          "#62c740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "glass",
        "rule": "dot",
        "rays": "orbit",
        "particles": "none",
        "arch": "cut",
        "upper": false,
        "ls": 0.71,
        "motion": "float",
        "spot": false
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 1.44,
        "sub": 1.37
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 130,
        "root": 85.36,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10174
      }
    },
    "spectrumf": {
      "name": "Spectrum F — Ideas",
      "bn": "Spectrum F — ideas",
      "dark": false,
      "c": {
        "bg": [
          "#8dd69b",
          "#77a388",
          "#354933"
        ],
        "ink": "#171923",
        "sub": "#59b29f",
        "accent": "#eb42e0",
        "accentL": "#a2f5c0",
        "accentD": "#4d95b8",
        "accent2": "#4d95b8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "107,163,117",
        "glow": "234,65,224",
        "vig": "70,45,20",
        "palette": [
          "#eb42e0",
          "#4d95b8",
          "#59b29f",
          "#a2f5c0",
          "#d9604c",
          "#4540c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "orn": "leaf",
        "chip": "none",
        "rule": "line",
        "rays": "none",
        "particles": "spark",
        "arch": "none",
        "upper": true,
        "ls": 0.88,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 1.55,
        "sub": 0.65
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 52,
        "root": 102.67,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10175
      }
    },
    "spectrumg": {
      "name": "Spectrum G — Ideas",
      "bn": "Spectrum G — ideas",
      "dark": true,
      "c": {
        "bg": [
          "#50386b",
          "#312338",
          "#1b1729"
        ],
        "ink": "#f7f4ed",
        "sub": "#b259ac",
        "accent": "#afeb42",
        "accentL": "#d8a2f5",
        "accentD": "#b84d76",
        "accent2": "#b84d76",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "41,29,56",
        "glow": "175,234,65",
        "vig": "0,0,0",
        "palette": [
          "#afeb42",
          "#b84d76",
          "#b259ac",
          "#d8a2f5",
          "#4cd989",
          "#c76d40"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "orn": "circle",
        "chip": "pill",
        "rule": "orn",
        "rays": "rings",
        "particles": "dust",
        "arch": "arch",
        "upper": false,
        "ls": 1.05,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.45,
        "sub": 0.77
      },
      "bgm": {
        "genre": "synth_bass",
        "mode": "lydian",
        "tempo": 65,
        "root": 119.98,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10176
      }
    },
    "spectrumh": {
      "name": "Spectrum H — Ideas",
      "bn": "Spectrum H — ideas",
      "dark": false,
      "c": {
        "bg": [
          "#d6b751",
          "#a3a152",
          "#493520"
        ],
        "ink": "#171923",
        "sub": "#92b259",
        "accent": "#427eeb",
        "accentL": "#f5f0a2",
        "accentD": "#57b84d",
        "accent2": "#57b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,139,62",
        "glow": "65,125,234",
        "vig": "70,45,20",
        "palette": [
          "#427eeb",
          "#57b84d",
          "#92b259",
          "#f5f0a2",
          "#b24cd9",
          "#40c794"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "paper",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dot",
        "arch": "circle",
        "upper": true,
        "ls": 1.22,
        "motion": "snap",
        "spot": false
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.56,
        "sub": 0.89
      },
      "bgm": {
        "genre": "kalimba",
        "mode": "pentatonic",
        "tempo": 78,
        "root": 137.29,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10177
      }
    },
    "spectrumi": {
      "name": "Spectrum I — Ideas",
      "bn": "Spectrum I — ideas",
      "dark": true,
      "c": {
        "bg": [
          "#1c676b",
          "#172f38",
          "#0e2923"
        ],
        "ink": "#f7f4ed",
        "sub": "#5978b2",
        "accent": "#eb424c",
        "accentL": "#a2e1f5",
        "accentD": "#624db8",
        "accent2": "#624db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,53,56",
        "glow": "234,65,76",
        "vig": "0,0,0",
        "palette": [
          "#eb424c",
          "#624db8",
          "#5978b2",
          "#a2e1f5",
          "#d6d94c",
          "#bc40c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "solid",
        "rule": "none",
        "rays": "beam",
        "particles": "confetti",
        "arch": "rounded",
        "upper": false,
        "ls": 1.39,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.67,
        "sub": 1.01
      },
      "bgm": {
        "genre": "organ",
        "mode": "dorian",
        "tempo": 91,
        "root": 154.6,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10178
      }
    },
    "spectrumj": {
      "name": "Spectrum J — Ideas",
      "bn": "Spectrum J — ideas",
      "dark": false,
      "c": {
        "bg": [
          "#d61e96",
          "#a33365",
          "#491145"
        ],
        "ink": "#171923",
        "sub": "#b2595e",
        "accent": "#42eb68",
        "accentL": "#f5a2c9",
        "accentD": "#b8814d",
        "accent2": "#b8814d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,22,114",
        "glow": "65,234,104",
        "vig": "70,45,20",
        "palette": [
          "#42eb68",
          "#b8814d",
          "#b2595e",
          "#f5a2c9",
          "#4cadd9",
          "#abc740"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "outline",
        "rule": "dot",
        "rays": "orbit",
        "particles": "star",
        "arch": "cut",
        "upper": true,
        "ls": 1.56,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 0.78,
        "sub": 1.13
      },
      "bgm": {
        "genre": "choir_pad",
        "mode": "minor",
        "tempo": 104,
        "root": 171.91,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10179
      }
    },
    "workshopa": {
      "name": "Workshop A — How-To",
      "bn": "Workshop A — how-to",
      "dark": true,
      "c": {
        "bg": [
          "#4d6b47",
          "#293829",
          "#22291c"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b27f",
        "accent": "#b842eb",
        "accentL": "#a2f5a2",
        "accentD": "#4db8b4",
        "accent2": "#4db8b4",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "40,56,37",
        "glow": "184,65,234",
        "vig": "0,0,0",
        "palette": [
          "#b842eb",
          "#4db8b4",
          "#59b27f",
          "#a2f5a2",
          "#d94c6a",
          "#406ac7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "grid",
        "frame": "line",
        "orn": "diamond",
        "chip": "glass",
        "rule": "line",
        "rays": "none",
        "particles": "none",
        "arch": "none",
        "upper": false,
        "ls": 0.2,
        "motion": "smooth",
        "spot": false
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 0.89,
        "sub": 1.25
      },
      "bgm": {
        "genre": "muted_guitar",
        "mode": "major",
        "tempo": 117,
        "root": 189.22,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10180
      }
    },
    "workshopb": {
      "name": "Workshop B — How-To",
      "bn": "Workshop B — how-to",
      "dark": false,
      "c": {
        "bg": [
          "#7b6fd6",
          "#7965a3",
          "#2a2f49"
        ],
        "ink": "#171923",
        "sub": "#9959b2",
        "accent": "#ebea42",
        "accentL": "#baa2f5",
        "accentD": "#b84d9c",
        "accent2": "#b84d9c",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "93,84,163",
        "glow": "234,233,65",
        "vig": "70,45,20",
        "palette": [
          "#ebea42",
          "#b84d9c",
          "#9959b2",
          "#baa2f5",
          "#4cd956",
          "#c74043"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "dots",
        "frame": "double",
        "orn": "spark",
        "chip": "none",
        "rule": "orn",
        "rays": "rings",
        "particles": "spark",
        "arch": "arch",
        "upper": true,
        "ls": 0.37,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.0,
        "sub": 1.37
      },
      "bgm": {
        "genre": "harp",
        "mode": "mixolydian",
        "tempo": 130,
        "root": 206.53,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10181
      }
    },
    "workshopc": {
      "name": "Workshop C — How-To",
      "bn": "Workshop C — how-to",
      "dark": true,
      "c": {
        "bg": [
          "#6b4429",
          "#382d1c",
          "#291512"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2b259",
        "accent": "#42baeb",
        "accentL": "#f5d2a2",
        "accentD": "#7db84d",
        "accent2": "#7db84d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,35,21",
        "glow": "65,186,234",
        "vig": "0,0,0",
        "palette": [
          "#42baeb",
          "#7db84d",
          "#b2b259",
          "#f5d2a2",
          "#804cd9",
          "#40c764"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "diagonal",
        "frame": "none",
        "orn": "dot",
        "chip": "pill",
        "rule": "double",
        "rays": "sunburst",
        "particles": "dust",
        "arch": "circle",
        "upper": false,
        "ls": 0.54,
        "motion": "stagger",
        "spot": true
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.11,
        "sub": 0.65
      },
      "bgm": {
        "genre": "soft_brass",
        "mode": "lydian",
        "tempo": 52,
        "root": 73.84,
        "rhythm": "syncopated",
        "brightness": 0.29,
        "seed": 10182
      }
    },
    "workshopd": {
      "name": "Workshop D — How-To",
      "bn": "Workshop D — how-to",
      "dark": false,
      "c": {
        "bg": [
          "#38d6a6",
          "#43a39a",
          "#19492d"
        ],
        "ink": "#171923",
        "sub": "#5998b2",
        "accent": "#eb4289",
        "accentL": "#a2f5eb",
        "accentD": "#4d5eb8",
        "accent2": "#4d5eb8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "42,163,126",
        "glow": "234,65,136",
        "vig": "70,45,20",
        "palette": [
          "#eb4289",
          "#4d5eb8",
          "#5998b2",
          "#a2f5eb",
          "#d9a94c",
          "#8b40c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "wave",
        "frame": "neon",
        "orn": "plus",
        "chip": "paper",
        "rule": "none",
        "rays": "beam",
        "particles": "dot",
        "arch": "rounded",
        "upper": true,
        "ls": 0.71,
        "motion": "pulse",
        "spot": false
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.22,
        "sub": 0.77
      },
      "bgm": {
        "genre": "glass_pad",
        "mode": "pentatonic",
        "tempo": 65,
        "root": 91.15,
        "rhythm": "arpeggio",
        "brightness": 0.375,
        "seed": 10183
      }
    },
    "workshope": {
      "name": "Workshop E — How-To",
      "bn": "Workshop E — how-to",
      "dark": true,
      "c": {
        "bg": [
          "#6a0f6b",
          "#381230",
          "#200929"
        ],
        "ink": "#f7f4ed",
        "sub": "#b2597e",
        "accent": "#58eb42",
        "accentL": "#f5a2e7",
        "accentD": "#b85b4d",
        "accent2": "#b85b4d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "55,7,56",
        "glow": "87,234,65",
        "vig": "0,0,0",
        "palette": [
          "#58eb42",
          "#b85b4d",
          "#b2597e",
          "#f5a2e7",
          "#4cd9d2",
          "#c7b340"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "rings",
        "frame": "ticket",
        "orn": "wave",
        "chip": "solid",
        "rule": "dot",
        "rays": "orbit",
        "particles": "confetti",
        "arch": "cut",
        "upper": false,
        "ls": 0.88,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.33,
        "sub": 0.89
      },
      "bgm": {
        "genre": "handpan",
        "mode": "dorian",
        "tempo": 78,
        "root": 108.46,
        "rhythm": "waltz",
        "brightness": 0.46,
        "seed": 10184
      }
    },
    "workshopf": {
      "name": "Workshop F — How-To",
      "bn": "Workshop F — how-to",
      "dark": false,
      "c": {
        "bg": [
          "#c2d68d",
          "#8da377",
          "#494933"
        ],
        "ink": "#171923",
        "sub": "#64b259",
        "accent": "#5d42eb",
        "accentL": "#cef5a2",
        "accentD": "#4db87a",
        "accent2": "#4db87a",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "147,163,107",
        "glow": "93,65,234",
        "vig": "70,45,20",
        "palette": [
          "#5d42eb",
          "#4db87a",
          "#64b259",
          "#cef5a2",
          "#d94cb7",
          "#40b4c7"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "scan",
        "frame": "line",
        "orn": "leaf",
        "chip": "outline",
        "rule": "line",
        "rays": "none",
        "particles": "star",
        "arch": "none",
        "upper": true,
        "ls": 1.05,
        "motion": "parallax",
        "spot": true
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 1.44,
        "sub": 1.01
      },
      "bgm": {
        "genre": "woodblock",
        "mode": "minor",
        "tempo": 91,
        "root": 125.77,
        "rhythm": "ostinato",
        "brightness": 0.545,
        "seed": 10185
      }
    },
    "workshopg": {
      "name": "Workshop G — How-To",
      "bn": "Workshop G — how-to",
      "dark": true,
      "c": {
        "bg": [
          "#384e6b",
          "#232738",
          "#172329"
        ],
        "ink": "#f7f4ed",
        "sub": "#6959b2",
        "accent": "#eb8e42",
        "accentL": "#a2b6f5",
        "accentD": "#994db8",
        "accent2": "#994db8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,40,56",
        "glow": "234,142,65",
        "vig": "0,0,0",
        "palette": [
          "#eb8e42",
          "#994db8",
          "#6959b2",
          "#a2b6f5",
          "#8ed94c",
          "#c7408c"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "crosshatch",
        "frame": "double",
        "orn": "circle",
        "chip": "glass",
        "rule": "orn",
        "rays": "rings",
        "particles": "none",
        "arch": "arch",
        "upper": false,
        "ls": 1.22,
        "motion": "rise",
        "spot": false
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 1.55,
        "sub": 1.13
      },
      "bgm": {
        "genre": "rhodes",
        "mode": "major",
        "tempo": 104,
        "root": 143.08,
        "rhythm": "drone",
        "brightness": 0.63,
        "seed": 10186
      }
    },
    "workshoph": {
      "name": "Workshop H — How-To",
      "bn": "Workshop H — how-to",
      "dark": false,
      "c": {
        "bg": [
          "#d65163",
          "#a35852",
          "#492031"
        ],
        "ink": "#171923",
        "sub": "#b28359",
        "accent": "#42ebc0",
        "accentL": "#f5a5a2",
        "accentD": "#b7b84d",
        "accent2": "#b7b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,62,75",
        "glow": "65,234,191",
        "vig": "70,45,20",
        "palette": [
          "#42ebc0",
          "#b7b84d",
          "#b28359",
          "#f5a5a2",
          "#4c64d9",
          "#65c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "topographic",
        "frame": "none",
        "orn": "none",
        "chip": "none",
        "rule": "double",
        "rays": "sunburst",
        "particles": "spark",
        "arch": "circle",
        "upper": true,
        "ls": 1.39,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.945,
        "bright": 0.45,
        "sub": 1.25
      },
      "bgm": {
        "genre": "celesta",
        "mode": "mixolydian",
        "tempo": 117,
        "root": 160.39,
        "rhythm": "pulse",
        "brightness": 0.715,
        "seed": 10187
      }
    },
    "workshopi": {
      "name": "Workshop I — How-To",
      "bn": "Workshop I — how-to",
      "dark": true,
      "c": {
        "bg": [
          "#1c6b28",
          "#173823",
          "#11290e"
        ],
        "ink": "#f7f4ed",
        "sub": "#59b29d",
        "accent": "#eb42e4",
        "accentL": "#a2f5be",
        "accentD": "#4d98b8",
        "accent2": "#4d98b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "14,56,21",
        "glow": "234,65,228",
        "vig": "0,0,0",
        "palette": [
          "#eb42e4",
          "#4d98b8",
          "#59b29d",
          "#a2f5be",
          "#d95c4c",
          "#4240c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "stripes",
        "frame": "neon",
        "orn": "square",
        "chip": "pill",
        "rule": "none",
        "rays": "beam",
        "particles": "dust",
        "arch": "rounded",
        "upper": false,
        "ls": 1.56,
        "motion": "drift",
        "spot": true
      },
      "sfx": {
        "pitch": 0.99,
        "bright": 0.56,
        "sub": 1.37
      },
      "bgm": {
        "genre": "qanun_like",
        "mode": "lydian",
        "tempo": 130,
        "root": 177.7,
        "rhythm": "syncopated",
        "brightness": 0.8,
        "seed": 10188
      }
    },
    "workshopj": {
      "name": "Workshop J — How-To",
      "bn": "Workshop J — how-to",
      "dark": false,
      "c": {
        "bg": [
          "#711ed6",
          "#7d33a3",
          "#1b1149"
        ],
        "ink": "#171923",
        "sub": "#b259ae",
        "accent": "#b3eb42",
        "accentL": "#d6a2f5",
        "accentD": "#b84d79",
        "accent2": "#b84d79",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "85,22,163",
        "glow": "178,234,65",
        "vig": "70,45,20",
        "palette": [
          "#b3eb42",
          "#b84d79",
          "#b259ae",
          "#d6a2f5",
          "#4cd986",
          "#c76a40"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "grain",
        "frame": "ticket",
        "orn": "star",
        "chip": "paper",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dot",
        "arch": "cut",
        "upper": true,
        "ls": 0.2,
        "motion": "orbit",
        "spot": false
      },
      "sfx": {
        "pitch": 1.035,
        "bright": 0.67,
        "sub": 0.65
      },
      "bgm": {
        "genre": "flute_pad",
        "mode": "pentatonic",
        "tempo": 52,
        "root": 195.01,
        "rhythm": "arpeggio",
        "brightness": 0.12,
        "seed": 10189
      }
    },
    "observatorya": {
      "name": "Observatory A — Discovery",
      "bn": "Observatory A — discovery",
      "dark": true,
      "c": {
        "bg": [
          "#6b6847",
          "#363829",
          "#29241c"
        ],
        "ink": "#f7f4ed",
        "sub": "#84b259",
        "accent": "#4263eb",
        "accentL": "#ecf5a2",
        "accentD": "#4db854",
        "accent2": "#4db854",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,54,37",
        "glow": "65,98,234",
        "vig": "0,0,0",
        "palette": [
          "#4263eb",
          "#4db854",
          "#84b259",
          "#ecf5a2",
          "#c84cd9",
          "#40c7aa"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "starfield",
        "frame": "line",
        "orn": "diamond",
        "chip": "solid",
        "rule": "line",
        "rays": "none",
        "particles": "confetti",
        "arch": "none",
        "upper": false,
        "ls": 0.37,
        "motion": "smooth",
        "spot": true
      },
      "sfx": {
        "pitch": 1.08,
        "bright": 0.78,
        "sub": 0.77
      },
      "bgm": {
        "genre": "bass_pulse",
        "mode": "dorian",
        "tempo": 65,
        "root": 212.32,
        "rhythm": "waltz",
        "brightness": 0.205,
        "seed": 10190
      }
    },
    "observatoryb": {
      "name": "Observatory B — Discovery",
      "bn": "Observatory B — discovery",
      "dark": false,
      "c": {
        "bg": [
          "#6fc0d6",
          "#6588a3",
          "#2a4948"
        ],
        "ink": "#171923",
        "sub": "#596ab2",
        "accent": "#eb5242",
        "accentL": "#a2d4f5",
        "accentD": "#734db8",
        "accent2": "#734db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "84,146,163",
        "glow": "234,81,65",
        "vig": "70,45,20",
        "palette": [
          "#eb5242",
          "#734db8",
          "#596ab2",
          "#a2d4f5",
          "#c0d94c",
          "#c740bd"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "contour",
        "frame": "double",
        "orn": "spark",
        "chip": "outline",
        "rule": "orn",
        "rays": "rings",
        "particles": "star",
        "arch": "arch",
        "upper": true,
        "ls": 0.54,
        "motion": "kinetic",
        "spot": true
      },
      "sfx": {
        "pitch": 1.125,
        "bright": 0.89,
        "sub": 0.89
      },
      "bgm": {
        "genre": "arp_synth",
        "mode": "minor",
        "tempo": 78,
        "root": 79.63,
        "rhythm": "ostinato",
        "brightness": 0.29,
        "seed": 10191
      }
    },
    "observatoryc": {
      "name": "Observatory C — Discovery",
      "bn": "Observatory C — discovery",
      "dark": true,
      "c": {
        "bg": [
          "#6b2949",
          "#381c24",
          "#291223"
        ],
        "ink": "#f7f4ed",
        "sub": "#b26359",
        "accent": "#42eb83",
        "accentL": "#f5a2bc",
        "accentD": "#b8924d",
        "accent2": "#b8924d",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "56,21,38",
        "glow": "65,234,131",
        "vig": "0,0,0",
        "palette": [
          "#42eb83",
          "#b8924d",
          "#b26359",
          "#f5a2bc",
          "#4c97d9",
          "#95c740"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "checker",
        "frame": "none",
        "orn": "dot",
        "chip": "glass",
        "rule": "double",
        "rays": "sunburst",
        "particles": "none",
        "arch": "circle",
        "upper": false,
        "ls": 0.71,
        "motion": "stagger",
        "spot": false
      },
      "sfx": {
        "pitch": 1.17,
        "bright": 1.0,
        "sub": 1.01
      },
      "bgm": {
        "genre": "piano",
        "mode": "major",
        "tempo": 91,
        "root": 96.94,
        "rhythm": "drone",
        "brightness": 0.375,
        "seed": 10192
      }
    },
    "observatoryd": {
      "name": "Observatory D — Discovery",
      "bn": "Observatory D — discovery",
      "dark": false,
      "c": {
        "bg": [
          "#57d638",
          "#43a344",
          "#304919"
        ],
        "ink": "#171923",
        "sub": "#59b27d",
        "accent": "#b542eb",
        "accentL": "#a3f5a2",
        "accentD": "#4db8b1",
        "accent2": "#4db8b1",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "66,163,42",
        "glow": "180,65,234",
        "vig": "70,45,20",
        "palette": [
          "#b542eb",
          "#4db8b1",
          "#59b27d",
          "#a3f5a2",
          "#d94c6e",
          "#406ec7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "orbit",
        "frame": "neon",
        "orn": "plus",
        "chip": "none",
        "rule": "none",
        "rays": "beam",
        "particles": "spark",
        "arch": "rounded",
        "upper": true,
        "ls": 0.88,
        "motion": "pulse",
        "spot": true
      },
      "sfx": {
        "pitch": 1.215,
        "bright": 1.11,
        "sub": 1.13
      },
      "bgm": {
        "genre": "marimba",
        "mode": "mixolydian",
        "tempo": 104,
        "root": 114.25,
        "rhythm": "pulse",
        "brightness": 0.46,
        "seed": 10193
      }
    },
    "observatorye": {
      "name": "Observatory E — Discovery",
      "bn": "Observatory E — discovery",
      "dark": true,
      "c": {
        "bg": [
          "#170f6b",
          "#1d1238",
          "#090f29"
        ],
        "ink": "#f7f4ed",
        "sub": "#9759b2",
        "accent": "#ebe642",
        "accentL": "#b8a2f5",
        "accentD": "#b84d9f",
        "accent2": "#b84d9f",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "12,7,56",
        "glow": "234,229,65",
        "vig": "0,0,0",
        "palette": [
          "#ebe642",
          "#b84d9f",
          "#9759b2",
          "#b8a2f5",
          "#4cd953",
          "#c74046"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "woven",
        "frame": "ticket",
        "orn": "wave",
        "chip": "pill",
        "rule": "dot",
        "rays": "orbit",
        "particles": "dust",
        "arch": "cut",
        "upper": false,
        "ls": 1.05,
        "motion": "float",
        "spot": true
      },
      "sfx": {
        "pitch": 1.26,
        "bright": 1.22,
        "sub": 1.25
      },
      "bgm": {
        "genre": "analog_pad",
        "mode": "lydian",
        "tempo": 117,
        "root": 131.56,
        "rhythm": "syncopated",
        "brightness": 0.545,
        "seed": 10194
      }
    },
    "observatoryf": {
      "name": "Observatory F — Discovery",
      "bn": "Observatory F — discovery",
      "dark": false,
      "c": {
        "bg": [
          "#d6a98d",
          "#a39177",
          "#493633"
        ],
        "ink": "#171923",
        "sub": "#b2b159",
        "accent": "#42beeb",
        "accentL": "#f5d0a2",
        "accentD": "#80b84d",
        "accent2": "#80b84d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "163,128,107",
        "glow": "65,190,234",
        "vig": "70,45,20",
        "palette": [
          "#42beeb",
          "#80b84d",
          "#b2b159",
          "#f5d0a2",
          "#7c4cd9",
          "#40c761"
        ]
      },
      "font": {
        "display": "Space Grotesk",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "halftone",
        "frame": "line",
        "fw": 12,
        "orn": "leaf",
        "chip": "paper",
        "rule": "line",
        "rays": "none",
        "particles": "dot",
        "arch": "none",
        "upper": true,
        "ls": 1.22,
        "motion": "parallax",
        "spot": false
      },
      "sfx": {
        "pitch": 0.72,
        "bright": 1.33,
        "sub": 1.37
      },
      "bgm": {
        "genre": "plucked",
        "mode": "pentatonic",
        "tempo": 130,
        "root": 148.87,
        "rhythm": "arpeggio",
        "brightness": 0.63,
        "seed": 10195
      }
    },
    "observatoryg": {
      "name": "Observatory G — Discovery",
      "bn": "Observatory G — discovery",
      "dark": true,
      "c": {
        "bg": [
          "#386b5a",
          "#233836",
          "#17291e"
        ],
        "ink": "#f7f4ed",
        "sub": "#599ab2",
        "accent": "#eb428d",
        "accentL": "#a2f5e9",
        "accentD": "#4d61b8",
        "accent2": "#4d61b8",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "29,56,47",
        "glow": "234,65,140",
        "vig": "0,0,0",
        "palette": [
          "#eb428d",
          "#4d61b8",
          "#599ab2",
          "#a2f5e9",
          "#d9a54c",
          "#8840c7"
        ]
      },
      "font": {
        "display": "Montserrat",
        "body": "Source Sans 3",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "paper",
        "frame": "double",
        "fw": 2,
        "orn": "circle",
        "chip": "solid",
        "rule": "orn",
        "rays": "rings",
        "particles": "confetti",
        "arch": "arch",
        "upper": false,
        "ls": 1.39,
        "motion": "rise",
        "spot": true
      },
      "sfx": {
        "pitch": 0.765,
        "bright": 1.44,
        "sub": 0.65
      },
      "bgm": {
        "genre": "bell",
        "mode": "dorian",
        "tempo": 52,
        "root": 166.18,
        "rhythm": "waltz",
        "brightness": 0.715,
        "seed": 10196
      }
    },
    "observatoryh": {
      "name": "Observatory H — Discovery",
      "bn": "Observatory H — discovery",
      "dark": false,
      "c": {
        "bg": [
          "#d251d6",
          "#a35295",
          "#3d2049"
        ],
        "ink": "#171923",
        "sub": "#b25980",
        "accent": "#5ceb42",
        "accentL": "#f5a2e9",
        "accentD": "#b8594d",
        "accent2": "#b8594d",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "159,62,163",
        "glow": "91,234,65",
        "vig": "70,45,20",
        "palette": [
          "#5ceb42",
          "#b8594d",
          "#b25980",
          "#f5a2e9",
          "#4cd9ce",
          "#c7b040"
        ]
      },
      "font": {
        "display": "Syne",
        "body": "Inter",
        "bn": "Anek Bangla",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "ripple",
        "frame": "none",
        "orn": "none",
        "chip": "outline",
        "rule": "double",
        "rays": "sunburst",
        "particles": "star",
        "arch": "circle",
        "upper": true,
        "ls": 1.56,
        "motion": "snap",
        "spot": true
      },
      "sfx": {
        "pitch": 0.81,
        "bright": 1.55,
        "sub": 0.77
      },
      "bgm": {
        "genre": "strings",
        "mode": "minor",
        "tempo": 65,
        "root": 183.49,
        "rhythm": "ostinato",
        "brightness": 0.8,
        "seed": 10197
      }
    },
    "observatoryi": {
      "name": "Observatory I — Discovery",
      "bn": "Observatory I — discovery",
      "dark": true,
      "c": {
        "bg": [
          "#576b1c",
          "#293817",
          "#29280e"
        ],
        "ink": "#f7f4ed",
        "sub": "#66b259",
        "accent": "#5942eb",
        "accentL": "#d0f5a2",
        "accentD": "#4db878",
        "accent2": "#4db878",
        "onAccent": "#ffffff",
        "chip": "rgba(12,16,28,0.70)",
        "halo": "45,56,14",
        "glow": "89,65,234",
        "vig": "0,0,0",
        "palette": [
          "#5942eb",
          "#4db878",
          "#66b259",
          "#d0f5a2",
          "#d94cba",
          "#40b7c7"
        ]
      },
      "font": {
        "display": "Outfit",
        "body": "Outfit",
        "bn": "Anek Bangla",
        "dw": 800,
        "bw": 500,
        "gf": []
      },
      "style": {
        "pattern": "facets",
        "frame": "neon",
        "orn": "square",
        "chip": "glass",
        "rule": "none",
        "rays": "beam",
        "particles": "none",
        "arch": "rounded",
        "upper": false,
        "ls": 0.2,
        "motion": "drift",
        "spot": false
      },
      "sfx": {
        "pitch": 0.855,
        "bright": 0.45,
        "sub": 0.89
      },
      "bgm": {
        "genre": "guitar",
        "mode": "major",
        "tempo": 78,
        "root": 200.8,
        "rhythm": "drone",
        "brightness": 0.12,
        "seed": 10198
      }
    },
    "observatoryj": {
      "name": "Observatory J — Discovery",
      "bn": "Observatory J — discovery",
      "dark": false,
      "c": {
        "bg": [
          "#1e71d6",
          "#334ea3",
          "#113949"
        ],
        "ink": "#171923",
        "sub": "#6759b2",
        "accent": "#eb8a42",
        "accentL": "#a2b8f5",
        "accentD": "#974db8",
        "accent2": "#974db8",
        "onAccent": "#10131b",
        "chip": "rgba(255,255,255,0.78)",
        "halo": "22,85,163",
        "glow": "234,138,65",
        "vig": "70,45,20",
        "palette": [
          "#eb8a42",
          "#974db8",
          "#6759b2",
          "#a2b8f5",
          "#91d94c",
          "#c7408f"
        ]
      },
      "font": {
        "display": "Archivo Black",
        "body": "DM Sans",
        "bn": "Noto Sans Bengali",
        "dw": 700,
        "bw": 400,
        "gf": []
      },
      "style": {
        "pattern": "radial",
        "frame": "ticket",
        "orn": "star",
        "chip": "none",
        "rule": "dot",
        "rays": "orbit",
        "particles": "spark",
        "arch": "cut",
        "upper": true,
        "ls": 0.37,
        "motion": "orbit",
        "spot": true
      },
      "sfx": {
        "pitch": 0.9,
        "bright": 0.56,
        "sub": 1.01
      },
      "bgm": {
        "genre": "mallet",
        "mode": "mixolydian",
        "tempo": 91,
        "root": 218.11,
        "rhythm": "pulse",
        "brightness": 0.205,
        "seed": 10199
      }
    }
  },
  "ratios": {
    "9x16": {
      "w": 1080,
      "h": 1920,
      "label": "TikTok / Reels / Shorts / Stories"
    },
    "4x5": {
      "w": 1080,
      "h": 1350,
      "label": "Instagram + Facebook ফিড (পোর্ট্রেট)"
    },
    "3x4": {
      "w": 1080,
      "h": 1440,
      "label": "Instagram গ্রিড / Facebook"
    },
    "1x1": {
      "w": 1080,
      "h": 1080,
      "label": "স্কয়ার (সব প্ল্যাটফর্ম)"
    },
    "4x3": {
      "w": 1440,
      "h": 1080,
      "label": "ক্লাসিক ল্যান্ডস্কেপ"
    },
    "16x9": {
      "w": 1920,
      "h": 1080,
      "label": "YouTube / Facebook / ওয়েবসাইট"
    }
  },
  "resolutions": {
    "sd": 540,
    "hd": 720,
    "fhd": 1080,
    "qhd": 1440,
    "4k": 2160
  },
  "groups": {
    "portrait": [
      "9x16",
      "4x5",
      "3x4"
    ],
    "landscape": [
      "16x9",
      "4x3"
    ],
    "social": [
      "9x16",
      "4x5",
      "1x1",
      "16x9"
    ],
    "all": [
      "9x16",
      "4x5",
      "3x4",
      "1x1",
      "4x3",
      "16x9"
    ]
  }
}''',
    'site/index.html': r'''<!doctype html>
<html lang="bn">
<head>
<meta charset="utf-8">
<title>frame</title>
<!-- GitHub Actions-এ ইন্টারনেট আছে, তাই থিমের ফন্ট লোড হবে (render.py নিজে লিংক বসায়)। না পেলে সিস্টেম ফন্টে চলবে। -->
<!--FONTS-->
<link rel="stylesheet" href="style.css">
</head>
<body>
<div id="stage"></div>
<script src="base.js"></script>
<script src="decor.js"></script>
<script src="scenes.js"></script>
<script src="main.js"></script>
</body>
</html>
''',
    'site/style.css': r''':root {
  --ink: #2a1c10; --sub: #8a6224; --accent: #b98a3e; --accentL: #e6cc8f; --accentD: #8a6224; --accent2: #1f4d46;
  --onAccent: #2a1608; --chip: rgba(255,252,245,0.82); --halo: 255,250,238;
  --serif: "Cormorant Garamond", "Noto Serif", "FreeSerif", serif;
  --sans: "Jost", "Noto Sans", "FreeSans", sans-serif;
  --bn: "Noto Sans Bengali", "Hind Siliguri", "Lohit Bengali", "FreeSans", sans-serif;
  --dw: 700; --bw: 500;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { overflow: hidden; background: #111; }
#stage { position: relative; overflow: hidden; color: var(--ink); font-family: var(--sans); }
.layer { position: absolute; left: 0; top: 0; }
.abs { position: absolute; }
.center { left: 0; text-align: center; }
.serif { font-family: var(--serif); font-weight: var(--dw); }
.sans { font-family: var(--sans); font-weight: var(--bw); }
.bn { font-family: var(--bn); }
.upper { text-transform: uppercase; }
.nowrap { white-space: nowrap; }

/* হিরো (প্রোডাক্ট/টপিক ছবি) */
.hero { position: absolute; left: 0; top: 0; width: 1000px; height: 1000px; transform-origin: 50% 50%; will-change: transform; }
.hero img { width: 1000px; height: 1000px; display: block; object-fit: contain; }
.hero-blend, .hero-spot { mix-blend-mode: multiply;
  -webkit-mask-image: radial-gradient(circle closest-side, #000 84%, transparent 100%); mask-image: radial-gradient(circle closest-side, #000 84%, transparent 100%); }
.hero-cutout img { filter: drop-shadow(0 28px 34px rgba(0,0,0,0.28)); }
.hero-card img { border-radius: 38px; object-fit: cover; border: 10px solid var(--accent); box-shadow: 0 34px 70px rgba(0,0,0,0.38); }
.spot { position: absolute; left: 0; top: 0; width: 1000px; height: 1000px; transform-origin: 50% 50%; will-change: transform; }

/* চিপ — থিম অনুযায়ী ৬ ধরন */
.chip { position: absolute; display: flex; align-items: center; gap: 16px; padding: 14px 30px 14px 20px; white-space: nowrap;
  font-family: var(--sans); font-weight: 600; font-size: 38px; letter-spacing: 1px; color: var(--ink); border-radius: 60px;
  background: var(--chip); border: 2px solid var(--accent);
  box-shadow: 0 10px 28px rgba(0,0,0,0.16), inset 0 0 0 4px rgba(255,255,255,0.35); }
.chip .dot { width: 34px; height: 34px; border-radius: 50%; flex: none; box-shadow: inset 0 -4px 8px rgba(0,0,0,0.22), inset 0 3px 6px rgba(255,255,255,0.55), 0 0 0 3px rgba(255,255,255,0.8), 0 0 0 4.5px rgba(185,138,62,0.55); }
body[data-chip="glass"] .chip { border-radius: 22px; border: 1.5px solid var(--accentL); background: var(--chip); box-shadow: 0 12px 30px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.35); }
body[data-chip="outline"] .chip { border-radius: 16px; background: rgba(0,0,0,0.18); border: 2.5px solid var(--accent); box-shadow: 0 0 18px -2px var(--accent), inset 0 0 14px -6px var(--accent); }
body[data-chip="block"] .chip { border-radius: 10px; background: var(--accent); color: var(--onAccent); border: 3px solid var(--ink); box-shadow: 8px 8px 0 var(--ink); }
body[data-chip="tag"] .chip { border-radius: 6px; background: var(--chip); border: 0; border-left: 12px solid var(--accent); box-shadow: 0 10px 24px rgba(0,0,0,0.16); padding-left: 24px; }
body[data-chip="block"] .chip .dot { box-shadow: 0 0 0 3px var(--ink); }

/* কার্ড (তুলনা সিন) ও ধাপের সংখ্যা */
.card { position: absolute; border-radius: 28px; background: var(--chip); border: 3px solid var(--accent); box-shadow: 0 18px 44px rgba(0,0,0,0.2); overflow: hidden; }
body[data-chip="block"] .card { border-radius: 10px; box-shadow: 10px 10px 0 var(--ink); border-color: var(--ink) !important; }
body[data-chip="tag"] .card { border-radius: 8px; }
body[data-chip="outline"] .card { background: rgba(0,0,0,0.22); box-shadow: 0 0 26px -4px var(--accent); }
.stepnum { border-radius: 50%; display: flex; align-items: center; justify-content: center; font-family: var(--serif); font-weight: var(--dw);
  background: var(--accent); color: var(--onAccent); box-shadow: 0 8px 20px rgba(0,0,0,0.25), 0 0 0 6px rgba(255,255,255,0.18); }
body[data-chip="block"] .stepnum, body[data-chip="tag"] .stepnum { border-radius: 14px; }
.vsbadge { border-radius: 50%; display: flex; align-items: center; justify-content: center; font-family: var(--serif); font-weight: var(--dw);
  background: var(--ink); color: var(--bg0, #fff); border: 4px solid var(--accent); box-shadow: 0 10px 26px rgba(0,0,0,0.3); z-index: 3; }
body[data-dark="1"] .vsbadge { background: var(--accent); color: var(--onAccent); border-color: var(--ink); }
body[data-dark="0"] .vsbadge { color: #fff; }

/* ক্যাপশন */
.cap { position: absolute; display: flex; align-items: center; justify-content: center; text-align: center;
  font-family: var(--bn); font-weight: 700; line-height: 1.5; color: var(--ink);
  text-shadow: 0 2px 0 rgba(var(--halo), 0.85), 0 0 18px rgba(var(--halo), 0.95), 0 0 34px rgba(var(--halo), 0.9); }
body[data-dark="1"] .cap { text-shadow: 0 2px 10px rgba(var(--halo), 0.9), 0 0 26px rgba(var(--halo), 0.9), 0 0 44px rgba(var(--halo), 0.8); }
''',
    'site/base.js': r'''/* মোশন গ্রাফিক্স স্টেজ (ভাগ ১): সহায়ক ফাংশন, থিম, লেআউট, হিরো ইমেজ।
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
    intro: [0.73, 0.47, 1.0], title: [0.27, 0.46, 1.0], blend: [0.74, 0.46, 1.0], traits: [0.5, 0.52, 0.95], notes: [0.5, 0.52, 0.95], family: [0.72, 0.46, 0.72],
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
''',
    'site/decor.js': r'''/* মোশন গ্রাফিক্স স্টেজ (ভাগ ২): থিমের সাজসজ্জা — ব্যাকগ্রাউন্ড প্যাটার্ন, ফ্রেম, কণা, ব্র্যান্ড বার। */
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
''',
    'site/scenes.js': r'''/* মোশন গ্রাফিক্স স্টেজ (ভাগ ৩): সিন তৈরির ফাংশন।
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
''',
    'site/main.js': r'''/* মোশন গ্রাফিক্স স্টেজ (ভাগ ৪): হিরো নড়াচড়া, ক্যাপশন, মূল ফ্রেম, প্রস্তুতি। */
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
''',
}


def _extract_engine():
    """ভেতরের ফাইলগুলো (ডিজাইন, থিম, সাউন্ড, সিঙ্ক কোড) build/_engine-এ নামায়।"""
    d = _os.path.join(_os.getcwd(), "build", "_engine")
    for name, text in _ASSETS.items():
        p = _os.path.join(d, name)
        _os.makedirs(_os.path.dirname(p), exist_ok=True)
        if not _os.path.exists(p) or open(p, encoding="utf-8").read() != text:
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
    return d

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

HERE = _extract_engine()
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
