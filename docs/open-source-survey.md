# 开源复用调研

核验日期：2026-09-06。先确定 Storyboard 接口，再接已有媒体工具；不 fork 整套视频产品。

| 项目 | 可直接复用 | 可参考 | License / 约束 | 本项目决策 |
| --- | --- | --- | --- | --- |
| [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 其依赖的 `edge-tts`、媒体处理生态；将来可抽取 Pexels/Pixabay 适配器 | `app/services/voice.py` 的配音与时间戳、`material.py` 的素材选择、`video.py` 的裁剪/合成 | [MIT](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/LICENSE)，复制代码需保留通知；素材和模型服务另有条款 | 直接依赖底层库，暂不导入其全局 config、MoviePy 和任务系统；研究证据与文学脚本由本项目负责 |
| [ShortGPT](https://github.com/RayVentura/ShortGPT) | 其使用的 Edge TTS、FFmpeg、现成字幕工具；Pexels 接口可按需适配 | `shortGPT/engine/abstract_content_engine.py` 的分步持久化；Editing Markup Language / JSON；`audio/edge_voice_module.py` | [MIT](https://github.com/RayVentura/ShortGPT/blob/stable/LICENSE)。本地检查 stable HEAD `3df4e0f7a422bf7386565d498bf4521a2544c614` | 借鉴显式阶段与可编辑 JSON；不引入 TinyDB 隐式属性、发布流程或整个 Engine；当前依赖固定旧 OpenAI SDK，直接集成会增加耦合 |
| [Remotion](https://github.com/remotion-dev/remotion) | `@remotion/bundler`、`@remotion/renderer`、React Composition、Sequence、音频/图片/视频组件；现成 Chromium 渲染与 FFmpeg 编码链路 | 参数化合成、逐帧确定性动画、Studio 预览 | [自定义 Remotion License](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)，不是 MIT：个人、最多 3 名员工的营利组织等符合免费条件；其他情形需 Company License | 第一版唯一 renderer：JSON → React → Remotion/FFmpeg → MP4；固定依赖版本，业务不直接管理编码管线 |

## MVP 的复用边界

- TTS：直接使用 [edge-tts](https://github.com/rany2/edge-tts) 的 `Communicate` 与边界事件，不自行实现语音合成。包的 LGPL 与在线服务使用条件分开看。允许导入人工配音。
- 字幕：保存 scene 内的字幕时间段，TTS 边界优先；SRT 序列化使用现成 `srt`。不把中文强行按空格切词，不默认引入 Whisper 模型。
- 素材：第一版按清单下载已选素材或导入本地文件，记录 URL、作者、许可与 SHA-256；无需自动搜索成功才能渲染。不把 Bing 搜索结果视为许可证明。
- 媒体下载：使用 HTTP 客户端流式下载；没有视频平台抓取需求时不引入 yt-dlp。
- 渲染：使用 Remotion 的 bundler / renderer。只以 `ffprobe` 检查时长、音轨；不自研 FFmpeg wrapper、剪辑 DSL 或工作流引擎。
- 数据：Pydantic + JSON Schema；每个项目一个目录，JSON 即可编辑的事实来源。当前没有需要 SQLite 的查询负载。

## 对架构的影响

`Brief → Research Pack → Script → Storyboard → Assets / TTS → Render` 是几个可单独运行的命令。Research 保留 Claim → Evidence → Source；事实与阅读解释分型。Render 只依赖 Storyboard 和其引用的本地文件，绝不调用 LLM 或重新研究。旁白改动使相应音频失效；纯字幕/画面/时长调整不影响研究。

DeepSeek 默认使用可配置的便宜模型，JSON mode 后仍做本地 schema 与引用校验，不能把“合法 JSON”当成“可靠知识”。[DeepSeek JSON 文档](https://api-docs.deepseek.com/guides/json_mode/)；可选 OpenAI 默认模型名为官方文档确认的 [`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna)。禁止自动升级到更贵模型。

参考实现 API：[Remotion renderMedia](https://www.remotion.dev/docs/renderer/render-media)。研究与素材的版权不由以上代码 License 覆盖。
