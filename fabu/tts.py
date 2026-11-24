"""第 3 步：把口播稿按句切开，一句一句配音，量出每句时长，用来对字幕。

引擎（--tts）：
  deepseek  POST https://api.deepseek.com/v1/tools/tts，voice_id = stella(女) / tide(男)，返回 wav。
            官方文档 2026-11-13 上线；不支持调语速，也不返回字级时间戳，所以按句合成、按句对字幕。
  edge      edge-tts（微软 Edge 朗读，免费、不要 key），默认 zh-CN-XiaoxiaoNeural。
每句统一转成 24kHz 单声道 wav，方便拼接。
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import httpx

from fabu.ledger import LEDGER

SENT_SPLIT = re.compile(r"(?<=[。！？!?])")


def split_sentences(text):
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


TRIM = ("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.04,areverse,"
        "silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.08,areverse")


def _norm(src, dst):
    # 统一成 24kHz 单声道，并切掉每句首尾的空白（edge-tts 每句前后各带约 0.3 秒），停顿由合成步骤统一控制
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-af", TRIM,
                    "-ar", "24000", "-ac", "1", str(dst)], check=True)


def tts_deepseek(text, dst, voice="stella", tries=4):
    # 走本机代理时偶尔会断 TLS 连接（SSL EOF / 超时），等几秒重试
    import time
    for k in range(tries):
        try:
            return _tts_deepseek_once(text, dst, voice)
        except (httpx.TransportError, httpx.RemoteProtocolError) as e:
            if k == tries - 1:
                raise
            print(f"  ! 配音请求失败，{3 * (k + 1)} 秒后重试：{str(e)[:80]}")
            time.sleep(3 * (k + 1))


def _tts_deepseek_once(text, dst, voice):
    raw = dst.with_suffix(".raw.wav")
    with httpx.stream("POST", "https://api.deepseek.com/v1/tools/tts", timeout=120,
                      headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
                      json={"text": text, "voice_id": voice, "format": "wav"}) as r:
        r.raise_for_status()
        LEDGER.add_tts(text)
        with open(raw, "wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    _norm(raw, dst)
    raw.unlink()


def tts_edge(text, dst, voice="zh-CN-XiaoxiaoNeural", rate="+6%"):
    import edge_tts
    mp3 = dst.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(mp3)))
    _norm(mp3, dst)
    mp3.unlink()


def synthesize(script, out_dir, engine="edge", voice=None):
    out_dir = Path(out_dir)
    adir = out_dir / "audio"
    adir.mkdir(parents=True, exist_ok=True)
    plan = []
    for si, seg in enumerate(script["segments"]):
        lines = []
        for li, sent in enumerate(split_sentences(seg["text"])):
            # 文件名带上句子和声音的指纹：改了稿子只重配改过的句子，不会沿用旧配音
            tag = hashlib.md5(f"{engine}|{voice}|{sent}".encode()).hexdigest()[:8]
            f = adir / f"s{si:02d}_{li:02d}_{tag}.wav"
            if not f.exists():
                if engine == "deepseek":
                    tts_deepseek(sent, f, voice or "stella")
                else:
                    tts_edge(sent, f, voice or "zh-CN-XiaoxiaoNeural")
            else:
                LEDGER.tts_cached()
            lines.append({"text": sent, "file": str(f), "dur": duration(f)})
        plan.append({"shot": seg["shot"], "lines": lines})
    (out_dir / "audio_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(l["dur"] for p in plan for l in p["lines"])
    print(f"  配音 {sum(len(p['lines']) for p in plan)} 句，纯语音 {total:.1f} 秒（引擎 {engine}）")
    return plan
