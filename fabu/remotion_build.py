"""第 4 步（Remotion 版）：把真实录屏 + 配音 + 字幕交给 Remotion 渲染成竖屏视频。

Python 这边只排时间轴，算出这几样交给 Remotion：
  - 配音整轨：句间停顿按标点和语气定（问号、感叹号停得长一点，带一点随机），不再一刀切
  - 每段用录屏的哪一截：从「为这个镜头做的第一个动作」开始播；配音比录屏长就停在最后一帧
  - 镜头：点击前推近到点击位置、点完停一会再拉远；tour 里写了 clip 的镜头推到那块区域
  - 鼠标轨迹、点击波纹、按键提示的时间（输出视频的秒数）
Remotion（remotion/src）负责画：亚像素平移不抖、缓动曲线、字幕弹入。
"""
import json
import random
import shutil
import subprocess
import wave
from pathlib import Path

from fabu.compose import geom, paper

ROOT = Path(__file__).resolve().parent.parent
RDIR = ROOT / "remotion"
FPS = 30
LEAD, SEG_TAIL, END_TAIL = 0.25, 0.42, 0.9
CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"


def pause_after(text, rnd):
    base = 0.36 if text.endswith(("？", "！", "?", "!")) else 0.27
    return base + rnd.uniform(-0.04, 0.05)


def build_narration(plan, dst, seed=11):
    """拼整轨配音；返回每段 (开始, 结束) 和每句 (开始, 结束)，单位秒。"""
    rnd = random.Random(seed)
    rate = 24000
    out, t = [], 0.0
    segs = []

    def sil(sec):
        out.append(b"\x00\x00" * int(rate * sec))
        return sec

    for si, seg in enumerate(plan):
        s0 = t
        t += sil(LEAD if si else 0.45)
        lines = []
        for li, ln in enumerate(seg["lines"]):
            with wave.open(ln["file"], "rb") as w:
                data = w.readframes(w.getnframes())
                dur = w.getnframes() / w.getframerate()
            out.append(data)
            lines.append({"text": ln["text"], "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur
            if li < len(seg["lines"]) - 1:
                t += sil(pause_after(ln["text"], rnd))
        t += sil(END_TAIL if si == len(plan) - 1 else SEG_TAIL)
        segs.append({"shot": seg["shot"], "start": round(s0, 3), "end": round(t, 3), "lines": lines})
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(out))
    return segs, t


def _w(ch):
    return 0.55 if ord(ch) < 128 else 1.0


def wrap_sub(text, max_units=16.5):
    """字幕断行：两行尽量一样长，优先断在逗号顿号后面，不拆开英文和数字。"""
    units = sum(_w(c) for c in text)
    if units <= max_units:
        return text
    n_lines = 2 if units <= max_units * 2 else 3
    best, best_cost, acc = None, 1e9, 0.0
    for i in range(1, len(text)):
        acc += _w(text[i - 1])
        a, b = text[i - 1], text[i]
        if a.isascii() and b.isascii() and (a.isalnum() or a in "./") and (b.isalnum() or b in "./"):
            continue
        if b in "，。！？、：；）」":
            continue
        target = units / n_lines
        cost = abs(acc - target) + (0 if a in "，、：；" else 6)
        if acc > max_units + 0.5 or (n_lines == 2 and units - acc > max_units + 0.5):
            cost += 50
        if cost < best_cost:
            best, best_cost = i, cost
    if best is None:
        return text
    head, tail = text[:best].strip(), text[best:].strip()
    return head + "\n" + wrap_sub(tail, max_units)


def add_click_sfx(wav_path, times, seed=5):
    """在点击时刻混进一声很轻的「咔哒」（合成的短噪声 + 高频衰减音，约 -22 dB）。"""
    import math
    import struct
    rnd = random.Random(seed)
    with wave.open(str(wav_path), "rb") as w:
        rate, n = w.getframerate(), w.getnframes()
        data = list(struct.unpack(f"<{n}h", w.readframes(n)))
    L = int(rate * 0.035)
    click = [(rnd.uniform(-1, 1) * 0.6 + math.sin(2 * math.pi * 2600 * i / rate) * 0.5) * math.exp(-i / (rate * 0.006))
             for i in range(L)]
    amp = 32767 * 0.08
    for t in times:
        st = int(t * rate)
        for i, v in enumerate(click):
            j = st + i
            if 0 <= j < n:
                data[j] = max(-32768, min(32767, data[j] + int(v * amp)))
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f"<{n}h", *data))


