# Video Studio V1.3 — 剧本优先 · 连续性导演 · 可审核剪辑（Codex + Gemini + Flow）

**一句创意/参考图 → Gemini 故事圣经 → 人审 → Gemini 分镜 → 独立导演复核 → 人审 → Flow 逐镜生成 → 单镜及相邻镜头联审 → FFmpeg 按实际入出点剪辑 → 成片审核。**

[**V1.3 导演流程：docs/DIRECTOR_V13.md**](docs/DIRECTOR_V13.md) · [入门：docs/ONE_CLICK.md](docs/ONE_CLICK.md) · [Codex Skill](.agents/skills/video-studio/SKILL.md)

> 这是本地优先、可恢复的自动制片工作流。**一键表示只需要在 Codex 发起制作，审核节点仍由人决定**，不是绕过网站登录、付费额度或无需人工审核的无人值守服务。默认仅需 Chrome 中登录 Gemini 与 Google Flow，不需要 Gemini API Key；首次需校准两个网站的选择器。没有实时登录的 Flow 页面无法事先验证这些选择器是否仍适用。

## 5 分钟理解

1. 用户在 Codex 说出创意并提供参考图，Codex 调用 `video-studio start`；Gemini 网页通过可见页面生成结构化分镜。
2. 用户批准 `storyboard` 后，在 Google Flow 选择模型、9:16 或 16:9、输出数量，并明确批准最多 N 次生成额度。
3. Codex 调用 `video-studio advance` 逐镜提交。浏览器结果正常下载后自动导入，否则状态暂停等待你从 Flow 下载文件再导入。用户逐镜观看并通过或退回。
4. 全部镜头批准后，`advance` 检查媒体并使用 FFmpeg 生成 MP4。用户观看成片并最终批准。
5. 每次状态都保存在 `production/run_state.json`。中断可用 `video-studio status` 恢复，已提交但结果不确定时**绝不自动再次扣费**。

## 安装

```powershell
git clone https://github.com/mindnature/video.git
cd video
python -m pip install -e '.[flow]'
video-studio doctor
./scripts/open_flow_chrome.ps1
```

还需单独安装 Python 3.10+、FFmpeg、Google Chrome，无需默认设置 API Key。专用 Chrome 打开后，登录 Gemini 和 Google Flow，选择 Video 模式及合适模型/画幅。配置 Gemini 与 Flow 选择器详见 [中文操作说明](docs/ONE_CLICK.md)。

## 常用命令（V1.3 默认 Gemini 网页）

```powershell
# 1. Gemini 先输出故事圣经；此时还没有提交 Flow
video-studio start projects/film --idea "一场有因果与情绪变化的神话短片" --preset story --shots 5 --title "月下空庭" --gemini-config projects/gemini-ui.local.json

# 2. 用户确认完整故事后，再生成正式分镜
video-studio approve projects/film --stage story
video-studio advance projects/film --gemini-config projects/gemini-ui.local.json

# 3. Gemini 独立导演复核，无阻断问题后再审核分镜和预算
video-studio director-review projects/film --gemini-config projects/gemini-ui.local.json
video-studio approve projects/film --stage storyboard
video-studio approve projects/film --stage credits --max-generations 5

# 4. 每次只让 Flow 生成一镜，必须检查真实结果
video-studio advance projects/film --flow-config projects/flow-ui.local.json
video-studio verify-shot projects/film --shot 01 --result pass --note "看过完整成片，主体与声音都正确"
video-studio approve projects/film --stage shot --shot 01

# 5. 第二镜起检查相邻两镜的真实剪接预览
video-studio advance projects/film --flow-config projects/flow-ui.local.json
video-studio verify-shot projects/film --shot 02 --result pass --note "本镜单独合格"
video-studio verify-seam projects/film --left 01 --right 02 --result pass --note "实际看过衔接，动作/视线/声音自然"
video-studio approve projects/film --stage shot --shot 02
# 后续重复；最后 advance 合成，再人工批准 final
```

若自动下载不成功，先在 Flow 网页下载，再运行 `receive` 导入相应镜头。真实浏览器提交失败不能自动重试。原有 V1.2 快速路径可以在 `start` 后加 `--quick-storyboard`，原项目也不受影响。详情：[V1.3 导演说明](docs/DIRECTOR_V13.md)。

