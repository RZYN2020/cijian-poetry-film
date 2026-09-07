# Workspace、Prompt 与运行记录

## 参考

参考 [LLM Space 的核心概念](https://github.com/deer-flow/llm-space/blob/main/docs/core-concepts.md)（2026-09-08 查阅）：本地实验文件包含 Prompt、变量、模型设置、运行快照和人工评价。这里只借鉴数据组织方式，没有复制代码或引入其 Agent 框架。

## 页面

- **分镜**：修改现有视频项目，保存与导出。
- **Prompts**：编辑研究、分镜、生图、朗诵指导模板；保存新版本、切换历史版本、查看展开后的文本及当前版本对照。正文和模型参数一起版本化。
- **运行记录**：按阶段、模型、状态或版本搜索，查看实际输入输出、父子调用、耗时、用量与输出素材；保存 1–5 分评价、问题标签和修改备注，选择另一条记录对照，导出全部 JSONL。
- **项目选择**：切换同级目录中已有 Storyboard 的项目。新项目仍使用 CLI `init` / `demo`，不是任意主题一键生成。

页面只操作本机文件。一个服务当前选中一个项目；多个窗口切换项目时，旧窗口的保存会被拒绝。运行期间不要从 CLI 并发写入同一项目。

## Prompt

仓库 `prompts/*.json` 是种子模板。每个项目第一次使用时在 `projects/<id>/prompts/` 建立独立版本：

```text
prompts/image/
  active.json                # 当前版本指针
  <content-hash>.json         # 不可变正文、变量定义、参数和修改说明
```

修改参数也生成新版本；回退只切换指针。Trace 保留调用当时的完整版本快照，不跟随当前模板变化。模板中的 `{{visual_intent}}` 来自镜头描述，变量只做文本替换，不执行表达式、文件 include 或任意代码。

参数以页面显示的白名单为准：文本支持 model、temperature、max_tokens；生图支持 model、size、quality；语音支持 model、voice、speed、edge_voice、edge_rate。未指定的值从环境配置及代码默认值读取；Trace 的 request 记录实际传入的值。默认 provider 仍由本地配置指定，密钥不进入模板。

注意：Edge 语音不接受自然语言表演指导，只支持声音与语速。修改朗诵 Prompt 正文对 Edge 无效。外部语音使用模板正文作为 instructions。以前的 TTS_INSTRUCTIONS 环境变量已由版本化模板替代。

保存模板不调用模型。运行按钮使用当前启用的版本和当前项目输入；查看历史结果不调用模型。生成与缓存都有记录。同一输入使用同一有效配置时可以命中缓存，不把缓存伪装为一次 API 成功调用。

## Trace 与后续优化

每次命令为一个 run，阶段/模型调用通过 run_id、parent_id 关联。文件位于 `traces/<id>.json`；写入 started 状态后执行，成功、失败、缓存命中分别记录。进程意外终止时可能留下 running 状态，这表示未正常结束，不代表任务仍存活。

记录字段包括项目、阶段、镜头、provider/model、Prompt 版本及展开快照、实际 request、API response 或音频边界、开始结束时间、耗时、usage、错误、输出文件路径与 SHA-256。大图片/音频不放进 JSON，保留文件与哈希。HTTP 响应中的图片 base64 不复制进 Trace；响应哈希和解码后文件可核对。没有返回 usage 的服务保持 null，费用当前保持 null，不依据猜测填写。

运行评价保存在独立的 `evaluations/<trace-id>.json`，修改评价不会改写原始调用。导出的 JSONL 将评价附到 Trace 上，方便按 Prompt 版本、参数、问题标签建立后续评估集。当前没有自动优化、训练或在线评价系统。

```sh
uv run ci-video traces projects/huanxisha --import-legacy
uv run ci-video traces projects/huanxisha --export /absolute/path/traces.jsonl
```

旧 `runs/` 仍保留，供既有 replay 命令使用。导入旧日志标记为 legacy；只能从素材清单恢复的图片/声音标记 imported。缺少的原始 Prompt 版本、请求、时间和用量不会补造。系统只能自动捕获经过本项目调用的 AI；在其他软件或 Codex 内完成的生成，需要导入其输出和已有元数据，无法事后还原未提供的完整调用。

这不是模型内部思维记录；保存的是可观测的请求、返回和处理步骤。错误、缓存与校验失败也有记录，方便判断问题出在模型还是处理阶段。

## 数据维护

项目 Prompt 版本、Trace 和评价默认只留本机，不自动上传 GitHub。种子模板与代码提交 Git。API key、授权头和已知密钥字符串会在 Trace 中脱敏；仍需把输入输出视为自己的工作数据。Trace 文件夹应随项目和素材一起备份，只有 Git 仓库不足以恢复所有实验数据。

测试：`uv run pytest`。可选浏览器测试 `tests/workspace_smoke.cjs` 需要可用的 Playwright 和 Remotion 下载的 Chromium。测试在临时项目中修改版本、填写评价、导出记录，不消耗付费 API。
