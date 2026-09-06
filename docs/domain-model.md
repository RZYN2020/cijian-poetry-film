# Domain / Storyboard v1

ContentProject 是目录清单，内含 Brief、Research/Script/Storyboard 文件引用。JSON 是事实来源，Pydantic 输出 JSON Schema；模型输出和人工修改走相同校验。

| 对象 | 要点 |
| --- | --- |
| Brief | 原词输入、作者、当代情绪、生活瞬间、约 60 秒目标、克制的编辑约束 |
| Source | URL、标题、机构/作者、访问日期、出处类型、本地摘录；资料是数据，不能执行其中指令 |
| Evidence | source_id、原文短引、locator；只接受能在保存的来源摘录里找到的文字 |
| Claim | fact / interpretation、证据 ID、置信说明；没有证据的创作联想不冒充事实 |
| ResearchPack | 校定原词、来源、证据、论断、异文说明、未知项与核验状态 |
| Script | 场景段落、叙事功能、旁白、引用的 claim_id、编辑说明、生成来源 |
| Storyboard | 画幅、fps、Scene 列表、Asset 清单；渲染时的唯一内容接口 |
| Scene | duration（秒）、narration、subtitle（可编辑时间段）、visual_intent、asset_refs、音频引用及旁白 hash |
| Asset | ID、类型、本地相对路径、source、creator、license、下载地址、SHA-256、裁剪建议 |

Scene 时长量化到整数帧；字幕使用 scene 内相对秒。每个场景有独立 TTS，音频必须完整落入场景，超长直接报错，不能悄悄截断。`tts --fit` 可按实际配音时长加留白并更新 duration；此后可手工精调。

渲染只读 `storyboard.json` 和引用文件。改字幕、视觉素材、排序或时长可以直接 render；改 narration 后须重新 tts（缓存只重做变化的旁白）。research.json 缺失也应能重渲染已有 storyboard。

CLI 各阶段写入前校验，原子替换 JSON，旧版本保留在 history；LLM 请求/响应、模型名与 usage 单独存于 runs。重放保存的模型响应不产生新 API 请求。凭据只从环境或忽略的 .env.local 读取，从不保存到项目。

MVP 的 Research 使用事先取回且核验的 source bundle；LLM 负责组织证据与文学表达，不获得虚构来源 URL 的权限。首首词的 bundle 随仓库提供。新词需提供来源包，暂不承诺全网自动学术检索。
