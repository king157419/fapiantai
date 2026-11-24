"""第 4 步：合成 1080×1920 竖屏视频（纸色底 + 作品截图卡片缓慢下移 + 逐句字幕 + 配音），外加封面和 SRT。

画面层次（每一段）：纸色底 → 截图（淡入、从上往下慢慢移）→ 带圆角镂空的前景（标题、阴影、页脚）→ 字幕。
字幕用 PIL 画成透明 PNG 叠上去，不依赖 libass 字体配置。
"""
import json
import random
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
PAPER = (244, 238, 226)
INK = (58, 49, 40)
INK_SOFT = (128, 112, 94)
ACCENT = (214, 140, 52)
CARD_X, CARD_Y, CARD_W, CARD_H, RADIUS = 160, 372, 760, 1170, 34
SUB_Y = 1590


def geom(tour):
    """卡片位置。手机网页用竖卡片（截图慢慢往下移）；桌面软件用横卡片（截图慢慢平移推近），字幕紧贴卡片下方。"""
    if tour.get("card") == "landscape":
        vw, vh = tour.get("viewport", [1480, 920])
        cw = 1000
        ch = round(cw * vh / vw)
        # 卡片 + 字幕这一组在标题（到 y≈340）和页脚（y≈1820）之间上下居中
        y = 340 + (1480 - (ch + 40 + 230)) // 2
        return {"x": 40, "y": y, "w": cw, "h": ch, "r": 26, "sub_y": y + ch + 40, "mode": "landscape"}
    return {"x": CARD_X, "y": CARD_Y, "w": CARD_W, "h": CARD_H, "r": RADIUS, "sub_y": SUB_Y, "mode": "portrait"}
FPS = 30
LEAD, GAP, TAIL = 0.30, 0.20, 0.45

FONT_DIR = Path("C:/Windows/Fonts")
F_TITLE = str(FONT_DIR / "NotoSerifSC-VF.ttf")
F_SUB = str(FONT_DIR / "msyhbd.ttc")
F_BODY = str(FONT_DIR / "msyh.ttc")