def shot_windows(events, rec_dur):
    """每个镜头：录屏里从哪开始播（第一个动作）、最多播到哪（下一个镜头的第一个动作）。"""
    shots = [e for e in events if e["type"] == "shot"]
    acts = [e for e in events if e["type"] in ("move", "click", "key")]
    win = {}
    prev_t = -1
    starts = []
    for s in shots:
        first = [a["t"] for a in acts if prev_t < a["t"] <= s["t"]]
        starts.append(max(0.0, (min(first) - 0.25) if first else s["t"] - 0.15))
        prev_t = s["t"]
    for i, s in enumerate(shots):
        if i + 1 < len(shots):
            limit = starts[i + 1]
        else:  # 最后一个镜头之后的收尾动作（比如取消勾选）不拍进去
            tail = [a["t"] for a in acts if a["t"] > s["t"]]
            limit = (min(tail) - 0.1) if tail else rec_dur
        last_act = max([a["t"] for a in acts if starts[i] <= a["t"] <= s["t"]], default=s["t"])
        win[s["name"]] = {"rec_start": round(starts[i], 3), "rec_limit": round(max(limit, starts[i] + 0.5), 3),
                          "clip": s.get("clip"), "need": round(max(last_act, s["t"]) + 0.9 - starts[i], 3)}
    return win