## 主要工程能力

- **Codex 原生 Skill**：`.agents/skills/video-studio/SKILL.md` 提供一条指令启动与审核后的恢复路径。
- **Gemini 导演**：默认用已登录的 Chrome Gemini 网页提交创意/参考图、提取可见文本、校验 JSON 分镜；Gemini API 可选，非必需。
- **Flow 浏览器适配**：只连接本机专用 Chrome 的 CDP，使用浏览器可见的输入框、按钮及下载菜单；不使用非公开 API、隐藏资源链接或绕过登录。提供 `inspect-flow` 截图与选择器校准；网页改版后必须更新选择器。
- **人工审核和预算防护**：分镜、扣费额度、每镜候选片段、成片均设审核关口；所有生成操作上限显式批准，故障不自动重试。
- **断点恢复/版本留存**：`run_state.json` 记录每镜状态、尝试次数、审核与资产哈希；旧视频保留，渲染只使用审核通过的具体版本。
- **后期与 QA**：生成含后期风格的审片版及首/中/尾关键帧、ffprobe 基础检查、视频比例与帧率统一、SRT 导出、按项目配置自动合成配音、拟音、字幕、可选监控/复古/电影后期、FFmpeg 拼接。真实性/手部/声音/字幕视觉审核仍由人完成。

## 旧版 CLI 兼容

`init`, `draft`, `plan`, `gemini-brief`, `flow-pack`, `flow-assist`, `ingest`, `qa`, `render`, `doctor` 保持可用；新的 `start`, `status`, `approve`, `advance`, `receive`, `reject`, `resolve`, `replan`, `inspect-flow` 提供有审核节点的流程。

## 安全

不要提交密钥、Chrome 登录信息、原始图片、项目视频、浏览器截图或本机选择器配置到 GitHub；`projects/` 已加入 `.gitignore`。不要开放 Chrome CDP 端口。Flow 每镜头单次提交可能扣除额度，不保证自动生成成功。不支持绕过 Flow 安全检查、付费、验证码或发布到短视频平台。

**状态：V1.2 通用制片质量控制 beta。** 自动化逻辑和模拟环境单元测试通过，但必须在你的真实 Google Flow 会话中完成端到端验证；浏览器 UI 依赖项不能在无账号登录环境中代替验证。

