"""成片自检：视频参数、音量、逐段配音转写回文字和稿子对比（DeepSeek ASR）。

  python -m fabu.verify out/11-xiaohai-riji
"""
import difflib
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fabu.ledger import LEDGER  # noqa: E402


def han(s):
    return re.sub(r"[^一-鿿0-9a-zA-Z]", "", s)


def asr(wav):
    import time
    for k in range(4):  # 走本机代理时偶尔断连接，重试几次
        try:
            with open(wav, "rb") as f:
                r = httpx.post("https://api.deepseek.com/v1/tools/asr", timeout=180,
                               headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
                               files={"file": (Path(wav).name, f, "audio/wav")})
            r.raise_for_status()
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if k == 3 or (isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500):
                raise
            print(f"  ! 转写请求失败，{3 * (k + 1)} 秒后重试：{str(e)[:80]}")
            time.sleep(3 * (k + 1))
    with wave.open(str(wav), "rb") as w:
        LEDGER.add_asr(w.getnframes() / w.getframerate())
    return r.json()["text"]


def _cut(out, i):
    spans = json.loads((out / "build_narration.json").read_text(encoding="utf-8"))
    a, b = spans[i]
    dst = out / "build" / f"nar{i:02d}.wav"
    dst.parent.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out / "build_narration.wav"), "-ss", f"{a:.3f}",
                    "-to", f"{b:.3f}", str(dst)], check=True)
    return dst


def main(out_dir):
    out = Path(out_dir)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_name,width,height,sample_rate:format=duration", "-of", "json",
                            str(out / "video.mp4")], capture_output=True, text=True, check=True).stdout
    info = json.loads(probe)
    vol = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out / "video.mp4"), "-af", "volumedetect", "-vn", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mean = re.search(r"mean_volume: ([-\d.]+)", vol).group(1)
    peak = re.search(r"max_volume: ([-\d.]+)", vol).group(1)
    plan = json.loads((out / "audio_plan.json").read_text(encoding="utf-8"))
    rows, scores = [], []
    for i, seg in enumerate(plan):
        want = "".join(l["text"] for l in seg["lines"])
        seg_wav = out / "build" / f"seg{i:02d}.wav"
        if (out / "build_narration.wav").exists() and (Path(str(out)) / "build_narration.json").exists():
            seg_wav = _cut(out, i)
        got = asr(seg_wav)
        sc = difflib.SequenceMatcher(None, han(want), han(got)).ratio()
        scores.append(sc)
        rows.append({"seg": i + 1, "want": want, "asr": got, "match": round(sc, 3)})
    report = {"streams": info["streams"], "duration": float(info["format"]["duration"]),
              "mean_volume_db": float(mean), "max_volume_db": float(peak),
              "asr_match_avg": round(sum(scores) / len(scores), 3), "asr_match_min": round(min(scores), 3), "segments": rows}
    (out / "verify.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"时长 {report['duration']:.1f}s  平均音量 {mean} dB  峰值 {peak} dB")
    for r in rows:
        print(f"  段{r['seg']} 一致度 {r['match']:.2f}  ASR：{r['asr']}")
    print(f"配音转写与稿子平均一致度 {report['asr_match_avg']:.2f}（最低 {report['asr_match_min']:.2f}）")
    return report


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from run import load_env
    load_env()
    main(sys.argv[1])
