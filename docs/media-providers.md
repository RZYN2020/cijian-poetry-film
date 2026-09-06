# 外部媒体 Provider

媒体生成不是固定绑定某一家服务。TTS 适配器接收 `text / voice / rate`，返回本地音频、时长、边界和请求元数据；图片适配器接收 scene 的 `visual_intent`，返回本地图片、模型、prompt、来源与许可。Provider 结果落盘后，Render 不再请求 API。

`TTS_PROVIDER=external`（默认）使用兼容 OpenAI Audio Speech 的端点（`TTS_BASE_URL`、`TTS_MODEL`、`TTS_API_KEY`）。可显式选择 `--provider edge` 或 `macos`，不会自动降级。图片命令 `images` 使用 `IMAGE_BASE_URL / IMAGE_MODEL / IMAGE_API_KEY`；支持返回 base64 或 HTTPS 图片 URL。`images --dry-run` 只保存请求，`import-image` 导入已有生成结果。只有 OpenAI 官方域名可以复用 OPENAI_API_KEY，自定义服务必须配置独立密钥。

BGM 由 `ci-video bgm` 从明确的音乐目录下载，不再合成占位氛围轨。默认 [Moonlight](https://www.scottbuckley.com.au/library/moonlight/) 是钢琴与弦乐，采用 CC BY 4.0；下载链接、署名、许可与校验和记录于 manifest。可编辑音乐目录添加其他已获许可的曲目，不需要 BGM 生成 API。

渲染时根据 `bgm_start / bgm_volume / bgm_fade / bgm_duck` 截取、淡化和压低音乐。`credits.md` 保存发布署名，不在朗诵中加入这些文字。样片使用 Codex image_gen 的六张生成图和 Edge 晓晓女声；付费 OpenAI TTS 本次返回余额不足，兼容 API 成功路径另有 mock 测试，未伪装为付费调用成功。
