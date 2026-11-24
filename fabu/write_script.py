"""第 2 步：让 LLM 写讲解稿 + 三平台文案，输出 script.json。

提供方（--llm）：
  deepseek  DEEPSEEK_API_KEY，模型 deepseek-flash（OpenAI 兼容 /chat/completions）
  codex     本机 codex exec（ChatGPT 账号登录）
  file      只写出 prompt.md，等人或别的模型把 script.json 放进来（没有 key 时用）
"""
import json
import os
import re
import subprocess
from pathlib import Path

import httpx

from fabu.ledger import LEDGER

SCHEMA = r"""
只输出一个 JSON 对象，不要任何解释，不要 Markdown 代码块。结构：
{
  "hook": "视频顶部常驻的一句话，≤16 字，说清这是什么",
  "segments": [
    {"shot": "截图名（只能从下面的截图清单里选）", "text": "这一段的口播稿"}
  ],
  "bilibili":     {"title": "≤40 字", "desc": "简介 80–200 字，可分行", "tags": ["≤10 个，不带 #"], "tid_hint": "建议分区，比如 知识/科学科普 或 生活/日常"},
  "xiaohongshu":  {"title": "≤20 字（平台硬上限）", "body": "正文 150–400 字，口语、分段，可以有少量 emoji", "tags": ["5–8 个话题，不带 #"]},
  "douyin":       {"title": "作品标题 ≤30 字", "desc": "作品描述 ≤100 字，末尾不用自己写 #", "tags": ["3–5 个话题，不带 #"]},
  "pinned_comment": "置顶评论：一句话说去哪玩，链接位置写成 {链接} 占位（发之前换成国内能打开的地址）"
}
"""

RULES = """
口播稿要求：
- 竖屏短视频，总时长 45–60 秒，全部 segments 的 text 加起来 200–260 个汉字。5–8 段。
- 第一段 3 秒内给钩子：说出观众自己的处境，不要"大家好""今天给大家介绍"。
- 讲清三件事：这是什么、怎么玩（跟着截图顺序走）、玩完得到什么。最后一段一句收尾 + 去哪玩。
- 每段的 text 要和它配的截图对得上，观众是边看画面边听。
- 用说话的口气，短句，一句不超过 25 字，句末用。！？ 断开（配音和字幕按这三个标点切）。
- 不要夸张营销腔：不说"绝了""宝藏""神器""YYDS""家人们"，不用"不是……而是……"句式。
- 产品是作者自己做的小网页，用第一人称"我做了"。
- 不要念网址。
链接规则：作品放在 vercel.app 上，中国大陆打不开。视频和文案里都不要写这个网址；告诉观众"链接放在评论区/简介"即可。
文案要求：三个平台各写各的，不要互相复制。B 站偏完整说明，小红书偏个人分享口吻，抖音最短。
"""


def build_prompt(tour, shots, product_text):
    lines = [f"你是短视频编导。下面是我做的一个网页小作品「{tour['name']}」。请写一条竖屏讲解视频的口播稿和三平台发布文案。",
             "", "## 作品说明（作者写的）", product_text.strip()[:3500], "", "## 截图清单（按操作顺序）"]
    for s in shots:
        lines.append(f"- {s['name']}：{s['desc']}｜画面文字：{s['page_text'][:160]}")
    lines += ["", "## 要求", RULES, "## 输出格式", SCHEMA]
    return "\n".join(lines)


def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型输出里找不到 JSON")
    return json.loads(m.group(0))


def call_deepseek(prompt):
    key = os.environ["DEEPSEEK_API_KEY"]
    r = httpx.post("https://api.deepseek.com/chat/completions", timeout=120,
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
                         "messages": [{"role": "user", "content": prompt}], "stream": False})
    r.raise_for_status()
    data = r.json()
    LEDGER.add_llm(data.get("usage", {}))
    return data["choices"][0]["message"]["content"]


def call_codex(prompt, work):
    pf, of = work / "prompt.md", work / "codex_last.txt"
    with open(pf, "rb") as fin:
        subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-o", str(of), "-"],
                       stdin=fin, check=True, timeout=600)
    return of.read_text(encoding="utf-8")


def validate(script, shot_names):
    problems = []
    for i, seg in enumerate(script.get("segments", [])):
        if seg.get("shot") not in shot_names:
            problems.append(f"第 {i+1} 段用了不存在的截图 {seg.get('shot')}")
    total = sum(len(re.sub(r"[^一-鿿]", "", s["text"])) for s in script["segments"])
    if not 150 <= total <= 320:
        problems.append(f"口播汉字数 {total}，不在 150–320 之间")
    xt = script["xiaohongshu"]["title"]
    if len(xt) > 20:
        problems.append(f"小红书标题 {len(xt)} 字，超过 20 字上限")
    pin = script.get("pinned_comment", "")
    if "评论区" in json.dumps(script["segments"], ensure_ascii=False) and "简介" in pin and "评论" not in pin:
        problems.append("口播说链接在评论区，置顶评论却说在简介，前后不一致")
    blob = json.dumps(script, ensure_ascii=False)
    if "vercel" in blob.lower():
        problems.append("稿子里出现了 vercel 网址（大陆打不开）")
    return problems


def write_script(tour, shots, product_text, out_dir, llm="deepseek"):
    out_dir = Path(out_dir)
    prompt = build_prompt(tour, shots, product_text)
    (out_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    target = out_dir / "script.json"
    if llm == "deepseek":
        script = _extract_json(call_deepseek(prompt))
    elif llm == "codex":
        script = _extract_json(call_codex(prompt, out_dir))
    elif llm == "file":
        if not target.exists():
            raise SystemExit(f"已写出 {out_dir/'prompt.md'}；把模型按它生成的 JSON 存成 {target} 再重跑")
        script = _extract_json(target.read_text(encoding="utf-8"))
    else:
        raise ValueError(llm)
    problems = validate(script, {s["name"] for s in shots})
    for p in problems:
        print("  ! 稿子检查：", p)
    target.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    return script, problems
