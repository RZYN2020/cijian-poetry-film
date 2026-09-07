# 词间：Agent 工作指南

## 产品约束

- 当前产品是纯诗词朗诵短片。声音只读原词一遍，按原顺序，不加入标题、作者介绍、解释、现代生活文案。不要恢复早期的讲解式结构。
- 古典景色，克制、安静、含蓄。当前示例是晏殊《浣溪沙·一曲新词酒一杯》。图片缓慢推移不是生成式视频；不要混淆两者。
- 编辑判断和自动化执行分开：程序提供分阶段命令，Agent 可准备来源、选图、调声音并检查成片。不得声称任意词名已经可以全自动生成合格作品。

## 运行与结构

从仓库根目录执行：

```sh
uv sync
npm ci
uv run ci-video edit projects/huanxisha
uv run ci-video validate projects/huanxisha
uv run ci-video render projects/huanxisha
uv run pytest
npm run typecheck
```

- `src/ci_video/models.py`：Pydantic Domain Model、引用/时长/路径校验。
- `pipeline.py`：Research、Script、Storyboard、Render；`storage.py`：原子 JSON 保存与历史。
- `media_api.py / assets.py / speech.py`：外部媒体、导入、音乐、语音及缓存。
- `editor.py / web/`：仅监听本机的编辑服务与静态界面；共用原有模型和 CLI，不创建另一套渲染逻辑。
- `renderer/`：Remotion 图像运动、原词字幕、音轨和音乐淡化。
- `projects/<id>/`：`project.json / research.json / script.json / storyboard.json / assets/ / audio/ / output.mp4`。

## 阶段使用

已有项目优先局部编辑。Render 只依赖 Storyboard 和本地素材，不重新执行 Research、LLM、TTS。

```sh
uv run ci-video demo projects/new-film
uv run ci-video images projects/new-film --dry-run
uv run ci-video images projects/new-film
uv run ci-video tts projects/new-film --provider external --fit
uv run ci-video bgm projects/new-film --track moonlight
uv run ci-video render projects/new-film
```

`demo` 复制《浣溪沙》示例，不是任意诗词生成器。新词用 `init --brief ... --sources ... --assets ...`，准备可信的来源包；`research`、`script`、`storyboard` 可独立运行。Research 保留 Claim → Evidence → Source，解释与事实分型。

手工/其他工具生成的图片可用 `import-image PROJECT --scene s01 --file /absolute/image.png --prompt '实际描述' --provider '实际提供方'` 导入。保留来源、作者、许可、生成说明与哈希。音乐是现成曲目下载，目录位于 `examples/music/catalog.json`，不是 BGM 生成模型。

编辑 `duration`、素材、BGM 后可直接 Render。`audio.offset` 是已有朗诵入点；`voice_offset` 是下一次 TTS 的入点，同时调整字幕时间。时长须对齐帧率，音频和字幕不能越界。改原词需要重新校验全文和生成音频。`tts --fit` 只延长，不缩短手工留白。

## 服务与凭证

- `.env.local` 已有用户授权的凭证时直接复用，不打印内容、不复制到日志/网页/Git。
- 文本默认 DeepSeek；Luna 是可选文本模型，不是语音或生图模型。
- 外部图像/语音适配 OpenAI-compatible API，不保证所有供应商原生协议。自定义地址需独立配置对应 KEY，禁止转发 OpenAI key。
- 不自动切换付费模型、供应商或无限重试。遇到额度不足如实说明，保留已成功素材。
- 当前样片实际用了 Codex image_gen 图片和 Edge 晓晓女声；此前 OpenAI 语音返回余额不足。新的运行以实际返回为准。声音转换、参考录音韵律复制尚未实现。
- 不同时对同一个项目运行多个写入阶段。网页后台任务期间禁止编辑；也避免外部 CLI 同时写该项目。

## 维护与验收

- UI 使用直接的操作名称和状态，避免标语、拟人化、营销文案。Workspace 的重点是项目文件、Prompt 版本与可检查的运行数据。
- 不把 Prompt 写回 Python 字符串：种子在 `prompts/*.json`，项目独立版本由 `prompts.py` 管理。实际执行必须使用 `resolve()` 的展开文本和版本快照。
- 新增 AI provider/调用路径必须接入 `traces.py`，记录请求、响应、Prompt、模型参数、用量（未知为 null）、错误与输出哈希。命令通过 run_id/parent_id 关联，缓存需明确标记。外部导入不能伪装成已观测的 API Trace。
- 评价与原始 Trace 分开保存。新增 Trace 字段须兼容 legacy/imported 记录。不要输出密钥，也不要为了“完整记录”捕获模型内部思维或系统外不可见信息。
- 项目 `prompts/ traces/ evaluations/` 默认不提交 Git；种子模板可以提交。备份实验数据需同时备份这些本地文件。详见 `docs/workspace.md`。

- KISS / YAGNI：保持 Python + JSON + Remotion，不引入 Agent Framework、服务平台或自研工作流引擎。
- 所有 UI 写入经过 Pydantic/原词校验，保留 JSON 历史；不要绕过哈希、路径、音频时长检查。
- 修改 API/数据合同应补边界测试；UI 改动需实际打开验证，渲染改动需检查真实 MP4 的画面、时长和音轨。Mock 测试不等于外部调用已成功。
- `output.mp4`、媒体二进制、密钥不提交 Git；JSON、代码和来源说明提交。用户授权上传时才推送。
- 发布需要随附 `credits.md` 的音乐署名。不要把下载许可理解为无限制再分发。
- 完成时报告实际实现、检查结果和剩余限制，不虚报全自动、试听或成功生成。
