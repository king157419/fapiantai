"""第 1 步：按 tour 文件打开作品、点一遍、在关键画面截图。

输出：out/<slug>/shots/<name>.png 和 shots.json（每张图的说明 + 当时页面上的文字，给写稿用）。
没有 tour 文件时，capture_generic 会截首屏 + 整页长图。
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def _resolve_url(tour, tour_path):
    src = tour.get("src")
    if src and not src.startswith("http"):
        p = (Path(tour_path).parent / src).resolve()
        if p.is_dir():
            p = p / "index.html"
        return p.as_uri() + tour.get("query", "")
    return (src or tour["url_public"]) + tour.get("query", "")


def _launch(pw):
    # Playwright 自带的浏览器在这台机器上没装；依次试本机 Chrome、Edge、自带
    for ch in ("chrome", "msedge", None):
        try:
            return pw.chromium.launch(channel=ch) if ch else pw.chromium.launch()
        except Exception:
            continue
    raise RuntimeError("找不到可用的浏览器：装 Chrome 或运行 playwright install chromium")


def capture(tour_path, out_dir):
    tour = json.loads(Path(tour_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    url = _resolve_url(tour, tour_path)
    w, h = tour.get("viewport", [390, 844])
    dsf = tour.get("scale", 2)
    mobile = w < 600  # 桌面软件（比如精彩时刻）按桌面浏览器开，不模拟手机
    never = tour.get("never_click", [])  # 绝对不能点的按钮（删除、收藏这类会改真实数据的）
    meta = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=dsf,
                                is_mobile=mobile, has_touch=mobile, locale="zh-CN")
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(tour.get("boot_wait", 800))
        for step in tour["steps"]:
            try:
                if "click" in step:
                    if any(n in step["click"] for n in never):
                        print(f"  ! 拒绝点击（在 never_click 里）：{step['click']}")
                        continue
                    page.locator(step["click"]).first.click(timeout=4000)
                elif "key" in step:
                    if step["key"] in tour.get("never_key", []):
                        print(f"  ! 拒绝按键（在 never_key 里）：{step['key']}")
                        continue
                    page.keyboard.press(step["key"])
                elif "type" in step:
                    page.locator(step["type"]).first.fill(step["text"], timeout=4000)
                elif "wait" in step:
                    page.wait_for_timeout(step["wait"])
                elif "shot" in step:
                    f = shots_dir / f"{step['shot']}.png"
                    if step.get("clip"):  # 只截一块（CSS 像素 x, y, 宽, 高），用来放大细节
                        x, y, cw, ch = step["clip"]
                        page.screenshot(path=str(f), clip={"x": x, "y": y, "width": cw, "height": ch})
                    else:
                        page.screenshot(path=str(f), full_page=bool(step.get("full")))
                    text = page.evaluate("document.body.innerText")[:600]
                    meta.append({"name": step["shot"], "file": f.name, "desc": step.get("desc", ""),
                                 "page_text": " ".join(text.split())})
            except Exception as e:  # 某一步点不到就跳过，别让整条流水线停下
                print(f"  ! 跳过一步 {step}: {str(e).splitlines()[0]}")
        browser.close()
    (out_dir / "shots.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  截图 {len(meta)} 张 -> {shots_dir}")
    return tour, meta
