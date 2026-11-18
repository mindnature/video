# Video Studio V1.3｜剧本优先 · 跨镜头连续性 · 导演剪辑

## 目标与边界

这版不是增加一套“嫦娥奔月专用提示词”。它将适用于人物短片、产品展示、自然纪录片、东方手工纪录片的**通用导演工作流**落实为代码：

**创意 → 故事圣经（人工审核）→ 分镜与剪辑计划 → 独立 Gemini 导演复核（人工审阅）→ 分镜批准 → Flow 逐镜生成（额度审批）→ 单镜审核 + 相邻镜头联审 → FFmpeg 按有效片段剪辑 → 成片审核。**

已有 V1.2 项目可正常读取。不会无条件用古装、三幕剧、固定机位或花瓣制作步骤代替你的创作要求。真实 Google Flow 账号/网页仍需现场校准；这些单元测试并不代替在线端到端验证。

## Codex 一句话启动

```powershell
cd D:\AI\video
# 首次或更新后：
python -m pip install -e ".[flow]"
video-studio doctor

# 新项目；Gemini 网页登录无需 API Key，先写剧本，不会直接生成 Flow 视频
video-studio start projects/moon-film --idea "以嫦娥奔月为题材，突出离别、升空与对望的因果和情感" --preset story --title "月下空庭" --shots 5 --gemini-config projects/gemini-ui.local.json
```

上面只是示例题材，项目本身不限制题材、长度或风格。`--preset general` 适用于产品/旅行/自然；`handcraft` 适用于材料工艺记录。

默认 V1.3 **必须**走两个生成阶段（仅 `gemini-web` 一键路径）。若只想用 V1.2 快速模式，显式添加 `--quick-storyboard`；旧 API/`init` 项目也保持兼容。

### 阶段一：故事圣经

`start` 调用已登录 Chrome 内的 Gemini 生成 `production/story_bible.json`。这时还**没有**生成分镜、更不会扣 Flow 额度。

故事圣经包括核心概念、创作目标、观众钩子、起因、推进、转折、结局、情感曲线，以及每个故事节拍的原因与影响。手工/产品类可用过程和认知变化代替戏剧冲突，不强制走传统三幕剧。

确认后执行：

```powershell
video-studio approve projects/moon-film --stage story
video-studio advance projects/moon-film --gemini-config projects/gemini-ui.local.json
```

若故事有问题，可修改 `production/story_bible.json` 后再审核；批准时会记录哈希，批准后改动将阻止进入下一阶段。

### 阶段二：分镜与剪接方案

Gemini 严格基于批准的故事圣经，返回 `project.json`，各镜头指定：

- `story_beat_ids`：对应已批准故事的哪个因果节拍
- `narrative_purpose`、`emotional_state`：该镜要传达的事件和情绪
- `framing`、`coverage_type`：全景/中景/反应/细节及主体可见范围
- `continuity.entry`、`continuity.exit`：进入和结束时的空间、道具、动作、视线、运动方向等
- `continuity.link_from_previous`：从前一镜到本镜为什么可以切，或为什么要明确跳切
- `edit.source_in`、`edit.source_out`：实际成片使用的片段起止秒数（**不等于 Flow 的生成时长**）
- `edit.transition`、`edit.transition_seconds`：切法和对应的叠化时长
- 旧的 `cast`、`subject_ids`、`acceptance`、`beats`、`sound_events`、`dialogue` 等继续保留

文件：`production/storyboard.md`、`story_bible.md`、`plan_audit.json`、`continuity_audit.json`、`edit_timeline.json`、`cut_review.md`。

**独立导演复核：**

```powershell
video-studio director-review projects/moon-film --gemini-config projects/gemini-ui.local.json
```

Gemini 将在一次独立的新对话中，专门挑剔故事因果、面部反应、景别、相邻镜头进出状态、剪接点和模型难点。生成 `production/director_review.json`。如果报告存在阻断级问题，修改 `project.json` 并执行 `replan`、重新复核。报告是计划审查，不是已经看过真实视频的证明。

完成审核后：

```powershell
video-studio approve projects/moon-film --stage storyboard
video-studio approve projects/moon-film --stage credits --max-generations 5
```

