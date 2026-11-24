# 发片台

把做好的网页小作品自动变成一条带配音和字幕的竖屏讲解视频，并写好 B 站、小红书、抖音三个平台各自的标题、文案和标签，排进发布队列；到了发布时间先提醒你，你点头才上传。

## 一条命令

```
cd D:\desk\claudex\27
D:\conda\miniconda3\python.exe run.py tours\11-xiaohai-riji.json --llm deepseek --tts deepseek --schedule "2026-11-21 20:30"
```

输出在 `out\<作品名>\`：

| 文件 | 是什么 |
|---|---|
| `video.mp4` | 1080×1920 竖屏讲解视频，约 50 秒，配音和逐句字幕都已经压进画面 |
| `video.srt` | 字幕文件（B 站可以另外上传成 CC 字幕） |
| `cover_9x16.jpg` / `cover_3x4.jpg` | 封面：抖音和 B 站用 9:16，小红书用 3:4 |
| `发布包.md` | 三个平台的标题、正文、标签和置顶评论，手动发布时直接复制 |
| `publish.json` | 同样的内容，给发布队列读 |
| `script.json` / `prompt.md` | 讲解稿，和生成它用的提示词 |
| `verify.json` | 自检结果：配音转写回文字，跟稿子逐段对比 |

## 流水线

1. **截图**（`fabu/capture.py`）：用本机 Chrome 打开作品，按 `tours\*.json` 里写好的步骤点一遍，在关键画面截图（手机尺寸 390×844，2 倍清晰度）。
2. **写稿**（`fabu/write_script.py`）：把作品的 README / PRODUCT.md 和截图说明交给 LLM，生成口播稿（每段对应一张截图）和三平台文案。写完会自动检查：截图名是否存在、字数是否合适、小红书标题有没有超过 20 字、有没有写 vercel 网址、链接位置前后是否一致。
3. **配音**（`fabu/tts.py`）：一句一句合成，切掉每句首尾的空白，量出每句的时长。
4. **合成**（`fabu/compose.py`）：纸色背景，作品截图放在圆角卡片里慢慢往下移，字幕逐句出现，段与段之间截图淡入。
5. **文案包**（`fabu/copy_pack.py`）。
6. **发布队列**（`fabu/queue.py`）：见下。
7. **自检**（`fabu/verify.py`）：`python -m fabu.verify out\11-xiaohai-riji`。

## 换一个作品

复制 `tours\11-xiaohai-riji.json`，改 `name`、`src`（作品文件夹的相对路径或网址），把 `steps` 改成这个作品的操作步骤：`click`（CSS 选择器）、`type`、`wait`（毫秒）、`shot`（截图名 + 一句画面说明，`"full": true` 截整页长图）。哪一步点不到会跳过，不会让整条流水线停下来。

### 桌面软件也行（例：`tours\13-valo-moments.json`，精彩时刻）

- `src` 写本地网址，先按 tour 里的 `start_cmd` 把软件的网页服务开起来。
- `"card": "landscape"`：截图用横卡片，镜头慢慢平移推近，字幕贴在卡片下面。`viewport` 写桌面尺寸，`scale` 写清晰度。
- 截图步骤多了 `key`（按键，比如 `ArrowRight`）和 `clip`（只截一块放大，`[x, y, 宽, 高]`）。
- `never_click` / `never_key`：会改真实数据的按钮和键（删除、收藏、导出），写进去就绝对不会点。
- `scroll`（录屏版）：`{"scroll": "选择器"}` 把那个元素平滑滚到画面中间（弹层里的也行，`"block": "start"` 滚到顶）；`{"scroll": 600}` 整页往下滚 600 像素。长页面别靠 click 自动跳，会生硬，鼠标也会画到屏幕外。
- 手机尺寸的录屏（高明显大于宽）在 Remotion 里自动用整屏「手机卡片」，平时看到整屏，点击时推近；小字要看清就给镜头加 `clip`。
- `cover_art` + `"cover_fit": "contain"`：封面图整张放进去不裁（适合纯色底的拼图，例：`tours/art/03-kintsu-vessels.png`）。
- `product_docs` / `product_note`：给写稿模型看的作品说明，可以不用 README、自己写一段。`link_note`：发布包里的链接提醒。

## 成片用 Remotion 渲染（默认）

`run.py` 默认 `--renderer remotion`；旧版截图平移用 `--renderer ffmpeg`。

1. **真实录屏**（`fabu/record.py`）：Playwright 按 tour 操作一遍，用 Chrome 的录屏接口（CDP `Page.startScreencast`）录下全过程，按 30fps 的时间网格取帧编码成 `rec/rec.mp4`；同时记下每次鼠标移动、点击、按键的时间和坐标（`rec/events.json`）。每个镜头点完后停 7 秒，给配音留画面。
2. **排时间轴**（`fabu/remotion_build.py`）：句间停顿按标点和语气定；每段从「为这个镜头做的第一个动作」开始播录屏，动作比配音长就加速（最多 1.6 倍）；镜头在点击前推近、点完拉远，写了 `clip` 的镜头推到那一块；字幕按逗号断行；点击时混进一声轻「咔哒」；最后响度统一到 -16 LUFS。
3. **渲染**（`remotion/src/Explainer.jsx`，Remotion 4.0.539）：亚像素平移不抖，三次缓动，画鼠标、点击波纹、按键提示和字幕弹入。用本机 Chrome 渲染，60 秒成片大约 6 分钟。
   单独预览：`cd remotion && npx remotion studio src/index.jsx`。

## 每次花了多少时间和钱

每次运行都会写 `out\<作品>\cost.json`，并在 `27\ledger.csv` 追加一行：每步用时、DeepSeek 写稿 tokens、配音字数、自检音频秒数、按官方价折算的人民币。价格写在 `fabu\ledger.py` 顶部（2026-11-19 查的官方价格页；高峰/空闲按北京时间判断，没管法定节假日）。

- `--verify`：最后自动做配音自检（DeepSeek ASR），也记账。
- `--fresh`：清掉配音缓存全部重配。配音缓存按「句子内容 + 声音」命名，改了稿子只会重配改过的句子。
- `--human-min 10 --note "说明"`：把人工花的分钟数和备注记进账本。

## 写稿和配音用什么

- `--llm deepseek`：DeepSeek `deepseek-flash`，key 放在 `.env` 的 `DEEPSEEK_API_KEY`。
- `--llm codex`：用本机 codex exec。`--llm file`：只写出 `prompt.md`，你或者别的模型把 `script.json` 放进来，再重跑。
- `--tts deepseek`：DeepSeek TTS（`/v1/tools/tts`，2026-11-13 上线）。`--voice stella` 是女声（默认），`--voice tide` 是男声。不能调语速，也没有字级时间戳，所以这里按句合成、按句对齐字幕。
- `--tts edge`：edge-tts，免费、不用 key，默认 `zh-CN-XiaoxiaoNeural`，可以作为备用。

## 发布队列

```
python -m fabu.queue add out\11-xiaohai-riji "2026-11-21 20:30"              # 三个平台都排这个时间（北京时间）
python -m fabu.queue add out\11-xiaohai-riji "2026-11-21 20:30" --mode native --platforms bilibili
python -m fabu.queue list
python -m fabu.queue tick        # 检查有没有到点的任务；到点就改成「等你确认」，并弹一条 Windows 通知
python -m fabu.queue confirm <id>        # 预览将要执行的上传命令
python -m fabu.queue confirm <id> --go   # 真的上传
```

- `remind`（默认）：到点提醒你，你确认后马上发。到点时电脑要开着，并且有东西在定时跑 `tick`，比如 Windows 计划任务：
  `schtasks /Create /SC MINUTE /MO 10 /TN 发片台tick /TR "D:\conda\miniconda3\python.exe -m fabu.queue tick"`（起始目录要设成 27 文件夹；这一条没有替你建）。
- `native`：你提前确认，上传时带上 `--schedule`，由平台自己到点发布。电脑可以关着。**更推荐这种。**

## 接上真实账号（2026-11-19 已装好 sau，等扫码登录）

上传用开源的 [social-auto-upload](https://github.com/dreammis/social-auto-upload)（`sau` 命令，MIT 协议），原理是用浏览器模拟你在创作者中心手动操作。

- 装在 `vendor\social-auto-upload`（`.venv` 用 Python 3.12，`conf.py` 里 `LOCAL_CHROME_PATH` 指向本机 Chrome，没有另外下载浏览器）。登录信息存在 `vendor\social-auto-upload\cookies\<平台>_main.json`。
- 扫码登录（要你本人用手机扫）：`python -m fabu.queue login`，会依次打开抖音、小红书、B 站的登录页。只登一个平台：`--platforms bilibili`。
- 发布：`python -m fabu.queue add out\<作品> "2026-11-21 20:30" --mode native`，然后对每个任务 `confirm <id> --go`。native 会带上 `--schedule`，由平台到点发布。
- B 站分区 id 在 `fabu/queue.py` 的 `BILIBILI_TID`（现在是 21），第一次发之前在投稿页核对。
- 旧的演示队列挪到了 `queue.demo-1118.json`。

## 已知限制

- 作品在 vercel.app 上，大陆打不开。稿子里不念网址，置顶评论里的 `{链接}` 要换成国内能打开的地址。
- 截图步骤每个作品要手写一次（大约 10 分钟）。
- 没有背景音乐（怕版权问题），可以在剪映里加，或者用平台自带的曲库。
