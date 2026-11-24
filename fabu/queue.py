"""第 6 步：发布队列。到点触发，但真正上传前一定停下来等你确认。

  python -m fabu.queue add out/11-xiaohai-riji "2026-11-20 20:30" [--platforms douyin,xiaohongshu,bilibili] [--mode native]
  python -m fabu.queue list
  python -m fabu.queue tick              # 检查到点的任务：改成「等你确认」，弹系统通知
  python -m fabu.queue watch             # 每 30 秒 tick 一次（demo 用；日常交给 Windows 计划任务）
  python -m fabu.queue confirm <id>      # 打印将要执行的上传命令（不执行）
  python -m fabu.queue confirm <id> --go # 真的执行 sau 上传

两种模式：
  remind（默认）  到点提醒你，你确认后立刻发。电脑要开着。
  native          你先确认，sau 上传时带 --schedule，交给平台自己的定时发布；到点时电脑可以关着。
时间一律按北京时间（UTC+8，中国没有夏令时，所以用固定偏移，不受本机时区影响）。
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue.json"
BJ = timezone(timedelta(hours=8))
FMT = "%Y-%m-%d %H:%M"

SAU_DIR = Path(__file__).resolve().parent.parent / "vendor" / "social-auto-upload"
SAU = str(SAU_DIR / ".venv" / "Scripts" / "sau.exe") if (SAU_DIR / ".venv" / "Scripts" / "sau.exe").exists() else "sau"
ACCOUNT = "main"          # sau 里登录的账号名：sau douyin login --account main
BILIBILI_TID = "21"       # B 站分区 id，sau 第一版必须传；21 是「日常」，发之前请在 B 站投稿页核对


def now_bj():
    return datetime.now(BJ)


def load():
    return json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []


def save(jobs):
    QUEUE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def add_jobs(out_dir, when, platforms=("douyin", "xiaohongshu", "bilibili"), mode="remind"):
    datetime.strptime(when, FMT)  # 格式不对直接报错
    out_dir = Path(out_dir).resolve()
    jobs = load()
    for p in platforms:
        jobs.append({"id": uuid.uuid4().hex[:6], "platform": p, "out_dir": str(out_dir), "at": when,
                     "mode": mode, "status": "scheduled", "log": [f"{now_bj():%Y-%m-%d %H:%M:%S} 排进队列"]})
        print(f"  排队 {jobs[-1]['id']}  {p:<12} 北京时间 {when}  模式 {mode}")
    save(jobs)
    return jobs


def sau_command(job):
    pub = json.loads((Path(job["out_dir"]) / "publish.json").read_text(encoding="utf-8"))
    p = job["platform"]
    c = pub["platforms"][p]
    base = Path(job["out_dir"])
    absp = lambda f: str((base / Path(f).name).resolve()) if not Path(f).is_absolute() else f  # noqa: E731
    cmd = [SAU, p, "upload-video", "--account", ACCOUNT, "--file", absp(pub["video"]), "--title", c["title"],
           "--desc", c["desc"], "--tags", ",".join(c["tags"])]
    if p == "bilibili":
        cmd += ["--tid", BILIBILI_TID]
    cmd += ["--thumbnail", absp(pub["cover_3x4"] if p == "xiaohongshu" else pub["cover_9x16"])]
    if job["mode"] == "native":
        cmd += ["--schedule", job["at"]]
    return cmd


def notify(title, body):
    """Windows 系统通知；失败就算了，终端里也会打印。"""
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
          "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
          f"$x=$t.GetElementsByTagName('text');$x.Item(0).AppendChild($t.CreateTextNode('{title}'))>$null;"
          f"$x.Item(1).AppendChild($t.CreateTextNode('{body}'))>$null;"
          "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('PowerShell').Show($n)")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=20)
    except Exception:
        pass


def tick():
    jobs, fired = load(), 0
    for j in jobs:
        if j["status"] != "scheduled":
            continue
        due = datetime.strptime(j["at"], FMT).replace(tzinfo=BJ)
        if now_bj() >= due:
            j["status"] = "awaiting_confirm"
            j["log"].append(f"{now_bj():%Y-%m-%d %H:%M:%S} 到点触发，等你确认")
            fired += 1
            msg = f"{j['platform']} 到点了：python -m fabu.queue confirm {j['id']} --go"
            print("  ⏰", msg)
            notify("发片台：该发了", msg)
    save(jobs)
    return fired


def show():
    for j in load():
        print(f"{j['id']}  {j['platform']:<12} {j['at']}  {j['mode']:<6}  {j['status']}")


def confirm(jid, go=False):
    jobs = load()
    j = next(x for x in jobs if x["id"] == jid)
    cmd = sau_command(j)
    print("将要执行：")
    print("  " + subprocess.list2cmdline(cmd))
    if not go:
        print("（只是预览。确认无误后加 --go 才会真的上传。）")
        return
    if j["mode"] == "remind" and j["status"] != "awaiting_confirm":
        sys.exit("还没到点。要提前交给平台定时发，请用 --mode native 重新排队。")
    if SAU == "sau" and not shutil.which("sau"):
        sys.exit("没装 sau（social-auto-upload）。装法见 README「接上真实账号」。")
    r = subprocess.run(cmd, cwd=SAU_DIR if SAU_DIR.exists() else None)
    j["status"] = "published" if r.returncode == 0 and j["mode"] == "remind" else (
        "handed_to_platform" if r.returncode == 0 else "failed")
    j["log"].append(f"{now_bj():%Y-%m-%d %H:%M:%S} 执行 sau，退出码 {r.returncode}")
    save(jobs)


def login(platforms=("douyin", "xiaohongshu", "bilibili")):
    """依次打开三个平台的扫码登录（要用户本人用手机扫）；登录信息存在 sau 的 cookies/ 下，之后一直记住。"""
    for p in platforms:
        print(f"== {p}：请用手机 App 扫码登录")
        subprocess.run([SAU, p, "login", "--account", ACCOUNT], cwd=SAU_DIR)
        subprocess.run([SAU, p, "check", "--account", ACCOUNT], cwd=SAU_DIR)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("out_dir"); a.add_argument("when")
    a.add_argument("--platforms", default="douyin,xiaohongshu,bilibili"); a.add_argument("--mode", default="remind", choices=["remind", "native"])
    sub.add_parser("list"); sub.add_parser("tick")
    w = sub.add_parser("watch"); w.add_argument("--every", type=int, default=30); w.add_argument("--until-fired", action="store_true")
    c = sub.add_parser("confirm"); c.add_argument("id"); c.add_argument("--go", action="store_true")
    lg = sub.add_parser("login"); lg.add_argument("--platforms", default="douyin,xiaohongshu,bilibili")
    args = ap.parse_args()
    if args.cmd == "add":
        add_jobs(args.out_dir, args.when, args.platforms.split(","), args.mode)
    elif args.cmd == "list":
        show()
    elif args.cmd == "tick":
        tick()
    elif args.cmd == "watch":
        while True:
            print(f"[{now_bj():%H:%M:%S} 北京时间] 检查队列")
            if tick() and args.until_fired:
                break
            time.sleep(args.every)
    elif args.cmd == "login":
        login(tuple(args.platforms.split(",")))
    elif args.cmd == "confirm":
        confirm(args.id, args.go)


if __name__ == "__main__":
    main()
