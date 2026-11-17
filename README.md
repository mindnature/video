# 一人 AI 剧组 · Video Studio

**从一句创意到可检查的完整短片：剧本 → 分镜 → 视频提示词 → Flow 辅助生成 → 音轨 → FFmpeg 合成 → 复核。**

这是一个可运行的、**本地优先**的短视频生产工具，而不是依赖某个模型名称的单次提示词。基础功能只依赖 Python 3.10+ 和 FFmpeg；浏览器辅助与大语言模型扩写都是可选功能。适合单人创作、Codex / Antigravity / Gemini 等代理协助。

> 当前版本 **v0.1.0 / MVP**。**不会自动替你购买生成额度、破解登录、调用未公开的视频接口，也不能凭空生成 Google Flow 视频或自动完成中文声纹克隆。** 对 Flow 的网页操作是可选、需人工检查的辅助模式；TTS 声音可用外部工具生成后导入。所有不可自动验证的环节在质检说明中标出。

## 两种制作模式

| 模式 | 默认计划 | 重点 |
| --- | --- | --- |
| **handcraft** | 9:16、六镜头 × 10 秒、总长 60 秒 | 真实植物/纽扣/纸雕的物理制作步骤、材料可辨性、首尾帧与慢运镜 |
| **story** | 16:9、五镜头 × 12 秒、总长 60 秒 | 固定角色外貌、视觉动作笑点、台词时序、多场景连续性 |

**核心原则**：把工艺可制作性、导演规则和质量检查提前写进结构化项目数据，不把所有事情押在一次视频生成上。

## 快速开始

```bash
# 1. 安装（建议 Python 3.10+）；另需系统中安装 ffmpeg 和 ffprobe
python -m pip install -e .
video-studio doctor

# 2. 创建 60 秒手作视频项目
video-studio init projects/flower-art --preset handcraft --title "春日花影"

# 3. 在 projects/flower-art/project.json 中修改每一镜的材料、动作和分镜时间轴
# 4. 导出可以直接提交给视频模型的镜头提示词和制片资料
video-studio plan projects/flower-art

# 5. 在 Google Flow 或你自己的视频模型中生成第 01 镜，下载后导入
video-studio ingest projects/flower-art --shot 01 --file /path/to/scene_01.mp4
# 按相同方法导入第 02 至 06 镜；再次导入同镜头会自动编号 v002 等

# 6. 视频准备检查（缺镜头会明确列出）
video-studio qa projects/flower-art

# 7. 统一画幅、帧率、音频，并拼接完整视频
video-studio render projects/flower-art
# 输出：projects/flower-art/exports/final_master.mp4
```

生成资料路径：`production/storyboard.md`、`production/prompts/shot_01.txt` ...、`production/voice_lines.csv`、`production/subtitles.srt`、`production/shot_list.json`。原素材路径：`assets/raw/shot_01/01_v001.mp4`。源视频不上传到 GitHub，避免隐私问题与仓库膨胀。

## 把一个点子变成分镜（可选模型）

复制 `.env.example` 的三项 `VIDEO_LLM_*` 环境变量并在你自己的终端设置，然后执行：

```bash
video-studio draft projects/new-film \
  --idea "唐僧在女儿国一本正经拒婚，结果偷偷藏起婚书，五机位喜剧反转" \
  --preset story --title "西梁国留婚" --shots 5
video-studio plan projects/new-film
```

`draft` 使用**OpenAI-compatible Chat Completions** 接口；模型名由用户自己配置。Gemini、Qwen、其他兼容服务能否工作取决于它们实际提供的接口和权限。环境变量和密钥不会存入仓库；生成 JSON 会做结构校验，仍须人工检查逻辑、材料和台词。未配置时用 `init` 离线模板即可。

## 让 Flow 辅助填词（可选）

基础流程永远可以直接复制 `production/prompts/shot_01.txt` 到你已经登录的 Google Flow。若希望代理帮忙填入提示词，可安装：

```bash
python -m pip install -e '.[flow]'
python -m playwright install chromium
```

在**独立浏览器配置目录**启动本机 Chrome 的 CDP 调试端口，例如 `--remote-debugging-port=9222`。只在本机回环地址使用，不向公网暴露调试端口；不要使用存有个人敏感账号的常用 Chrome 配置。手动打开并登录 Flow，设置模型、画幅、生成额度后：

```bash
video-studio flow-assist projects/flower-art/production/prompts/shot_01.txt \
  --selector 'textarea'
```

这会尽力**填入**文本，但**默认不点击生成按钮**。浏览器的具体选择器随 Flow 网页更新而变，可用 `--selector` 指定验证过的输入框 CSS 选择器。若你确实要主动提交，可额外加 `--submit --button '<verified CSS selector>'`；执行前自行确认生成额度及平台规则。生成视频后，仍需你下载并用 `ingest` 导入；不会抓取隐藏下载直链或自动循环耗费额度。

## 替换中文配音

如果视频模型中文口音不准确，可用你自己的 VoxCPM / VoiceStudio / 其他 TTS 来生成台词音轨。打开 `production/voice_lines.csv`，按 `id` 生成单句音频，导入：

```bash
video-studio ingest projects/new-film --shot 01 --kind voice --line 01_01 --file /path/to/line.wav
video-studio render projects/new-film --mix-voice
# 也可以在模型/FFmpeg 支持字幕滤镜时添加 --burn-subtitles
```

每条配音按 `absolute_start` 相对于整片开始的时间混入；原声降低到 35% 音量。`mix-voice` 只是**时间轴混音**，不保证嘴型自动匹配。对每句台词请听检字音、尾字和与人物嘴部的同步；Whisper 是可选的外部核查工具，本项目目前不自动运行 Whisper 或 VoxCPM。若场景完全没有台词，直接保留自然环境音即可。

## 后期与检查

- **统一剪辑**：FFmpeg 将视频按目标时长裁切或尾帧补齐，以原比例缩放加留边（不拉伸、不强制裁掉作品），统一为 H.264 / AAC，并顺序拼接。
- **字幕**：`plan` 输出标准 SRT；`render --burn-subtitles` 要求 FFmpeg 编译带字幕滤镜 / libass，中文字体需在本机可用。字幕以计划时间轴为准，不代替 Whisper 字级对齐。
- **存档**：每次 `ingest` 产生 `v001`、`v002`；成片存在时自动生成新文件名，不覆盖原版。
- **自动质检边界**：`qa` 识别缺失镜头、无视频流、原片过短、无音频流和缺少可选配音。**目前不能识别人脸崩坏、手指畸形、工艺物理失真、真实唇形同步、字幕压住主体**；最后必须人工完整审片。

## 工程结构

```text
videostudio/       可运行 CLI、项目校验、提示词、LLM 可选适配、Flow 辅助、FFmpeg 合成
examples/          60 秒手作 / 剧情 JSON 模板
AGENTS.md          给 Codex / AI 代理的导演与复核指令
.github/workflows/ci.yml  Python 单元测试
projects/          使用中生成，已被 .gitignore 排除
```

## 开发与安全

```bash
python -m unittest discover -s tests -v
python -m videostudio --help
```

不要把 OAuth / Google Cookie / LLM Key / 原视频素材提交进仓库。不要公开 CDP 端口。机器自动化只能操作你有权使用的网页，不能绕过登录和平台付费机制。该项目暂不支持自动投放视频到小红书、抖音或视频号。

MIT License · 项目仓库：<https://github.com/mindnature/video>
