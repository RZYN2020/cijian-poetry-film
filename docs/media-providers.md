# 外部媒体 Provider

媒体生成不是固定绑定某一家服务。TTS 适配器接收 `text / voice / rate`，返回本地音频、时长、边界和请求元数据；图片适配器接收 scene 的 `visual_intent`，返回本地图片、模型、prompt、来源与许可。Provider 结果落盘后，Render 不再请求 API。

推荐配置：`TTS_PROVIDER=external` 时使用兼容 OpenAI Audio Speech 的端点（`TTS_BASE_URL`、`TTS_MODEL`、`TTS_API_KEY`）；未配置时使用 `macos` 或 `edge`。图片使用 `IMAGE_PROVIDER=external` 时调用用户指定的图像 API；当前额度不足时可继续使用已缓存素材，不阻塞 Render。

BGM 是 Storyboard 的显式字段 `bgm_path / bgm_volume`。可以放入现成且有许可的音乐，或运行 `ci-video bgm` 生成轻量氛围轨；音乐文件也记录在 `assets/manifest.json`，包含来源与许可。不要把未经授权的商业音乐复制进仓库。
