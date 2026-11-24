"""第 5 步：把三平台文案整理成两份东西。
  发布包.md     人看的：每个平台的标题、正文、标签、封面，复制粘贴就能手动发
  publish.json  机器读的：发布队列用它拼 sau 命令
"""
import json
from pathlib import Path


def write_copy(tour, script, out_dir, covers):
    out_dir = Path(out_dir)
    b, x, d = script["bilibili"], script["xiaohongshu"], script["douyin"]
    pub = {
        "name": tour["name"],
        "video": str(out_dir / "video.mp4"),
        "srt": str(out_dir / "video.srt"),
        "cover_9x16": str(covers["cover_9x16.jpg"]),
        "cover_3x4": str(covers["cover_3x4.jpg"]),
        "pinned_comment": script.get("pinned_comment", ""),
        "platforms": {
            "bilibili": {"title": b["title"], "desc": b["desc"], "tags": b["tags"], "tid_hint": b.get("tid_hint", "")},
            "xiaohongshu": {"title": x["title"], "desc": x["body"], "tags": x["tags"]},
            "douyin": {"title": d["title"], "desc": d["desc"], "tags": d["tags"]},
        },
    }
    (out_dir / "publish.json").write_text(json.dumps(pub, ensure_ascii=False, indent=2), encoding="utf-8")

    def tags(ts):
        return " ".join("#" + t for t in ts)

    md = f"""# 发布包 · {tour['name']}

视频：`video.mp4`（1080×1920，竖屏）　字幕：`video.srt`（B 站可上传为 CC 字幕）
封面：`cover_9x16.jpg`（抖音 / B 站）　`cover_3x4.jpg`（小红书）

置顶评论：{pub['pinned_comment']}

> 链接提醒：{tour.get('link_note', '作品在 vercel.app 上，大陆打不开。评论区放的链接要换成国内能开的地址（自定义域名，或离线合订本）。')}

---

## B 站
**标题**（{len(b['title'])} 字）：{b['title']}

**简介**：
{b['desc']}

**标签**：{'，'.join(b['tags'])}
**分区建议**：{b.get('tid_hint', '')}

---

## 小红书
**标题**（{len(x['title'])} 字，上限 20）：{x['title']}

**正文**：
{x['body']}

{tags(x['tags'])}

---

## 抖音
**标题**：{d['title']}

**描述**：{d['desc']} {tags(d['tags'])}

---

## 口播稿（逐段）
""" + "\n".join(f"{i + 1}. 〔{s['shot']}〕{s['text']}" for i, s in enumerate(script["segments"])) + "\n"
    (out_dir / "发布包.md").write_text(md, encoding="utf-8")
    print(f"  文案 -> {out_dir / '发布包.md'}")
