# Video Studio V1.2｜双网页一键制片与通用质量验收

**默认无需 Gemini API Key。** 用户通过专用 Chrome 分别登录 [Gemini](https://gemini.google.com/app) 与 [Google Flow](https://labs.google/fx/tools/flow)，Codex 负责自动提交分镜与镜头、素材管理、审核节点和 FFmpeg 后期。

> 一键的含义：用一个 `start` 口令启动计划，之后在**分镜、Flow 额度、每镜头、最终成片**节点由用户审核。首次安装与两种网页的 UI 选择器校准不可省略。网页变更可能导致自动化停止；不能保证所有账号均可自动操作或下载。

## 1. 一次性安装（Windows）

```powershell
git clone https://github.com/mindnature/video.git
cd video
python -m pip install -e '.[flow]'
video-studio doctor
./scripts/open_flow_chrome.ps1
```

另需安装 Python 3.10+、FFmpeg、Google Chrome。在启动的专用 Chrome 中**人工登录 Gemini 和 Google Flow**；不要交出账号密码，不要用有敏感资料的常用 Chrome 配置，不要开放 `127.0.0.1:9222` 调试端口。

## 2. 首次校准两个网页

为防止操作错误按钮，不预设未经验证的 CSS 选择器。在项目根目录执行：

```powershell
New-Item -ItemType Directory -Force projects | Out-Null
Copy-Item examples/gemini_ui.example.json projects/gemini-ui.local.json
Copy-Item examples/flow_ui.example.json projects/flow-ui.local.json
video-studio inspect-gemini projects/flower --gemini-config projects/gemini-ui.local.json
```

让 Codex 查看 `projects/flower/production/gemini_browser/gemini_screenshot.png` 和 `ui_probe.json`，依据**真实界面**填入 Gemini 的 `prompt_selector`、`send_button_selector`、`response_selector`。若需要由自动化上传图片，填写 `reference_file_input_selector`；否则先在 Gemini 网页手动上传并确认 `manual_references_loaded: true`。如需每次新建会话，可配置 `new_chat_button_selector`。无网络权限、登录过期或 CSS 不稳定时，停下来让人校准；不要猜测按钮位置。

运行 `video-studio start` 创建项目后，同样使用 `video-studio inspect-flow projects/flower --flow-config projects/flow-ui.local.json` 查看截图和选择器数量；配置 `prompt_selector`、`generate_button_selector`；可选配置结果卡片和下载选择器。Flow 自动提交之前会检查选择器与参考图片状态。`projects/` 被 Git 忽略，截图/选择器不上传 GitHub。

## 3. 一句话启动

```powershell
video-studio start projects/flower --idea "用真实花瓣和叶片制作东方仕女手工画，六镜纪录片" --title "东方花影" --preset handcraft --shots 6 --reference "C:\Pictures\art.jpg" --gemini-config projects/gemini-ui.local.json
```

这一步只会通过 Gemini 网页生成分镜，**不会扣 Flow 视频生成额度**。成功输出 `production/storyboard.md` 和 `production/prompts/shot_*.txt`，然后停在 `awaiting_storyboard_approval`。有多个参考图可多次传入 `--reference`。

人工审核分镜，不满意可编辑 `project.json` 并运行 `video-studio replan projects/flower`，满意才继续：

```powershell
video-studio approve projects/flower --stage storyboard
# 检查 Flow 账号、画幅、模型与预计消耗，明确同意最多提交 6 次
video-studio approve projects/flower --stage credits --max-generations 6
# 每次最多提交一个镜头，随后暂停审核/下载
video-studio advance projects/flower --flow-config projects/flow-ui.local.json
```

若自动下载失败，用户在 Flow 通过可见下载按钮保存真实视频，再运行：

```powershell
video-studio receive projects/flower --shot 01 --file "C:\Downloads\scene_01.mp4"
video-studio approve projects/flower --stage shot --shot 01
```

继续执行 `advance → 审核 → approve shot`。全部镜头批准后，`advance` 自动 FFmpeg 合成 `exports/final_master.mp4`，观看后运行：

```powershell
video-studio approve projects/flower --stage final
```

## 4. Gemini 页面异常如何恢复？

`video-studio status projects/flower` 显示当前状态。如果 Gemini **尚未点击提交**（校准失败），会处于 `gemini_ready`，更新选择器后运行：

```powershell
video-studio advance projects/flower --gemini-config projects/gemini-ui.local.json
```

如果**可能已提交**但页面超时/回复不是合法 JSON，状态为 `gemini_submission_uncertain`。先在 Gemini 页面检查实际回复。可将网页完整 JSON 正文另存为本地 `storyboard.json`，手动导入而不重发：

```powershell
video-studio receive-gemini projects/flower --file "C:\Downloads\storyboard.json"
```

只有确认需要重新提交，才能**人工明确批准**：

```powershell
video-studio resolve-gemini projects/flower --action retry
video-studio advance projects/flower --gemini-config projects/gemini-ui.local.json
```

Flow 提交后若不确定是否扣费，不得自动重试：检查 Flow，再使用 `resolve --shot ... --action download`，或用户确认后 `retry`。所有原片版本保留。

## 5. 备用模式

- **Gemini API**：`video-studio start ... --provider gemini`；需要 `GEMINI_API_KEY` 与 `GEMINI_MODEL`，这是可选通道，非默认。
- **纯离线模板**：`video-studio start ... --provider template`；无需 Gemini，但只输出通用分镜，需手工修订。
- **原有手动流程**：`init` / `plan` / `flow-pack` / `ingest` / `render` 仍可使用。

## 6. 已实现与仍待实测的边界

- 已实现：本地 Chrome CDP Gemini 网页填写、发送、读取可见回复、JSON 严格校验、独立人工审核、出错后可恢复；Flow 尝试提交、可见菜单下载、视频归档/接触表、FFmpeg 合成。
- 仍需在你真实账号验证：Gemini 和 Flow 的网页选择器、Gemini 图片上传控件、Flow 结果下载结构、账号额度和可选生成时长。网站版并非稳定 API，官方未保证第三方 DOM 自动化兼容。
- 已登录 Chrome 不等于无限授权或可跳过 Google 登录验证；所有额度操作需要明确预算审批。项目不读取 Cookie，不调用非公开网站接口，不绕过验证码、风控或付费要求。

**成功判定**：只有实际下载的镜头媒体通过 ffprobe、用户逐镜审核、完整合成并最终批准后，才能声称视频已完成。


### V1.2 必须执行的验收步骤

新版本分镜文件 `production/plan_audit.json` 会自动检查人物作用域、身份与动作的冲突、结束画面矛盾和动作密度。只有 `ERROR=0` 才可批准分镜。

每个生成素材会尝试导出 `production/review/shot_XX_*_review.mp4`，含所需监控/怀旧/电影风格，以及按项目配置的配音和字幕。请看完整片段，不能只查看抽帧。对于带 `acceptance` 或需要风格包装的镜头，先输入：

```bash
video-studio verify-shot projects/<slug> --shot 01 --result pass --note "完整观看，确认主体、结尾、音画及风格满足要求"
video-studio approve projects/<slug> --stage shot --shot 01
```

不要在未看过真实生成素材时执行 `verify-shot`。更详细说明见 `docs/QUALITY_V12.md`。
