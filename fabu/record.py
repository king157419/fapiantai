"""第 1 步（录屏版）：按 tour 真实操作一遍，用 Chrome 的录屏接口（CDP Page.startScreencast）录下整个过程，
同时记下每次鼠标移动、点击、按键的时间和坐标，给 Remotion 画鼠标轨迹和「点哪放大哪」用。

输出 out/<作品>/rec/
  rec.mp4      录屏，恒定 30fps（原始帧只在画面变化时才来，这里按时间戳补齐）
  events.json  {"viewport": [w, h], "events": [{t, type: move|click|key|shot, x, y, key, name, desc, clip}]}
  shots/       每个 shot 节点的高清截图（写稿时给模型看画面文字用）
"""
import asyncio
import base64
import json
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import async_playwright

from fabu.capture import _resolve_url

MOVE_SEC = 0.75     # 鼠标从上一个位置滑到目标用多久（录屏里这段时间画面不动，鼠标由 Remotion 画）
IDLE_AFTER_SHOT = 7.0  # 每个镜头点完之后停多久，留出配音的时间（播放器这类画面会继续动）


def record(tour_path, out_dir):
    return asyncio.run(_record(tour_path, out_dir))


async def _launch(pw):
    for ch in ("chrome", "msedge", None):
        try:
            return await (pw.chromium.launch(channel=ch) if ch else pw.chromium.launch())
        except Exception:
            continue
    raise RuntimeError("找不到可用的浏览器")


async def _record(tour_path, out_dir):
    tour = json.loads(Path(tour_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    rec = out_dir / "rec"
    if rec.exists():
        shutil.rmtree(rec)
    frames_dir = rec / "frames"
    frames_dir.mkdir(parents=True)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    w, h = tour.get("viewport", [390, 844])
    dsf = tour.get("scale", 2)
    mobile = w < 600
    never = tour.get("never_click", [])
    frames, events, meta = [], [], []
    cursor = [w * 0.62, h * 0.55]

    async with async_playwright() as pw:
        browser = await _launch(pw)
        page = await browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=dsf,
                                is_mobile=mobile, has_touch=mobile, locale="zh-CN")
        await page.goto(_resolve_url(tour, tour_path), wait_until="networkidle")
        await page.wait_for_timeout(tour.get("boot_wait", 800))
        cdp = await page.context.new_cdp_session(page)

        async def _ack(sid):
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": sid})
            except Exception:  # 浏览器关掉后还没发出去的确认，忽略
                pass

        def on_frame(p):
            f = frames_dir / f"{len(frames):05d}.jpg"
            f.write_bytes(base64.b64decode(p["data"]))
            # 用收到这一帧时的系统时间，和点击事件用同一个时钟（Chrome 自带的时间戳跟系统时钟差约 1 秒）
            frames.append((time.time(), f.name))
            asyncio.ensure_future(_ack(p["sessionId"]))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92,
                                          "maxWidth": int(w * dsf), "maxHeight": int(h * dsf), "everyNthFrame": 1})
        await page.wait_for_timeout(1200)
        t0 = time.time()

        def now():
            return round(time.time() - t0, 3)

        for step in tour["steps"]:
            try:
                if "click" in step:
                    if any(n in step["click"] for n in never):
                        print(f"  ! 拒绝点击（在 never_click 里）：{step['click']}")
                        continue
                    loc = page.locator(step["click"]).first
                    box = await loc.bounding_box(timeout=4000)
                    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    events.append({"t": now(), "type": "move", "x": cursor[0], "y": cursor[1]})
                    await page.wait_for_timeout(int(MOVE_SEC * 1000))
                    events.append({"t": now(), "type": "click", "x": x, "y": y})
                    await loc.click(timeout=4000)
                    cursor = [x, y]
                elif "key" in step:
                    if step["key"] in tour.get("never_key", []):
                        print(f"  ! 拒绝按键（在 never_key 里）：{step['key']}")
                        continue
                    events.append({"t": now(), "type": "key", "key": step["key"], "x": cursor[0], "y": cursor[1]})
                    await page.keyboard.press(step["key"])
                elif "scroll" in step:
                    # 平滑滚动：写选择器 = 把那个元素滚到画面中间（弹层里的滚动也行）；写数字 = 整页往下滚这么多像素
                    events.append({"t": now(), "type": "move", "x": cursor[0], "y": cursor[1]})
                    if isinstance(step["scroll"], str):
                        await page.locator(step["scroll"]).first.evaluate(
                            "(e, b) => e.scrollIntoView({behavior: 'smooth', block: b})", step.get("block", "center"))
                    else:
                        await page.evaluate("(d) => window.scrollBy({top: d, behavior: 'smooth'})", step["scroll"])
                    await page.wait_for_timeout(step.get("ms", 1100))
                elif "type" in step:
                    await page.locator(step["type"]).first.fill(step["text"], timeout=4000)
                elif "wait" in step:
                    await page.wait_for_timeout(step["wait"])
                elif "shot" in step:
                    f = shots_dir / f"{step['shot']}.png"
                    if step.get("clip"):
                        x, y, cw, ch = step["clip"]
                        await page.screenshot(path=str(f), clip={"x": x, "y": y, "width": cw, "height": ch})
                    else:
                        await page.screenshot(path=str(f))
                    text = " ".join((await page.evaluate("document.body.innerText"))[:600].split())
                    events.append({"t": now(), "type": "shot", "name": step["shot"], "desc": step.get("desc", ""),
                                   "clip": step.get("clip"), "x": cursor[0], "y": cursor[1]})
                    meta.append({"name": step["shot"], "file": f.name, "desc": step.get("desc", ""), "page_text": text})
                    await page.wait_for_timeout(int(step.get("idle", IDLE_AFTER_SHOT) * 1000))
            except Exception as e:
                print(f"  ! 跳过一步 {step}: {str(e).splitlines()[0]}")
        await page.wait_for_timeout(500)
        t_end = time.time()
        await cdp.send("Page.stopScreencast")
        await browser.close()

    # 帧时间戳 → 恒定 30fps 视频：在 30fps 的时间网格上，每格取「此刻最新到达的那一帧」，按顺序喂给 ffmpeg。
    # （不用 concat 的 duration：它会把短于 1/25 秒的帧拉长，画面越来越晚于鼠标事件）
    frames.sort()
    n_out = int((t_end - t0) * 30) + 1
    ts_list = [ts for ts, _ in frames]
    import bisect
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", "30", "-c:v", "mjpeg",
                             "-i", "-", "-vf", f"scale={int(w * dsf) // 2 * 2}:{int(h * dsf) // 2 * 2}:flags=lanczos,format=yuv420p",
                             "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-r", "30", "rec.mp4"], cwd=rec, stdin=subprocess.PIPE)
    cache = {}
    for kf in range(n_out):
        t = t0 + kf / 30
        i = max(0, bisect.bisect_right(ts_list, t) - 1)
        name = frames[i][1]
        if name not in cache:
            cache.clear()
            cache[name] = (frames_dir / name).read_bytes()
        proc.stdin.write(cache[name])
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg 合录屏失败")
    shutil.rmtree(frames_dir)
    (rec / "events.json").write_text(json.dumps({"viewport": [w, h], "duration": round(t_end - t0, 3),
                                                 "events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "shots.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  录屏 {t_end - t0:.1f} 秒，原始帧 {len(frames)} 张，事件 {len(events)} 个 -> {rec}")
    return tour, meta
