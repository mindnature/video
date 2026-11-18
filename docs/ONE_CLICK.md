# Codex 一键制片 V1.0｜用户审核版

**一次口令启动，关键节点人工审核，任务失败可恢复。**

## 第一次准备（Windows + Codex）

1. `git clone https://github.com/mindnature/video.git`，在 Codex 打开仓库，让 Codex 阅读 `.agents/skills/video-studio/SKILL.md`。
2. 安装 Python 3.10+、FFmpeg、Google Chrome；在仓库执行 `python -m pip install -e '.[flow]'`，再运行 `video-studio doctor`。
3. 在自己电脑的环境变量里设置 `GEMINI_API_KEY` 和 `GEMINI_MODEL`（必须是账号可调用的实际模型）。本项目不能直接把 Gemini 网页会员当作 API；不必把密钥提供给聊天机器人。
4. 在 PowerShell 运行 `./scripts/open_flow_chrome.ps1`，在新开的**专用 Chrome** 登录 Google Flow，手工选择 Video、画幅、单次输出数量 x1、模型。不得开放本地 9222 调试端口。
5. 复制 `examples/flow_ui.example.json` 至仓库外或者 `.gitignore` 保护的 `projects/flow-ui.local.json`。让 Codex 运行 `video-studio inspect-flow projects/电影名 --flow-config projects/flow-ui.local.json`，分析 `production/flow_browser/flow_screenshot.png` 和 `ui_probe.json`，然后填写经过实际页面验证的 CSS 输入框、生成按钮、结果卡片和下载按钮选择器。最后两项不配置时，会暂停改为人工下载；**不会假称已完成自动下载**。

## 只说一句话启动（例）

在 Codex 中说：

> 使用 $video-studio 帮我制作 9:16、60 秒的东方手作纪录片。参考我的图片。Gemini 分析真实材料，规划六个 10 秒制作镜头；Google Flow 生成每段；我只负责审核。每完成一个镜头让我看预览，最后自动拼接为 MP4。

Codex 的 CLI 步骤示例：

```powershell
video-studio start projects/flower --idea "真实花瓣逐步拼合为东方仕女" --reference "C:\Pictures\art.jpg" --title "东方花影" --preset handcraft --shots 6
# 审核 Gemini 分镜：production/storyboard.md 和 production/prompts/*.txt
video-studio approve projects/flower --stage storyboard
# 人工检查 Flow 模型、比例、生成额度后批准本轮最多 6 次提交
video-studio approve projects/flower --stage credits --max-generations 6
# 提交一镜，等待输出或人工下载
video-studio advance projects/flower --flow-config projects/flow-ui.local.json
# 如果没有自动下载，在 Flow 点下载后：
video-studio receive projects/flower --shot 01 --file "C:\Downloads\scene_01.mp4"
# 浏览候选片段与 contact sheet，满意才批准
video-studio approve projects/flower --stage shot --shot 01
# Codex 自动重复 advance→用户选镜头→approve，直到生成 6 个镜头
# 全部通过后 advance 自动合成 exports/final_master.mp4
video-studio advance projects/flower --flow-config projects/flow-ui.local.json
video-studio approve projects/flower --stage final
```

## 四处审核（必需）

- **分镜**：确认剧本、工序和机位。可以手工修改 `project.json`，执行 `replan` 后重新批准。
- **额度**：明确本次最多允许几次 Flow 提交。重复生成需要再次授权，系统不自动猜额度。
- **每镜头**：下载的原片必须可通过 ffprobe，人工判断人物/手部/物理工艺/衔接；不满意可以拒绝并重新授权生成。
- **成片**：FFmpeg 自动拼接后完整观看，满意再标记完成。

## 中断恢复

执行 `video-studio status projects/flower` 查看当前阶段。再次执行对应命令即可继续。

如果在 Flow 提交后网络出错，状态为 `generation_uncertain`，**先检查 Flow 是否实际生成**：

```powershell
video-studio resolve projects/flower --shot 03 --action download
video-studio receive projects/flower --shot 03 --file "C:\Downloads\shot_03.mp4"
```

确认没有可用片段，才可以用 `--action retry`，并明确重新授权额度。已经完成的视频和旧版本全部保留，不会重做之前审核通过的镜头。

## 已经实现的范围与边界

- ✅ Gemini API 可接收创意及 JPG/PNG/WebP 参考图，生成分镜 JSON、镜头提示词。
- ✅ Codex Skill 能驱动项目状态推进、审核暂停、素材版本归档、音频与后期处理。
- ✅ Playwright 通过专用已登录 Chrome 的本地 CDP，按用户确认的 DOM 选择器逐镜提交；支持识别新结果卡片并尝试以网站正常下载动作保存视频。
- ✅ 自动验证下载视频流，生成预览接触表，FFmpeg 合成，并需人工最终审片。
- ⚠️ Flow 是动态网页，**浏览器选择器和下载机制需要用户实际登录后校准**；无当前账号会话无法承诺全链路自动下载成功。
- ⚠️ Gemini API 可能按量计费，Flow 生成消耗对应账号额度。没有使用任何非公开 Google API、绕过登录或机器人检测的方法。
- ⚠️ 语音克隆、Whisper 词级对齐、自动检测材料失真尚未作为本阶段的全自动功能交付。Google Flow 影片生成的可选时长以当前页面为准。