def build_props(tour, script, plan, out_dir):
    out_dir = Path(out_dir)
    rec = json.loads((out_dir / "rec" / "events.json").read_text(encoding="utf-8"))
    vw, vh = rec["viewport"]
    # 卡片比录屏更高：镜头始终裁掉左右一部分、跟着操作走，字在手机上更大（竖屏短视频常见做法）
    if vh > vw * 1.3:
        # 手机网页：卡片做成整块手机屏（宽高比和录屏一样），平时能看到整屏，点击时才推近
        card_h = tour.get("card_h", 1190)
        card_w = round(card_h * vw / vh)
        y0 = 340 + (1480 - (card_h + 40 + 230)) // 2
        g = {"x": (1080 - card_w) // 2, "y": y0, "w": card_w, "h": card_h, "r": 36, "sub_y": y0 + card_h + 40,
             "mode": "phone"}
    else:
        card_h = tour.get("card_h", 820)
        y0 = 340 + (1480 - (card_h + 40 + 230)) // 2
        g = {"x": 40, "y": y0, "w": 1000, "h": card_h, "r": 28, "sub_y": y0 + card_h + 40, "mode": "follow"}
    k = g["w"] / vw
    s0 = max(1.0, card_h / (vh * k))  # 填满卡片高度所需的最小放大
    slug = out_dir.name
    pub = RDIR / "public" / slug
    pub.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out_dir / "rec" / "rec.mp4", pub / "rec.mp4")
    paper().save(pub / "paper.png")
    segs, total = build_narration(plan, pub / "narration.wav")
    shutil.copy2(pub / "narration.wav", out_dir / "build_narration.wav")
    (out_dir / "build_narration.json").write_text(json.dumps([[sg["start"], sg["end"]] for sg in segs]), encoding="utf-8")
    win = shot_windows(rec["events"], rec["duration"])

    cam, cursor, clicks, keys = [], [], [], []
    full = {"s": round(s0, 4), "x": vw / 2, "y": vh / 2}

    def clampc(s, x, y):
        s = max(s, s0)
        hw, hh = vw / (2 * s), card_h / (2 * k * s)
        return {"s": round(s, 4), "x": round(min(max(x, hw), vw - hw), 2), "y": round(min(max(y, hh), vh - hh), 2)}

    def key(t, c):
        cam.append({**c, "t": round(t, 3)})

    key(0, full)
    for seg in segs:
        w = win[seg["shot"]]
        a, b = seg["start"], seg["end"]
        seg["rec_start"], seg["rec_limit"] = w["rec_start"], w["rec_limit"]
        # 配音比这段操作短：录屏加速播放，保证动作都拍进去（最多 1.6 倍，再快就不自然了）
        rate = round(min(1.6, max(1.0, w["need"] / max(0.5, b - a))), 3)
        seg["rate"] = rate

        def to_out(rt, rate=rate):
            return a + (rt - w["rec_start"]) / rate

        evs = [e for e in rec["events"] if w["rec_start"] <= e["t"] < w["rec_limit"] and to_out(e["t"]) < b]
        if w["clip"]:
            x, y, cw, ch = w["clip"]
            s = min(g["w"] / (k * cw), card_h / (k * ch)) * 0.96
            key(a + 0.35, cam[-1] if cam[-1]["t"] <= a + 0.35 else full)
            key(a + 1.35, clampc(s, x + cw / 2, y + ch / 2))
            key(b - 0.55, clampc(s, x + cw / 2, y + ch / 2))
            key(b + 0.15, full)
            last = full
        else:
            zoomed_until = -1
            last = full
            for e in evs:
                to = to_out(e["t"])
                if e["type"] == "click":
                    target = clampc(s0 * 1.45, e["x"], e["y"])
                    last = clampc(s0, e["x"], e["y"])
                    if to - 0.85 > zoomed_until + 0.1:
                        key(to - 0.85, cam[-1] if cam and cam[-1]["t"] <= to - 0.85 else full)
                    key(to - 0.05, target)
                    hold = min(to + 1.5, b - 0.2)
                    key(hold, target)
                    zoomed_until = hold
                    clicks.append(round(to, 3))
                if e["type"] == "move":
                    cursor.append({"t": round(to, 3), "x": round(e["x"], 1), "y": round(e["y"], 1)})
                if e["type"] == "click":
                    cursor.append({"t": round(to, 3), "x": round(e["x"], 1), "y": round(e["y"], 1)})
                if e["type"] == "key":
                    label = {"ArrowRight": "→", "ArrowLeft": "←", "Escape": "Esc"}.get(e["key"], e["key"])
                    keys.append({"t": round(to, 3), "label": label})
            if zoomed_until > 0:
                key(min(zoomed_until + 0.75, b + 0.1), last)
                if b - (zoomed_until + 0.75) > 2.5:  # 停得久就慢慢回到全局
                    key(b + 0.2, full)
    cam.sort(key=lambda c: c["t"])
    # 去掉时间倒退/重复的关键帧
    clean = []
    for c in cam:
        if clean and c["t"] <= clean[-1]["t"]:
            clean[-1] = c
        else:
            clean.append(c)
    add_click_sfx(pub / "narration.wav", clicks)
    # 每段能播多少帧录屏；播完还没到段尾就停在最后一帧（提前抽成图片，Remotion 里用 <Img>）
    for i, seg in enumerate(segs):
        dur_f = int(round((seg["end"] - seg["start"]) * FPS))
        play_f = int(min(dur_f, (seg["rec_limit"] - seg["rec_start"]) / seg["rate"] * FPS))
        seg["playFrames"] = max(1, play_f)
        end_t = seg["rec_start"] + (seg["playFrames"] - 1) / FPS * seg["rate"]
        img = pub / f"end{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{end_t:.3f}", "-i", str(pub / "rec.mp4"),
                        "-frames:v", "1", "-q:v", "2", str(img)], check=True)
        seg["endImg"] = img.name
    for seg in segs:
        for ln in seg["lines"]:
            ln["display"] = wrap_sub(ln["text"])
    if not cursor:
        cursor = [{"t": 0, "x": vw * 0.62, "y": vh * 0.55}]
    props = {
        "slug": slug, "fps": FPS, "durationInFrames": int(round(total * FPS)) + 1,
        "title": tour["name"], "hook": script.get("hook", ""), "footer": tour.get("footer", "我做的小网页 · 链接在评论区"),
        "viewport": [vw, vh], "card": g, "segments": segs, "camera": clean, "cursor": cursor, "clicks": clicks, "keys": keys,
    }
    (pub / "props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    srt = []
    for seg in segs:
        for ln in seg["lines"]:
            srt.append((ln["start"], ln["end"], ln["text"]))
    return props, pub / "props.json", srt


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def loudnorm(video):
    """响度统一到 -16 LUFS（短视频平台常用），画面不重编码。"""
    tmp = Path(video).with_suffix(".ln.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "copy",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(video)


def render(tour, script, plan, out_dir):
    out_dir = Path(out_dir)
    props, props_file, srt = build_props(tour, script, plan, out_dir)
    final = (out_dir / "video.mp4").resolve()
    cmd = ["npx", "remotion", "render", "src/index.jsx", "Explainer", str(final), f"--props={props_file}",
           "--codec=h264", "--crf=18", "--concurrency=75%", "--log=warn"]
    if Path(CHROME).exists():
        cmd.append(f"--browser-executable={CHROME}")
    subprocess.run(cmd, cwd=RDIR, check=True, shell=True)
    loudnorm(final)
    (out_dir / "video.srt").write_text(
        "".join(f"{i + 1}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(srt)), encoding="utf-8")
    print(f"  成片（Remotion）{final}  共 {props['durationInFrames'] / FPS:.1f} 秒")
    return final