MIT License · [项目仓库](https://github.com/mindnature/video) · [Google Flow 官方帮助](https://support.google.com/flow/answer/16353334) · [Codex Skill 文档](https://developers.openai.com/api/reference/cli)


## V1.1 双网页默认模式

Google Gemini 网页和 Google Flow 使用同一个本地专用 Chrome 配置文件，**默认无需 Gemini API 密钥**。
使用 `inspect-gemini` 校准分镜输入/输出，用 `inspect-flow` 校准镜头生成；Gemini 失败时 `receive-gemini` 可手动导入有效 JSON，`resolve-gemini --action retry` 必须由用户明确授权。详细步骤以 [V1.1 中文说明](docs/ONE_CLICK.md) 为准。

## V1.2｜通用制片质量闭环（2026-11）

保留 V1.1 的 Codex / Chrome Gemini / Chrome Flow、人审和断点恢复；本版修复 **全剧角色混入单镜、硬编码人数限制、缺少风格化后期、自动成片不使用配音/字幕** 等问题。

- 新增第三种 `general` 通用模式：人物剧情、产品展示、旅行短片、风景等不必套用古装喜剧或手工模板。`handcraft`/`story` 保留，旧项目仍可读取。
- 全局 `characters` 和 `subjects` 只描述**跨镜身份外观**。在每个 `shot.cast`（人物）和 `shot.subject_ids`（产品、道具）中显式列出当前镜头需要的实体；提示词不会再自动展开全体角色。永久站位动作写在身份描述中会产生阻断错误。
- 每镜可配置 `acceptance`（`start_visible`、`end_visible`、`end_absent`、`required_events`、`audio_checks`），在 `plan_audit.json` 检查明显冲突和动作密度。密度检查属于预警，不代表模型一定拍不好。
- `postproduction.style` 可为 `clean`、`surveillance`、`vintage`、`cinematic`。仅选择 `surveillance` 才在 **FFmpeg 渲染** 阶段加入低帧率感、低清、噪点、REC/CAM 标识和按帧递增的时码；普通影片不受影响。**不要**要求 Flow 在原片内生成这些字。
- `postproduction.voice`/`subtitles` 设为 `auto`（默认）、`on` 或 `off`；在自动 `advance` 的最终输出中执行相同配置。`voice=on` 且缺必要配音会阻止最终通过 QA；`auto` 使用已有配音，否则保留原片人声。`subtitles=auto` 对有台词的项目自动烧录计划 SRT。
- `shot.sound_events` 可指定本地拟音文件及计划触发秒数。时间位置是**预设音轨时间**，不是已经验证的画面接触时刻。`qa` 会检查文件及配音时长差异，但嘴型、敲击接触点、实际台词开合仍必须人工听看核对。
- 收到候选后导出 `production/review/shot_XX_*_review.mp4`（包含已指定的后期效果），以及 **first/middle/end** 三张抽帧。带 `acceptance` 或风格化效果的镜头必须经 `verify-shot` 明确记录人审结果后，才能 `approve --stage shot`。当特殊风格审片版无法生成时，不得直接按原片通过。

### 通用新项目与分镜审核

```bash
video-studio start projects/my-film --idea "展示一款便携水杯的开箱、结构和使用" --preset general --shots 4 --title "便携水杯" --provider gemini-web
# Gemini 网页必须按需设置 cast/subject_ids、acceptance 和 postproduction
video-studio plan projects/my-film
# 先检查 production/plan_audit.json，解决 ERROR 后才能批准分镜
video-studio approve projects/my-film --stage storyboard
video-studio approve projects/my-film --stage credits --max-generations 4
video-studio advance projects/my-film --flow-config projects/flow_ui.local.json
# 下载或导入素材后，完整观看带风格包装的镜头审片版，逐镜判断首尾状态和声音
video-studio verify-shot projects/my-film --shot 01 --result pass --note "已看完整审片版和尾帧，动作、主体及声音符合要求"
video-studio approve projects/my-film --stage shot --shot 01
# 每镜重复 advance/verify-shot/approve，最后输出完成后再人工审片
```

如果只是手动导入素材，也可使用 `video-studio render projects/my-film`，新版本自动参考 `postproduction` 配置。若要明确跳过，可用 `--no-voice` / `--no-subtitles`；严格要求保留对白字幕时使用项目中的 `on`，而不是依赖原片随机声轨。

[完整字段及验收示例](docs/QUALITY_V12.md) · 本项目不会宣称 FFmpeg 或静态抽帧能够自动识别人脸错位、人物走位和音画同步。实际 Google Flow Chrome 界面的端到端自动化仍须在账号上联调。


## V1.3 — Story-first director & continuity editing

- **真正的两阶段 Gemini 网页导演**：默认 `start` 首先只生成 `production/story_bible.json`，批准 `--stage story` 后再次生成分镜（旧路径 `--quick-storyboard` 仍可用）。镜头里增加叙事目的、景别、情绪、节拍映射与连续性入出状态。
- **独立导演复核**：`director-review PROJECT --gemini-config PATH` 让 Gemini 独立审故事/镜头/动作和剪接，存在阻断问题或分镜之后改变时不允许 `approve storyboard`。
- **可执行剪辑时间轴**：新增每镜 `edit.source_in/source_out`；FFmpeg 支持短片段裁取、硬切和实际音视频叠化，不再按生成视频时长机械取满。`match_action`、`match_eyeline` 等为拍摄与审核意图，不能靠代码自动保证。
- **相邻镜头联审**：为第二镜及以后自动生成已批准上一镜+本镜候选的真实剪接预览；严格连续性模式下须 `verify-seam` 审核通过后才能 `approve shot`。
- **可选尾帧参考**：`continuity.reference_previous_end=true` 时，从已批准素材中截出上一镜的实际出点参考帧，供配置好的 Flow 上传控件使用；仍须审核浏览器登录和生成额度。
- **旧项目兼容**：未填写故事圣经、连续性与剪辑字段的项目沿用 V1.2 规则，不会因为升级而修改已生成视频或自动重拍。

完整字段、命令与限制：[docs/DIRECTOR_V13.md](docs/DIRECTOR_V13.md)。V1.3 有本地测试覆盖，但还未在你的实际 Google Flow 网页完成真实端到端浏览器验证。
