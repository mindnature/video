# Video Studio V1.5｜剪映配音工作台（Windows 优先）

## 范围与前提

剪映专业版提供“文本朗读”和多种可试听音色。此集成**不调用未公开的剪映 API、不读取本机剪映草稿内部数据库、不绕过登录，也不把剪映视为可完全自动控制的配音接口**。根据剪映客户端的版本和账号权限，部分音色、导出菜单可能不同。通过人工可见的剪映软件制作音频，再由 Video Studio 自动完成音频归档、时间点校验、混音、字幕输出和正式交付检查。

在当前 V1.5 中，**剪映内部选声、点击朗读和导出仍由用户完成**，Video Studio 只自动化可可靠验证的本地文件操作。无需 Gemini API Key，也不需要剪映 API Key。

## 一、Codex 生成可复制配音包

当项目分镜 `project.json` 有台词/旁白时，`plan` 会自动生成 `production/jianying/`；也可以随时重新生成文本清单：

```powershell
video-studio jianying-pack projects/nandu
```

输出：

- `copy_to_jianying.txt`：连续旁白文本，可直接复制到剪映，段落之间保留空行
- `line_by_line.txt`：句子 ID、计划时间和对应文稿，用于逐句生成更精细的语音
- `voice_lines.csv`：句子、说话人和在**最终剪辑时间轴**的起止时刻
- `alignment.json`：基于计划时间的可编辑模板；**不代表实际对齐完成**
- `INSTRUCTIONS.md`：可离线查看的人工操作流程

## 二、在剪映里试听与生成

1. 打开剪映专业版，进入文字／文本朗读或当前版本的“朗读”入口。将 `copy_to_jianying.txt` 粘贴进去，挑选 2–3 种音色。
2. 用《南渡》这类人文纪录片，先试听一段温暖回忆和一段克制悲伤的文字；不要用未试听过的系统默认音色直接交片。可沿用 V1.4 的试听门禁：

```powershell
video-studio voice-guide projects/nandu
video-studio voice-audition projects/nandu --warm "D:\\Audio\\warm.wav" --somber "D:\\Audio\\somber.wav" --source "剪映专业版：手动试听与导出"
video-studio voice-approve projects/nandu --note "两段对照试听后确认自然语气、气口和情绪一致"
```

3. 在剪映时间线里对齐每句话：停顿、无旁白段、环境音及句末留白均按影片结构保留。推荐把最终参考视频导入剪映作为时间标尺。
4. 优先导出**仅包含配音的 WAV**（可用 MP3/M4A/FLAC），避免把配乐、环境音一起导出导致混音重复。如当前版本没有音频单独导出选项，可先导出视频后经 FFmpeg 将其音轨抽取成 WAV。剪映界面和具体音色以实际客户端为准。

## 三、导入方式 A：完整时间线旁白（推荐）

导出一条**有正确静音空隙的整片旁白轨**，例如《南渡》80 秒，30–40 秒保留无旁白，片尾可只留江风；视频长度为 80 秒时，允许音轨在片尾留白处提前结束。

```powershell
video-studio jianying-import projects/nandu --audio "D:\\Audio\\nandu_voice.wav" --full-track
```

然后打开 `projects/nandu/production/jianying/alignment.json`，把每条 `start/end` 改为**听到的实际语音起止秒数**。本系统不会凭空猜测字音时间。所有时间是最终成片的绝对秒数，不是每个 Flow 原片的局部秒数。

人工将旁白与实际画面、字幕听查之后：

```powershell
video-studio jianying-approve projects/nandu --note "已逐句听查字音、自然停顿、无旁白渡江段、字幕起止与原片环境音"
video-studio jianying-status projects/nandu
```

这样正式 `video-studio advance` / `render` 会自动把**已审核的剪映音轨**从 0 秒混入，生成匹配的 SRT 并按 `postproduction.subtitles` 设置烧录字幕。它不会对配音声线作所谓“自动自然度评分”，也不会自动完成字级/音素级强制对齐。

修改 `alignment.json`、重新导入配音、改动已批准的分镜/剪辑范围，都会使此前的配音批准失效，需要重新听查批准。旧版旁白音频始终保留，不覆盖已有素材。

## 四、导入方式 B：逐句录制（更精细）

如果想精细控制每句的声线、语速和修订范围，可单独导出每句 WAV：

```powershell
video-studio jianying-import projects/nandu --audio "D:\\Audio\\line_01.wav" --line 01_01
video-studio jianying-import projects/nandu --audio "D:\\Audio\\line_03.wav" --line 03_01
```

该模式使用已有 `ingest --kind voice` 的版本化音轨结构，自动把音频放到原计划的每句开头；请在审片时确认时长和字幕是否合适。V1.4 的真人试听审核仍然有效。此模式没有自动字级对齐，也不会擅自平移文本时间轴。

如某一句持续时间明显超出计划片段，QA 会给出警告。建议重新导出语速更合适的语音，或在未开始 Flow 制作前调整剪辑设计，而不是自动加速变声。

## 五、与既有 Video Studio 工作流整合

`Gemini 故事与分镜 → 人工批准 → Flow 动态镜头 → 剪映声音试听与导出 → jianying-import → 时间点校准和 jianying-approve → FFmpeg 混音与字幕 → delivery-report → 人工最终审片`。

保留了原来的 Flow 额度控制、动态素材来源、镜头动作/人物一致性验收和 V1.3 连续性剪辑；剪映**只是配音来源**，不取代视频生成。没有剪映或者用户选择其他声音来源时，原 V1.4 外部音频导入和试听流程仍可用。

视频包含他人声音或音色克隆时，必须确认拥有使用权、授权范围和发布权限；不要未经许可克隆或仿冒真人声音。试听音色的使用条款也以剪映当时公布的说明为准。
