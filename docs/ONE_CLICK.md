# 一键制片｜V1.3 默认流程

最新版以 [V1.3 中文导演说明](DIRECTOR_V13.md) 为准。

1. `video-studio start ... --provider gemini-web`：先让已登录的 Gemini 生成故事圣经（无 Flow 扣费）。
2. `video-studio approve ... --stage story`：人工确认因果、情绪、结局。
3. `video-studio advance ... --gemini-config ...`：Gemini 按批准剧本出分镜、景别、剪接计划。
4. `video-studio director-review ... --gemini-config ...`：独立 Gemini 导演复核，直到无阻断问题。
5. `video-studio approve ... --stage storyboard`，然后明确批准 Flow 次数。
6. `video-studio advance ... --flow-config ...`：一次生成一镜；每镜导入或浏览器下载后审核。
7. 第二镜起还需观看剪接预览，`verify-seam ... --left 01 --right 02 --result pass --note ...`；单镜也要按 V1.2 `verify-shot`。
8. 全部完成后 `advance` 按有效入出点自动剪辑、拼接、混音和字幕；人工确认最终 MP4。

初次需安装 Python 3.10+、FFmpeg、Playwright、Chrome，校准实际 Gemini 和 Flow 页面选择器。不提供绕过付费、验证码或登录的自动化。V1.2 快速模式可通过 `start --quick-storyboard` 保留。

参见 [V1.2 质量控制说明](QUALITY_V12.md) 和 [完整 V1.3 导演说明](DIRECTOR_V13.md)。
