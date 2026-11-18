# Video Studio V1.2｜通用制片约束与验收规范

本文件供 Codex、Gemini 导演模块和人工审核使用。**适用范围不局限于任何故事、人物或手工题材。**

## 1. 角色 / 主体作用域

- 顶层 `characters` 为身份库，固定相貌、服饰、体态等；不要写“始终站在门外”“全程不能走”等永久动作。
- 顶层 `subjects` 为产品或其它非人主体身份库，固定型号、颜色、包装等；不要写“杯盖始终关闭”。
- 镜头内用 `cast` 和 `subject_ids` 引用需要的实体。未列入的角色/主体不会被注入提示词。
- 每镜的空间位置、运动、开合、接触、离场由 `scene`/`camera`/`action`/`beats` 负责。
- 可以出现 4 名甚至更多演员。建议根据画面复杂度预警，而不是通过代码随意限制人数。

```json
{
  "characters": {"访客甲": "深蓝外衣、短发", "访客乙": "绿色外衣、长发", "接待员": "白色上衣"},
  "subjects": {"便携水杯": "磨砂蓝色杯身、黑色杯盖"},
  "shots": [
    {
      "id": "01", "scene": "展厅门口", "camera": "檐下固定机位，全景", "duration": 10,
      "action": "两人走到门口，接待员从内开门，简单交谈后两人离开",
      "cast": ["访客甲", "访客乙", "接待员"], "subject_ids": [], "materials": [],
      "beats": [{"start": 0, "end": 5, "visual": "走近、敲门和开门"}, {"start": 5, "end": 10, "visual": "交谈并转身离场"}],
      "dialogue": [],
      "acceptance": {
        "start_visible": ["门起初关闭", "两位访客在外侧"],
        "required_events": ["敲门后才能开门", "接待员不能跟访客一起离开"],
        "end_visible": ["接待员留在门内"],
        "end_absent": ["两位访客已经完全出画"],
        "audio_checks": ["敲门声音跟手指接触同步"]
      }
    }
  ]
}
```

注意：上方展示 `characters` / `subjects` / `shots` 子结构，实际项目仍必须包含 `title`、`mode`、`aspect_ratio`、`fps` 等根字段。`acceptance` 是由人审或专门视频视觉审查完成的**验收标准**，代码不会凭空判定这项标准已经成立。

## 2. 分镜提交前的静态检查

运行 `video-studio plan projects/<slug>` 后查看 `production/plan_audit.json`。

- ERROR：角色/主体引用不在身份库；台词说话人已列为全局角色但没出场；结束画面同一文字既必须出现又不得出现；全局身份中出现明确的永久站位限制。这些错误会阻止批准分镜。
- WARN：未明确本镜出场人物、未写验收目标、太多独立动作挤在过短时间窗。需人工处理或明确接受预警。
- 程序不能从一句长动作描述推导出所有肢体运动，不会凭关键词保证逻辑无冲突。导演仍需把复杂动作拆成可拍时间段，必要时拆镜、跳切或换机位。

## 3. 风格化后期配置

```json
"postproduction": {
  "style": "surveillance",
  "camera_prefix": "CAM",
  "clock_start": "08:30:00",
  "location": "COURTYARD",
  "surveillance_fps": 15,
  "sensor_noise": 7,
  "voice": "on",
  "subtitles": "on",
  "original_audio_gain": 0.35
}
```

- `style=clean`：普通画面无额外特效。
- `style=surveillance`：低时间分辨率、低清、弱饱和度、噪点、暗角、REC、机位标识、连续走时码。时间从 `clock_start` 起按镜头规划时长递增。是否是原始真实 CCTV 画面不能单凭这个视觉包装证明。
- `style=vintage`：泛黄低饱和颗粒感；`cinematic`：温和对比度/暗角；均需在实际屏幕上审看。
- 监控 UI 和字幕由 FFmpeg 后期渲染，Flow 原片提示词应要求纯净画面。部分 Windows FFmpeg 构建缺少 `drawtext` / `subtitles`，需安装具备这些滤镜且能显示中文的构建。

## 4. 声音、字幕与拟音

每段 `dialogue` 仍按 `speaker`、`text`、`start`、`end` 声明；`production/voice_lines.csv` 是初步配音时间表。可用外部 VoxCPM / Whisper 辅助制作，但项目不假称自动音素级口型同步。

可以给某一镜增加声音事件：

```json
"sound_events": [
  {"time": 0.7, "path": "assets/sfx/knock.wav", "gain": 0.7},
  {"time": 2.4, "path": "assets/sfx/door.wav", "gain": 0.6}
]
```

声音路径必须是**项目文件夹内的相对路径**，且必须真的存在。配音默认按计划时刻插入，字幕也按计划时刻渲染；若某句新配音超出计划时间窗，`qa` 会提示用户重新配音或调整时间。要确认叩门声与手指触门、开门声与门轴运动、说话起止与字幕吻合，必须观看实际镜头逐点核查。

## 5. 一镜一验收

生成后的素材保留原片，`production/review/` 新增带指定风格及字幕的审片版、开头/中段/近尾帧图，以及 `shot_<id>_human_review.json` 人审记录。

1. 完整播放审片版，不只看接触图。
2. 核查人物/产品身份、入画离画方向、关键事件顺序、结束画面及画外声音。
3. 验收有疑问就 `reject`，保留当前版本并经人工批准额度后重拍；不要自动连刷。
4. 确认后：

```bash
video-studio verify-shot projects/<slug> --shot 01 --result pass --note "完整观看，包括尾帧，动作、风格和音画已核对"
video-studio approve projects/<slug> --stage shot --shot 01
```

有具体 `acceptance` 或非 `clean` 风格的镜头没有 `verify-shot` 记录不能批准。特殊风格必须能渲染审片版，否则会被拦截。需要配音且 `voice=on` 时，缺少配音轨会阻断最终 QA。

## 6. 三类回归场景

- 剧情：四名演员出场、第五名缺席；不得污染提示词；末帧检查人员是否按要求完全出画。
- 产品：仅本镜引用的杯子、包装等外观注入；开盖前后状态独立；不得沿用上镜的“闭合”动作。
- 手作：天然材料孔洞/叶脉/厚度和实际固定过程可辨；末尾检查是否错误瞬间成品。

自动测试只保证工程约束生效与 FFmpeg 能按样本渲染，不等于真实模型已在 Flow 中拍对这些画面。