def font(path, size, weight=None):
    f = ImageFont.truetype(path, size)
    if weight and path.endswith("VF.ttf"):
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def paper(size=(W, H), seed=7):
    """纸色底 + 很淡的颗粒和暖色晕染。"""
    rnd = random.Random(seed)
    im = Image.new("RGB", size, PAPER)
    noise = Image.effect_noise(size, 18).convert("L")
    im = Image.composite(im, Image.new("RGB", size, (232, 224, 208)), noise.point(lambda v: 255 - v // 9))
    glow = Image.new("L", size, 0)
    d = ImageDraw.Draw(glow)
    for _ in range(3):
        x, y, r = rnd.randint(0, size[0]), rnd.randint(0, size[1]), rnd.randint(380, 700)
        d.ellipse((x - r, y - r, x + r, y + r), fill=40)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(Image.new("RGB", size, (250, 231, 200)), im, glow)


def wrap(text, f, max_w, draw):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=f) > max_w and cur:
            # 不让标点落在行首
            if ch in "，。！？、：；」』）":
                cur += ch
                continue
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def make_frame(tour, script, path):
    """前景：纸底 + 标题 + 卡片阴影 + 页脚，卡片位置镂空（alpha=0）。"""
    g = geom(tour)
    CARD_X, CARD_Y, CARD_W, CARD_H, RADIUS = g["x"], g["y"], g["w"], g["h"], g["r"]
    base = paper().convert("RGBA")
    d = ImageDraw.Draw(base)
    # 标题区
    d.text((W // 2, 150), tour["name"], font=font(F_TITLE, 92, 700), fill=INK, anchor="mm")
    hook = script.get("hook", "")
    d.text((W // 2, 262), hook, font=font(F_BODY, 40), fill=INK_SOFT, anchor="mm")
    d.rounded_rectangle((W // 2 - 34, 318, W // 2 + 34, 324), radius=3, fill=ACCENT)
    # 卡片阴影
    sh = Image.new("L", (W, H), 0)
    ImageDraw.Draw(sh).rounded_rectangle((CARD_X + 6, CARD_Y + 18, CARD_X + CARD_W + 6, CARD_Y + CARD_H + 22),
                                         radius=RADIUS, fill=90)
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    base = Image.composite(Image.new("RGBA", (W, H), (120, 96, 70, 255)), base, sh)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle((CARD_X - 3, CARD_Y - 3, CARD_X + CARD_W + 3, CARD_Y + CARD_H + 3),
                        radius=RADIUS + 3, outline=(255, 252, 245), width=6)
    # 页脚
    d.text((W // 2, 1858), tour.get("footer", "我做的小网页 · 链接在评论区"), font=font(F_BODY, 30), fill=INK_SOFT, anchor="mm")
    # 镂空
    hole = Image.new("L", (W, H), 255)
    ImageDraw.Draw(hole).rounded_rectangle((CARD_X, CARD_Y, CARD_X + CARD_W, CARD_Y + CARD_H), radius=RADIUS, fill=0)
    base.putalpha(hole)
    base.save(path)


def make_sub(text, path):
    im = Image.new("RGBA", (W, 230), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(F_SUB, 54)
    lines = wrap(text, f, 900, d)[:3]
    lh = 76
    y0 = (230 - lh * len(lines)) // 2 + lh // 2
    for i, ln in enumerate(lines):
        d.text((W // 2, y0 + i * lh), ln, font=f, fill=INK, anchor="mm",
               stroke_width=6, stroke_fill=(251, 247, 238))
    im.save(path)


def concat_wavs(files, gaps, dst):
    """按 [前导静音, 句1, 间隔, 句2, ..., 尾部静音] 拼 wav；返回每句的 (开始, 结束)。"""
    rate = 24000
    frames, spans, t = [], [], 0.0

    def silence(sec):
        return b"\x00\x00" * int(rate * sec)

    frames.append(silence(gaps[0])); t += gaps[0]
    for i, f in enumerate(files):
        with wave.open(f, "rb") as w:
            data = w.readframes(w.getnframes())
            dur = w.getnframes() / w.getframerate()
        frames.append(data)
        spans.append((t, t + dur)); t += dur
        g = gaps[1] if i < len(files) - 1 else gaps[2]
        frames.append(silence(g)); t += g
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(frames))
    return spans, t


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def compose(tour, script, plan, out_dir):
    out_dir = Path(out_dir)
    work = out_dir / "build"
    work.mkdir(exist_ok=True)
    shots_dir = out_dir / "shots"
    frame = work / "frame.png"
    make_frame(tour, script, frame)
    g = geom(tour)
    CARD_X, CARD_Y, CARD_W, CARD_H, SUB_Y = g["x"], g["y"], g["w"], g["h"], g["sub_y"]
    seg_files, srt, clock = [], [], 0.0
    for si, seg in enumerate(plan):
        wav = work / f"seg{si:02d}.wav"
        spans, dur = concat_wavs([l["file"] for l in seg["lines"]], (LEAD, GAP, TAIL), wav)
        shot = Image.open(shots_dir / f"{seg['shot']}.png")
        sh = round(shot.height * CARD_W / shot.width)
        travel = max(0, sh - CARD_H)
        # 截图位置：先停 0.8 秒，再用 smoothstep 往下移到底，最后停 0.6 秒
        a, b = 0.8, max(1.2, dur - 0.6)
        p = f"clip((t-{a})/{b - a},0,1)"
        y_expr = f"{CARD_Y}-{travel}*({p})*({p})*(3-2*({p}))" if travel else str(CARD_Y)
        x_expr, scale = str(CARD_X), f"{CARD_W}:-1"
        if g["mode"] == "landscape":
            # 横图：放大到比卡片大 7%，整段时间里从左上慢慢移到右下，像镜头轻轻推过去；方向按段交替
            k = max(CARD_W / shot.width, CARD_H / shot.height) * 1.07
            sw, shh = round(shot.width * k / 2) * 2, round(shot.height * k / 2) * 2
            ex, ey = sw - CARD_W, shh - CARD_H
            q = f"clip(t/{dur:.3f},0,1)"
            sm = f"({q})*({q})*(3-2*({q}))"
            if si % 2:
                x_expr, y_expr = f"{CARD_X}-{ex}+{ex}*{sm}", f"{CARD_Y}-{ey}*{sm}"
            else:
                x_expr, y_expr = f"{CARD_X}-{ex}*{sm}", f"{CARD_Y}-{ey}+{ey}*{sm}"
            scale = f"{sw}:{shh}"
        inputs = ["-f", "lavfi", "-i", f"color=c=0x{PAPER[0]:02x}{PAPER[1]:02x}{PAPER[2]:02x}:s={W}x{H}:r={FPS}:d={dur:.3f}",
                  "-loop", "1", "-t", f"{dur:.3f}", "-i", str(shots_dir / f"{seg['shot']}.png"),
                  "-loop", "1", "-t", f"{dur:.3f}", "-i", str(frame)]
        fc = [f"[1:v]scale={scale}:flags=lanczos,format=rgba,fade=t=in:st=0:d=0.35:alpha=1[s]",
              f"[0:v][s]overlay=x='{x_expr}':y='{y_expr}':eval=frame[v1]",
              "[v1][2:v]overlay=0:0[v2]"]
        last = "v2"
        for li, (line, (st, en)) in enumerate(zip(seg["lines"], spans)):
            sub = work / f"sub{si:02d}_{li:02d}.png"
            make_sub(line["text"], sub)
            inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(sub)]
            idx = 3 + li
            end = en + (GAP if li < len(spans) - 1 else TAIL) - 0.02
            fc.append(f"[{last}][{idx}:v]overlay=0:{SUB_Y}:enable='between(t,{st:.3f},{end:.3f})'[w{li}]")
            last = f"w{li}"
            srt.append((clock + st, clock + en, line["text"]))
        inputs += ["-i", str(wav)]
        aidx = 3 + len(seg["lines"])
        mp4 = work / f"seg{si:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
                        "-map", f"[{last}]", "-map", f"{aidx}:a", "-af", "alimiter=limit=0.89:level=disabled", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
                        "-crf", "19", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                        "-t", f"{dur:.3f}", str(mp4)], check=True)
        seg_files.append(mp4)
        clock += dur
        print(f"  段 {si + 1}/{len(plan)}  {seg['shot']:<16} {dur:5.1f}s")
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{f.as_posix()}'\n" for f in seg_files), encoding="utf-8")
    final = out_dir / "video.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    (out_dir / "video.srt").write_text(
        "".join(f"{i + 1}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(srt)), encoding="utf-8")
    print(f"  成片 {final}  共 {clock:.1f} 秒")
    return final


def make_covers(tour, script, out_dir, art=None):
    """封面两张：9:16（抖音/B站竖屏）和 3:4（小红书）。有作品插画就用插画。"""
    out_dir = Path(out_dir)
    outs = {}
    for name, (cw, ch) in {"cover_9x16.jpg": (1080, 1920), "cover_3x4.jpg": (1080, 1440)}.items():
        im = paper((cw, ch), seed=3).convert("RGB")
        d = ImageDraw.Draw(im)
        if art and Path(art).exists():
            a = Image.open(art).convert("RGB")
            box_w = int(cw * 0.72)
            box_h = int(ch * (0.56 if ch > 1500 else 0.52))
            if tour.get("cover_fit") == "contain":
                # 整张图放进框里不裁，空出来的地方用图角上的底色补（适合纯色底的拼图）
                k = min(box_w / a.width, box_h / a.height) * 0.94
                a = a.resize((round(a.width * k), round(a.height * k)), Image.LANCZOS)
                bg = Image.new("RGB", (box_w, box_h), a.getpixel((2, 2)))
                bg.paste(a, ((box_w - a.width) // 2, (box_h - a.height) // 2))
                a = bg
            else:
                # 铺满框再居中裁：竖插画裁上下，横截图（桌面软件）裁左右，不留黑边
                k = max(box_w / a.width, box_h / a.height)
                a = a.resize((round(a.width * k), round(a.height * k)), Image.LANCZOS)
                l, t = (a.width - box_w) // 2, (a.height - box_h) // 2
                a = a.crop((l, t, l + box_w, t + box_h))
            mask = Image.new("L", a.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, *a.size), radius=36, fill=255)
            ax, ay = (cw - box_w) // 2, int(ch * 0.07)
            sh = Image.new("L", (cw, ch), 0)
            ImageDraw.Draw(sh).rounded_rectangle((ax + 6, ay + 18, ax + box_w + 6, ay + box_h + 22), radius=36, fill=80)
            im = Image.composite(Image.new("RGB", (cw, ch), (120, 96, 70)), im, sh.filter(ImageFilter.GaussianBlur(22)))
            im.paste(a, (ax, ay), mask)
            d = ImageDraw.Draw(im)
            ty = ay + box_h + int(ch * 0.085)
        else:
            ty = int(ch * 0.4)
        d.text((cw // 2, ty), tour["name"], font=font(F_TITLE, 120 if ch > 1500 else 104, 700), fill=INK, anchor="mm")
        title = script["xiaohongshu"]["title"] if ch < 1500 else script.get("hook", "")
        lines = wrap(title, font(F_SUB, 58), cw - 160, d)
        if len(lines) > 1 and "，" in title:
            # 两行时优先在逗号处断开，避免最后一行只剩两三个字
            head, tail = title.split("，", 1)
            if all(len(wrap(x, font(F_SUB, 58), cw - 160, d)) == 1 for x in (head + "，", tail)):
                lines = [head + "，", tail]
        for i, ln in enumerate(lines[:2]):
            d.text((cw // 2, ty + 120 + i * 80), ln, font=font(F_SUB, 58), fill=ACCENT, anchor="mm",
                   stroke_width=2, stroke_fill=(251, 247, 238))
        p = out_dir / name
        im.save(p, quality=92)
        outs[name] = p
    return outs
