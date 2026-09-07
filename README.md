# 词间

只朗诵原词的古典诗词短片。Python 管理可编辑 JSON，Remotion 合成画面、字幕、朗诵和已有音乐。研究中的背景与解释不进入声音轨。

本次《浣溪沙》样片：六张 AI 生成园林画面，缓慢推移，晓晓女声，54 秒，1080×1920。图片运动是剪辑动画，并非生成式视频。音乐是 Scott Buckley 的 Moonlight。

## 运行

需要 Python 3.11+、uv、Node.js、FFmpeg/ffprobe。

已有本地项目可直接打开编辑页面：

```sh
uv run ci-video edit projects/huanxisha
# 浏览器打开 http://127.0.0.1:8765
```

页面支持选镜头、试听每句朗诵、调整镜头时长与朗诵入点、选择/导入图片、导入音乐并记录来源与许可、调整音乐音量/入点/淡化、重新生成朗诵、后台导出和播放 MP4。保存直接写入同一份 `storyboard.json` 并保留历史，过期窗口的保存会被拒绝。当前画面预览是静态构图参考，完整镜头运动与混音以导出的成片为准。

页面仅监听本机，一次打开一个项目。生成语音需要相应在线服务，外部 API 按已配置模型计费；编辑和使用已有素材导出不调用生成模型。当前不提供参考录音声音转换或可视化生图；可以导入其他工具生成的图片。运行后台任务时请不要另外用 CLI 修改同一项目。换端口用 `--port 8766`，终端 Ctrl+C 退出编辑器。

其他 Agent 的使用与维护指南见 [AGENTS.md](AGENTS.md)。

```sh
uv sync
npm ci
cp .env.example .env.local
# 在 .env.local 配置密钥，禁止提交
uv run ci-video demo projects/my-film
uv run ci-video images projects/my-film --dry-run
uv run ci-video images projects/my-film
uv run ci-video tts projects/my-film --provider external --fit
uv run ci-video bgm projects/my-film --track moonlight
uv run ci-video render projects/my-film
```

示例 Script 已人工校对，可直接使用。重新研究/生成 Script 可分别执行 `research`、`script`、`storyboard` 命令，文本提供方默认 DeepSeek。对 Research 的人工审阅不能由 JSON 校验替代。

生图与语音适配 OpenAI-compatible `/images/generations`、`/audio/speech`，可分别配置地址、模型和密钥；不表示兼容所有厂商的原生协议。Luna 用于文本，不用于图像或语音。付费 API 失败会停止，不自动切换供应商或反复扣费。

免费在线语音替代可显式执行：

```sh
EDGE_TTS_RATE=-35% uv run ci-video tts projects/my-film --provider edge --voice zh-CN-XiaoxiaoNeural --fit
```

这是 edge-tts 接入的在线服务，不是有 SLA 的付费语音 API。本次 OpenAI 语音账户返回 `credit_balance_exhausted`，样片实际使用 Edge。样片六张图片由 Codex image_gen 生成并导入，不声称已实测成功调用付费 Images API。

本地生成图片可通过 `import-image PROJECT --scene s01 --file /absolute/image.png --prompt '画面描述' --provider '供应商'` 导入。图片/音频二进制、密钥和视频不进 Git；新克隆需重新生成或导入素材。

## 编辑与重放

修改 `projects/<id>/storyboard.json` 后直接运行 `render`。它只读取 Storyboard 和引用的本地媒体，不需要 Research、LLM 或网络。调整诗句文本需要重做 TTS；纯朗诵模式要求六句按原顺序完整出现，不能添加解说。

`duration` 控制镜头时长，`voice_offset` 控制重新生成 TTS 时的入点，已有音轨的入点是 `audio.offset`；`subtitle` 使用镜头内秒数。`bgm_start / bgm_volume / bgm_fade / bgm_duck` 控制音乐截取、音量、淡化与朗诵时压低音乐。`tts --fit` 只延长不够长的镜头，不缩短手工留白。

生成请求、哈希缓存和 JSON 历史保存在项目中。输出包含 `output.mp4`、实际渲染快照 `rendered-storyboard.json`、校验报告 `render-report.json` 和发布署名 `credits.md`。

已有音乐目录在 `examples/music/catalog.json`；添加歌曲需填写下载链接、作者、许可、许可链接及署名。`bgm` 下载实际音乐，不生成音乐；换曲后再次 Render。发布样片时须附上 `credits.md` 中的音乐署名。

```sh
uv run pytest
npm run typecheck
uv run ci-video validate projects/huanxisha
```

开源复用与许可见 [调研](docs/open-source-survey.md)。
