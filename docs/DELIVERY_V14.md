# Video Studio V1.4｜正式交付真实性与声音导演

## 制片目标

Codex 一条指令发起，Chrome Gemini 编剧/导演、Google Flow 生成真实动态视频、FFmpeg 剪辑；人工审核仍然存在。V1.4 **不新增任何未实现的视频生成模型，也不假称系统已经看懂画面动作**。这次只升级交付契约、可核实的来源/额度账本、自然旁白试听、角色跨镜复核，以及 Gemini 导演复审止损。

## 1. 先声明交付类型

在新项目开始时：

```powershell
video-studio start projects/nandu-new --idea "李清照南渡，具有表演动作的真实动态短片" --preset story --shots 8 --title "南渡" --delivery flow_dynamic --gemini-config projects/gemini-ui.local.json
```

新 CLI 默认 `flow_dynamic`，只有三种合法类型：

- `flow_dynamic`：正式 Google Flow 动态影片；逐镜保留 Flow 来源证据，且由真人明确验收**主体真实运动**。单张图片的 Ken Burns 推拉不等于人物运动。
- `animatic`：脚本节奏预演，允许静帧、文字分镜、模拟配音；**输出必须明确标记“预演”，不能称为正式 Flow 动态成片**。
- `mixed_media`：明确允许混合图像、动态片段的作品。不可伪称所有镜头均由 Flow 生成。

这些规则只会对明确使用 V1.4 `delivery` 的项目强制执行；旧的 V1.3 项目不会被升级脚本悄悄覆盖。受严格审核的影片须走 `advance` 正式流程，直接使用 `render` 生成技术 MP4 不能替代最终 `approve --stage final` 证据检查。

## 2. 生成次数对账

保持 V1.3 的权限机制：

```powershell
video-studio approve projects/nandu-new --stage credits --max-generations 8
video-studio advance projects/nandu-new --flow-config projects/flow-ui.local.json
video-studio delivery-report projects/nandu-new
```

`production/delivery_report.json` 记录：

- `authorized`：人工明确增加过的总次数上限；
- `reserved_possible_spend`：每次实际尝试提交前预留的次数；
- `visible_clicks_observed`：本地 Playwright 成功点击后返回的记录，仅能证明观察到浏览器点击，**不能证明 Google 已实际扣除额度**；
- `clicks_without_observable_receipt`：未被观察到成功点击的预留次数，可能因为错误或中断；不能擅自认为未扣费。

发现超额、事件不对账时，自动阻断正式交付。发生 UI 超时后，仍需手动检查 Google Flow 的网页历史再决定是否重试；程序不会自动提交第九次。

## 3. 素材来源与动态表演

Flow 浏览器自动下载的候选镜头会记录 `origin=flow_browser`、文件路径和 SHA-256。**手动下载**的镜头必须由实际操作的人确认来源：

```powershell
video-studio receive projects/nandu-new --shot 01 --file "D:\\Downloads\\shot_01.mp4" --from-flow
```

未加 `--from-flow` 的外部文件会如实记录成 `other`，不得在正式 Flow 动态影片中按 Flow 来源通过。手动来源记录为 `operator_attested_flow`，是操作员证言，**不是可查询的 Google 官方生成证明**。

查看真实动态镜头及带后期效果的审片版以后：

```powershell
video-studio verify-shot projects/nandu-new --shot 01 --result pass --motion pass --identity pass --note "已看完完整原片：李清照低头、触纸、箱盖转动；服饰年龄与前一镜一致"
video-studio approve projects/nandu-new --stage shot --shot 01
```

`--motion pass` 必须是用户实际观察到**镜头内主体的运动**，而非只有镜头推拉/静帧变焦。重复出场的人物还必须用 `--identity pass` 记录跨镜头外貌、年龄感和服饰的一致性。项目会抽取少量解码帧，提示“完全相同”静帧的风险；**这一技术测试既无法证明主体运动，也不能代替人工审片**。

如果脸部漂移或动作错误，则 `verify-shot --result fail` 并退回镜头，保留原版本和既有费用记录。

## 4. 自然旁白先试听，再配正式成片

项目中的台词若以 `旁白`、`narrator`、`voiceover` 或 `解说` 标注，V1.4 新的 `flow_dynamic` 项目会自动启用声音复核并要求替换旁白音轨，不允许只用默认系统 TTS 就宣布声音定稿。

先生成试音文案：

```powershell
video-studio voice-guide projects/nandu-new
```

文件是 `production/voice_audition_guide.md`，供外部真人/高质量语音工具制作温暖、沉静两种试音；项目不在无授权条件下购买或访问任何配音服务。

将两个已试听音频交给项目：

```powershell
video-studio voice-audition projects/nandu-new --warm "D:\\Audio\\warm.wav" --somber "D:\\Audio\\somber.wav" --source "外部配音员或已授权语音工具"
video-studio voice-approve projects/nandu-new --note "试听了人物情绪、气口、语调和实际画面；音色自然，适合作品"
```

正式分句配音还需用现有 `ingest --kind voice --line ...` 导入，每条旁白按其真实音频检查字音、停顿与字幕。若旁白需要替换但未导入，则最终 QA 阻断。**试音批准不等于实际语音被自动强制对齐：现有 SRT 按计划时间排布，实际语音、字幕、接触声的同步必须结合视频审听校准**。不要说已实现自动 Whisper 对齐或真实人声检测。

## 5. Gemini 导演复核止损

每个新 V1.3/V1.4 项目最多执行 **2 轮自动 Gemini 导演复核**。超限后不继续循环生成相互矛盾的建议。用户已经批准的故事圣经仍由哈希保护；如导演意见矛盾，可由用户在核实后作出有据可查的终局决定：

```powershell
video-studio director-override projects/nandu-new --reason "沿用用户已批准的江岸结尾；从手中纸卷拉远且人物必须仍可辨认，第二镜动作简化"
```

该命令不能覆盖项目结构校验错误，至少要有一次实际 Gemini 导演复核，且必须写明不少于 12 字的选择理由。它将人类导演选择记录进审查事件，不会隐瞒 Gemini 提出的旧问题。

## 6. 交付前必须出报告

```powershell
video-studio delivery-report projects/nandu-new
video-studio advance projects/nandu-new  # 全部镜头批准后进行严格交付预检和实际合成
video-studio approve projects/nandu-new --stage final
```

`production/delivery_report.json` 显示每镜来源、候选文件 SHA 校验、动态表演验收、人物身份验收、试听结果阻断项，以及授权/可能扣费次数。若 `ready=false`，不得把技术 MP4 称为正式完成；如需只展示节奏方案，应使用单独的 `animatic` 项目和清楚的标签。

## 回归案例

- 《南渡》：全部 8 镜为 Flow 动态来源；预演不能伪称动态正片；对齐字幕和旁白、李清照跨镜年龄感；额度数量逐项对账。
- 《嫦娥奔月》：承接 V1.3 的剪接连续性，对主体运动和人物身份做真实审核。
- 手工/产品：材料摆放、手和工具的运动必须真实；不得把单张图的推拉称为制作过程。

所有网页操作仍需本人在已登录浏览器中完成必要审核；此项目没有已验证的 Google 官方计费账单 API、自动人物身份识别器或自动 ASR 音素级对齐。V1.4 本地测试仅证明本地流程、渲染和状态门禁，不能替代真实 Flow 端到端复核。