网页超时并不意味着没发送成功：使用 `status` 查看状态，检查 Gemini 网页后通过 `receive-gemini` / `receive-director-review` 导入复制的有效 JSON，或在确认后显式运行相应的 `resolve-... --action retry`。**不会因为超时自动重发，也不会擅自批准阶段。**

## 原视频时长不等于剪入时长

假设 Flow 为一镜生成 8 秒，但是实际剧情只有 3 秒值得保留：

```json
{
  "duration": 8,
  "edit": {
    "source_in": 2.0,
    "source_out": 5.0,
    "transition": "cut",
    "transition_seconds": 0,
    "edit_intent": "只保留人物发现变化、转头看向同伴的连续反应"
  }
}
```

此镜在最终成片中实际使用 **3 秒**。如果与前一镜衔接的是 `dissolve` 且 `transition_seconds=0.4`，时间轴会再减去这 0.4 秒交叠。`edit_timeline.json` 保存实际时间位置。台词/SRT 和拟音按剪接时间轴重新计算，裁掉范围外的事件不会混入。

支持的切法：

| `transition` | 处理方法 |
|---|---|
| `cut` | 直接硬切 |
| `dissolve` | FFmpeg 对画面和音频进行实际叠化 |
| `match_action` | **剪辑意图**：硬切，须由分镜和素材保证动作方向/位置匹配 |
| `match_eyeline` | **剪辑意图**：硬切，须由真实画面保证视线匹配 |
| `sound_bridge` | **剪辑意图**：硬切，音效/台词需另行在时间轴布置；没有神奇的自动画外音同步 |

`match_action`、`match_eyeline`、`sound_bridge` 并非 FFmpeg 能自动生成匹配内容的特效。若画面不连续，必须调整剪接点或退回 Flow 重新生成。**淡入淡出不能掩盖演员脸部、动作、位置不一致。**

## 相邻镜头联审（V1.3 核心）

首镜通过之后，第二镜收到视频时，系统使用上一镜**已经批准的具体版本**与新候选生成真实两镜预览，并输出前后约四秒的边界片段：

`production/review/seams/seam_01_02_...mp4`

审核人应当完整观看这一段，明确检查场景地理、人物身份/服饰、前镜出画和后镜入画方向、动作/视线、道具状态、音效与字幕以及情绪过渡。

```powershell
video-studio verify-shot projects/moon-film --shot 02 --result pass --note "单镜动作、脸部、字幕已核查"
video-studio verify-seam projects/moon-film --left 01 --right 02 --result pass --note "两镜间的动作、视线和环境声连续，剪接点自然"
video-studio approve projects/moon-film --stage shot --shot 02
```

V1.3 的严格连续性项目中，如果未产生真实联审视频、未完成 `verify-seam`、审核为 fail，或候选视频被换了版本，都不能批准该镜。**机器仅生成剪接预览，人负责视觉语义判断**。这是人工审核，不是虚构自动视觉识别。

必要时下一镜设置：

```json
"continuity": {"entry": {"location": "同一庭院"}, "exit": {"location": "庭院出口"},
                "link_from_previous": "沿上一镜视线接入", "reference_previous_end": true}
```

系统会从已批准的上一镜真实视频、指定剪出点附近提取 PNG 参考帧；之后由本地 Flow 浏览器按经确认的上传控件提交。没有实际已批准的前镜素材或上传控件不确定时，暂停并报告，不假装接续已成功。图片参考是辅助而不是一致性保证。

## 最后合成和复核

全部镜头分别通过单镜与相邻镜头验收后，`advance` 才会执行实际剪辑和 FFmpeg 合成；输出 MP4 后仍须你观看全片并 `approve --stage final`。自动媒体 QC 可以检查时长、音轨、丢失素材、声明状态冲突，但**不能独立判断演员是不是同一个人、故事够不够动人、真实口型是否完全吻合**。

旧 V1.2 本地项目、`init`、`render`、`qa`、`plan`、配音字幕后期、Flow 额度审批和素材留档均保持兼容。不要直接覆盖含已生成素材的旧项目；建议另建新的 V1.3 测试项目，历史版本可随时回看。
