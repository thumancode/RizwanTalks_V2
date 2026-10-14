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
    "synthwave"
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
      capH: Math.min(190, Math.max(104, H * 0.145)),
      capTop: H - Math.min(190, Math.max(104, H * 0.145)) - Math.max(140, H * 0.18),
      capFont: Math.min(lk(46, 54), H * 0.042),
      capW: Math.min(W * 0.84, 1640), brandY: H - Math.max(100, H * 0.14),
      compact: true,
    });
  }
  G.textW = Math.min(W - 120, WIDE ? 1500 : 960);   // লেখার সর্বোচ্চ প্রস্থ
  G.cx = W / 2;
  G.yv = (sq, tall) => lk(sq, tall);

  // ---------- হিরো (প্রোডাক্ট / টপিক ছবি) অবস্থা, সিন অনুযায়ী ----------
  // fx, fy = ক্যানভাসের অনুপাত; s = আকার (hero unit দিয়ে গুণ হবে)
  const HS = {
    intro: [0.5, 0.443, 1.0], title: [0.5, 0.547, 0.78], blend: [0.5, 0.471, 0.72], traits: [0.5, 0.471, 0.86], notes: [0.5, 0.471, 0.86],
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
