"""一键：作品 → 截图 → 讲解稿 → 配音 → 竖屏视频 → 三平台文案 → 进发布队列。

用法：
  python run.py tours/11-xiaohai-riji.json --llm deepseek --tts deepseek
  python run.py tours/11-xiaohai-riji.json --llm file --tts edge      # 没有 key 时
可选：--skip-capture（沿用已有截图）  --voice tide  --schedule "2026-11-20 20:30"
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fabu.capture import capture  # noqa: E402
from fabu.compose import compose, make_covers  # noqa: E402
from fabu.copy_pack import write_copy  # noqa: E402
from fabu.tts import synthesize  # noqa: E402
from fabu.write_script import write_script  # noqa: E402
from fabu.ledger import LEDGER  # noqa: E402


def load_env():
    # 这台机器的 SSL_CERT_FILE 指向一个不存在的文件，会让 httpx 直接报错；指向的文件不存在就忽略它
    for k in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
        if os.environ.get(k) and not Path(os.environ[k]).exists():
            os.environ.pop(k)
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tour")
    ap.add_argument("--llm", default="deepseek", choices=["deepseek", "codex", "file"])
    ap.add_argument("--tts", default="deepseek", choices=["deepseek", "edge"])
    ap.add_argument("--voice")
    ap.add_argument("--skip-capture", action="store_true")
    ap.add_argument("--schedule", help="发布时间，格式 YYYY-MM-DD HH:MM（北京时间），三个平台都排这个时间")
    ap.add_argument("--verify", action="store_true", help="最后用 DeepSeek ASR 把配音转写回文字做自检")
    ap.add_argument("--fresh", action="store_true", help="删掉旧的配音缓存，全部重新合成（记账才准）")
    ap.add_argument("--human-min", type=float, help="这次人工花的分钟数（写 tour 文件、看片），记进账本")
    ap.add_argument("--note", default="", help="账本备注")
    ap.add_argument("--renderer", default="remotion", choices=["remotion", "ffmpeg"],
                    help="remotion（默认）：真实录屏 + 鼠标轨迹 + 点击放大；ffmpeg：旧版，截图平移")
    a = ap.parse_args()
    load_env()
    tour_path = Path(a.tour).resolve()
    slug = tour_path.stem
    out = ROOT / "out" / slug
    out.mkdir(parents=True, exist_ok=True)
    tour = json.loads(tour_path.read_text(encoding="utf-8"))
    src = (tour_path.parent / tour["src"]).resolve()

    if a.fresh:
        import shutil
        shutil.rmtree(out / "audio", ignore_errors=True)
    LEDGER.reset()
    t0 = time.perf_counter()

    print("① 截图")
    with LEDGER.step("截图"):
        if a.skip_capture and (out / "shots.json").exists() and (a.renderer == "ffmpeg" or (out / "rec" / "events.json").exists()):
            shots = json.loads((out / "shots.json").read_text(encoding="utf-8"))
        elif a.renderer == "remotion":
            from fabu.record import record
            _, shots = record(tour_path, out)
        else:
            _, shots = capture(tour_path, out)

    print("② 写讲解稿和文案")
    product = ""
    for name in tour.get("product_docs", ["PRODUCT.md", "README.md"]):
        if (src / name).exists():
            product += (src / name).read_text(encoding="utf-8") + "\n"
    product += tour.get("product_note", "")
    with LEDGER.step("写稿"):
        script, problems = write_script(tour, shots, product, out, llm=a.llm)

    print("③ 配音")
    with LEDGER.step("配音"):
        plan = synthesize(script, out, engine=a.tts, voice=a.voice)

    print("④ 合成视频")
    with LEDGER.step("合成"):
        if a.renderer == "remotion":
            from fabu.remotion_build import render
            video = render(tour, script, plan, out)
        else:
            video = compose(tour, script, plan, out)
        art = src / "art" / "cover.jpg"
        if tour.get("cover_art"):
            art = (tour_path.parent / tour["cover_art"]).resolve()
        covers = make_covers(tour, script, out, art if art.exists() else None)

    print("⑤ 三平台文案")
    with LEDGER.step("文案包"):
        write_copy(tour, script, out, covers)

    if a.schedule:
        print("⑥ 进发布队列")
        from fabu.queue import add_jobs
        add_jobs(out, a.schedule)

    extra = {"人工分钟": a.human_min, "备注": a.note, "LLM": a.llm, "TTS": a.tts}
    if a.verify:
        print("⑦ 自检")
        from fabu.verify import main as verify_main
        with LEDGER.step("自检"):
            rep = verify_main(out)
        extra["配音转写一致度"] = rep["asr_match_avg"]
        extra["成片秒数"] = round(rep["duration"], 1)
    extra["总墙钟秒"] = round(time.perf_counter() - t0, 1)
    LEDGER.save(out, slug, extra)
    print("完成：", out)


if __name__ == "__main__":
    main()
