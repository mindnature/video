# Video Studio V1.1 — Codex Gemini + Flow 双网页一键制片（带人工审核）

**一句创意 / 一张参考图 → Gemini 分镜 → 人工审核 → Google Flow 浏览器逐镜生成 → 镜头审核 → FFmpeg 合成 → 成片审核。**

[**中文操作说明：docs/ONE_CLICK.md**](docs/ONE_CLICK.md) · [Codex Skill](.agents/skills/video-studio/SKILL.md)

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

## 常用命令

```powershell
# 默认 Gemini 网页通过已登录 Chrome 自动生成六镜头分镜（不扣 Flow 额度）
video-studio start projects/flower --idea "真实花瓣做东方仕女手工画" --title "东方花影" --reference "C:\Pictures\art.jpg" --gemini-config projects/gemini-ui.local.json
video-studio status projects/flower

# 人工审阅分镜；修改 project.json 后需 replan 再批准
video-studio approve projects/flower --stage storyboard
video-studio approve projects/flower --stage credits --max-generations 6

# 每次最多提交一镜。正常自动下载或暂停等待手动下载
video-studio advance projects/flower --flow-config projects/flow-ui.local.json
video-studio receive projects/flower --shot 01 --file "C:\Downloads\scene_01.mp4"
video-studio approve projects/flower --stage shot --shot 01
# 重复 advance 和逐镜审批。所有镜头审核后 advance 自动合成
video-studio approve projects/flower --stage final
```

如果不使用 Gemini 网页，可选用旧的离线 `init` / `gemini-brief` / `plan` / `flow-pack` 流程，或者 `start --provider template` 创建预设分镜，再手工修订 `project.json` / `replan`。这并不等同于 Gemini 自动创作。

## 主要工程能力

- **Codex 原生 Skill**：`.agents/skills/video-studio/SKILL.md` 提供一条指令启动与审核后的恢复路径。
- **Gemini 导演**：默认用已登录的 Chrome Gemini 网页提交创意/参考图、提取可见文本、校验 JSON 分镜；Gemini API 可选，非必需。
- **Flow 浏览器适配**：只连接本机专用 Chrome 的 CDP，使用浏览器可见的输入框、按钮及下载菜单；不使用非公开 API、隐藏资源链接或绕过登录。提供 `inspect-flow` 截图与选择器校准；网页改版后必须更新选择器。
- **人工审核和预算防护**：分镜、扣费额度、每镜候选片段、成片均设审核关口；所有生成操作上限显式批准，故障不自动重试。
- **断点恢复/版本留存**：`run_state.json` 记录每镜状态、尝试次数、审核与资产哈希；旧视频保留，渲染只使用审核通过的具体版本。
- **后期与 QA**：生成缩略接触表、ffprobe 基础检查、视频比例与帧率统一、SRT 导出、可选配音混音、FFmpeg 拼接。真实性/手部/声音/字幕视觉审核仍由人完成。

## 旧版 CLI 兼容

`init`, `draft`, `plan`, `gemini-brief`, `flow-pack`, `flow-assist`, `ingest`, `qa`, `render`, `doctor` 保持可用；新的 `start`, `status`, `approve`, `advance`, `receive`, `reject`, `resolve`, `replan`, `inspect-flow` 提供有审核节点的流程。

## 安全

不要提交密钥、Chrome 登录信息、原始图片、项目视频、浏览器截图或本机选择器配置到 GitHub；`projects/` 已加入 `.gitignore`。不要开放 Chrome CDP 端口。Flow 每镜头单次提交可能扣除额度，不保证自动生成成功。不支持绕过 Flow 安全检查、付费、验证码或发布到短视频平台。

**状态：V1.1 双网页驱动 beta。** 自动化逻辑和模拟环境单元测试通过，但必须在你的真实 Google Flow 会话中完成端到端验证；浏览器 UI 依赖项不能在无账号登录环境中代替验证。

MIT License · [项目仓库](https://github.com/mindnature/video) · [Google Flow 官方帮助](https://support.google.com/flow/answer/16353334) · [Codex Skill 文档](https://developers.openai.com/api/reference/cli)


## V1.1 双网页默认模式

Google Gemini 网页和 Google Flow 使用同一个本地专用 Chrome 配置文件，**默认无需 Gemini API 密钥**。
使用 `inspect-gemini` 校准分镜输入/输出，用 `inspect-flow` 校准镜头生成；Gemini 失败时 `receive-gemini` 可手动导入有效 JSON，`resolve-gemini --action retry` 必须由用户明确授权。详细步骤以 [V1.1 中文说明](docs/ONE_CLICK.md) 为准。
