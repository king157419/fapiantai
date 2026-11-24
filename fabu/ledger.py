"""记账：每一步花了多少秒、调了多少次 DeepSeek、花了多少钱。

价格来自 https://api-docs.deepseek.com/zh-cn/quick_start/pricing （2026-11-19 查）：
  deepseek-flash（元/百万 tokens）：空闲 输入命中 0.02 / 未命中 1 / 输出 4；高峰翻倍 0.04 / 2 / 8
  高峰 = 北京时间周一到周五 9:00–12:00、14:00–18:00（法定节假日算空闲，这里没判断节假日）
  TTS：每 1 万字符 1.5 元（限时 5 折，刊例价 3 元）
  ASR：每小时音频 0.39 元（限时 5 折，刊例价 0.78 元）
输出：out/<作品>/cost.json，并在 27/ledger.csv 追加一行（每次运行一行，方便以后算平均）。
"""
import csv
import json
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
FLASH = {"idle": (0.02, 1.0, 4.0), "peak": (0.04, 2.0, 8.0)}  # 命中, 未命中, 输出；元/百万 tokens
TTS_PER_10K = 1.5
ASR_PER_HOUR = 0.39


def period(now=None):
    now = now or datetime.now(BJ)
    h = now.hour + now.minute / 60
    if now.weekday() < 5 and (9 <= h < 12 or 14 <= h < 18):
        return "peak"
    return "idle"


class Ledger:
    def __init__(self):
        self.reset()

    def reset(self):
        self.started = datetime.now(BJ)
        self.steps = []          # [(名字, 秒)]
        self.llm = {"calls": 0, "hit": 0, "miss": 0, "out": 0, "yuan": 0.0}
        self.tts = {"calls": 0, "chars": 0, "cached": 0, "yuan": 0.0}
        self.asr = {"calls": 0, "seconds": 0.0, "yuan": 0.0}

    @contextmanager
    def step(self, name):
        t = time.perf_counter()
        try:
            yield
        finally:
            sec = time.perf_counter() - t
            self.steps.append((name, round(sec, 1)))
            print(f"  （{name} 用时 {sec:.1f} 秒）")

    def add_llm(self, usage):
        hit = usage.get("prompt_cache_hit_tokens", 0)
        miss = usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0) - hit)
        out = usage.get("completion_tokens", 0)
        p_hit, p_miss, p_out = FLASH[period()]
        self.llm["calls"] += 1
        self.llm["hit"] += hit
        self.llm["miss"] += miss
        self.llm["out"] += out
        self.llm["yuan"] += (hit * p_hit + miss * p_miss + out * p_out) / 1e6

    def add_tts(self, text):
        self.tts["calls"] += 1
        self.tts["chars"] += len(text)
        self.tts["yuan"] += len(text) / 10000 * TTS_PER_10K

    def tts_cached(self):
        self.tts["cached"] += 1

    def add_asr(self, seconds):
        self.asr["calls"] += 1
        self.asr["seconds"] += seconds
        self.asr["yuan"] += seconds / 3600 * ASR_PER_HOUR

    def total_yuan(self):
        return self.llm["yuan"] + self.tts["yuan"] + self.asr["yuan"]

    def save(self, out_dir, slug, extra=None):
        out_dir = Path(out_dir)
        rep = {
            "作品": slug,
            "开始（北京时间）": self.started.strftime("%Y-%m-%d %H:%M"),
            "计价时段": "高峰" if period(self.started) == "peak" else "空闲",
            "机器用时_秒": dict(self.steps),
            "机器用时合计_秒": round(sum(s for _, s in self.steps), 1),
            "写稿_DeepSeek": {**self.llm, "yuan": round(self.llm["yuan"], 4)},
            "配音_DeepSeekTTS": {**self.tts, "yuan": round(self.tts["yuan"], 4)},
            "自检_DeepSeekASR": {**self.asr, "seconds": round(self.asr["seconds"], 1), "yuan": round(self.asr["yuan"], 4)},
            "API合计_元": round(self.total_yuan(), 4),
            **(extra or {}),
        }
        (out_dir / "cost.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        book = Path(__file__).resolve().parent.parent / "ledger.csv"
        new = not book.exists()
        with open(book, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["开始", "作品", "时段", "机器用时秒", "写稿tokens(入/出)", "配音字数", "自检音频秒", "API元", "人工分钟", "备注"])
            w.writerow([rep["开始（北京时间）"], slug, rep["计价时段"], rep["机器用时合计_秒"],
                        f"{self.llm['hit'] + self.llm['miss']}/{self.llm['out']}", self.tts["chars"],
                        round(self.asr["seconds"], 1), rep["API合计_元"], (extra or {}).get("人工分钟", ""),
                        (extra or {}).get("备注", "")])
        print(f"  记账：机器 {rep['机器用时合计_秒']} 秒，API {rep['API合计_元']} 元 -> {out_dir / 'cost.json'}")
        return rep


LEDGER = Ledger()
