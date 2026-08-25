# Group Log Archive (群聊日志归档)

![logo](logo.png)

一个 [AstrBot](https://github.com/Soulter/AstrBot) 插件：定时将 AstrBot 文件日志中的**群聊记录**增量导出为按天归档的纯文本文件，只保留聊天内容，省空间、省上下文。支持分群归档、图片实时保存与 AI 命名、隐私脱敏。

## 功能

- **定时增量导出**群聊记录，只保留聊天内容（默认 60 秒，支持 cron 自定义时间，如 `12:00` 或 `0 3 * * *`）
- **只保留聊天记录行**，过滤掉系统调试、LLM 请求等无关日志（体积可缩小 99%+）
- **分群按天归档**：`astrbot_<群号>_YYYY-MM-DD.log`，各群互不混淆
- **图片实时保存**：群里的图片自动存入 `tu/` 子目录并记录，支持 AI 自动命名、定时清理
- **隐私脱敏**：群号哈希、QQ 号打码（可选开关）
- 导出后自动清空源日志（truncate），避免 `data/logs` 与归档双份增长
- 增量断点续传（`.export_state.json`），AstrBot 重启/日志轮转不丢不重
- 插件卸载时执行最终导出，保证数据完整性
- 提供 `/log_archive` 指令查看状态、手动导出

## 前提条件

1. AstrBot 需开启**文件日志**并设为 **DEBUG** 级别（这样日志里才会记录群消息原文）：
   - WebUI → 设置 → 日志相关：`log_file_enable=true`、`log_level=DEBUG`
   - 修改后需重启 AstrBot 生效
2. 依赖 `apscheduler` 与 `Pillow`（AstrBot 自带，无需额外安装）

## 安装

将本插件目录放入 AstrBot 的 `data/plugins/` 下，然后在 WebUI 的插件市场/管理页启用即可。

## 快速开始（新手必看）

1. **安装插件**：下载 Release 页的 zip 解压后放入 `data/plugins/`，或在 WebUI 插件管理 → 从 Git 仓库安装：`https://github.com/Fangnai-byte/astrbot_plugin_group_log_archive`，然后启用。
2. **开启日志（关键，否则没有数据）**：
   - 插件配置里打开 `auto_enable_debug`（自动修改 AstrBot 配置），或手动开启 `log_file_enable=true` + `log_level=DEBUG`；
   - **重启 AstrBot** 生效。
3. **按需配置**（插件配置页）：
   - `track_images`：图片自动保存到 `tu/`；
   - `image_caption`：AI 给图片命名（需支持识图的模型，会消耗 token）；
   - `mask_group_id` / `mask_qq_id`：群号/QQ 号脱敏；
   - `log_cleanup`：如 `7day/04:30` 定时清理过期日志；
   - `cron_expression`：如 `12:00` 指定每天定时导出。
4. **开始使用**：管理员在群里发送 `/log_archive status` 可查看归档路径与文件列表；归档文件默认在 `data/workspaces/group_logs/`。
5. **遇到问题**：阅读下方「常见问题」和「故障排查（AI/Bot 指引）」。

## 文件保存在哪里

- **默认归档目录**：`<AstrBot根目录>/data/workspaces/group_logs/`
- **归档文件**：`astrbot_<群号>_YYYY-MM-DD.log`（每个群一个文件，按天归档，如 `astrbot_123456789_2026-08-22.log`）
- **图片目录**：`group_logs/tu/`（开启图片追踪后自动创建）
- **增量状态文件**：同目录下的 `.export_state.json`（记录导出进度，勿删）

不确定路径时，群里发送 `/log_archive status`，插件会直接告诉你实际归档路径和文件列表。想改存放位置，在插件配置里设置 `output_dir`（见下方配置项）。

## 使用

发送指令（群聊或私聊均可）：

```
/log_archive status   # 查看状态与归档文件列表
/log_archive now      # 立即导出一轮
/log_archive clean    # 手动清空源日志
/log_archive help     # 显示帮助
```

### 配置项

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `poll_interval` | 轮询导出间隔（秒），最小 5 | `60` |
| `cron_expression` | 定时导出时间，支持简单格式 `12:00`（每天12点）或完整 cron（如 `0 3 * * *`、`*/5 * * * *`），留空用间隔模式 | 空 |
| `log_dir` | 源日志目录，留空自动使用 `data/logs` | 空 |
| `log_prefix` | 源日志文件名前缀 | `astrbot.log` |
| `log_source` | 聊天记录日志源：`auto`=自动检测（优先级 GC→RawMessage→event_bus）；`group_chat_context`=开 DEBUG 且消息进管线（信息全）；`rawmessage`=开 DEBUG 即可（含群号，可绕过管线过滤）；`event_bus`=INFO 即可（无群号，不分群） | `auto` |
| `group_whitelist` | 群白名单：仅归档列表中的群（填群号），留空=全部群 | 空 |
| `auto_enable_debug` | 自动开启 DEBUG：检测到未开 DEBUG 时自动修改 AstrBot 配置（`log_level=DEBUG` + 文件日志），重启后生效 | `false` |
| `log_cleanup` | 日志自动清理：格式 `<天数>day/<时>:<分>[:<秒>]`，如 `3day/00:00:00:000`（保留3天、每天零点清理）、`7day/04:30`；留空不清理 | 空 |
| `output_dir` | 归档输出目录，留空自动使用 `data/workspaces/group_logs` | 空 |
| `only_chat` | 只保留聊天记录 | `true` |
| `clean_source` | 导出后清空源日志 | `true` |
| `mask_group_id` | 群号脱敏（哈希替代，文件名+内容均生效） | `false` |
| `mask_qq_id` | QQ号脱敏（打码如 `123****456`） | `false` |
| `track_images` | 图片追踪：实时监听群消息，图片自动保存到归档 `tu/` 目录并记录 | `false` |
| `cleanup_images` | 自动清理：按保留天数清理 `tu/` 目录图片 | `false` |
| `image_retention_days` | 图片保留天数（配合 `cleanup_images`） | `7` |
| `image_caption` | AI 图片命名：调用识图模型为图片生成 5-6 字名称（消耗 API token） | `false` |
| `image_caption_provider` | 命名用模型 Provider ID，留空自动选择支持视觉的模型 | 空 |

> 隐私提示：默认**不脱敏**，归档为原始记录（含群号/昵称/内容）。如需分享归档，建议开启脱敏配置。

## 图片功能

开启 `track_images` 后，插件会**实时监听**群消息，群里发的图片/文件图片会被立即保存（**原图**）到归档目录的 `tu/` 子文件夹，同时在当天的分群归档文件里追加一条记录：

```
[2026-08-22 13:08:05.839] [Plug] [INFO] [astrbot.group_log_archive]: group_chat_context | pre-config:GroupMessage:123456789 | [Fangnai/13:08:05]: [图片] [图:tu/img_20260822130805_0.jpg]
```

- 图片以 `img_时间戳_序号.扩展名` 命名，按群分目录存放（`tu/<群号>/`，脱敏时为群号哈希），与归档记录一一对应
- 纯图片、文件图片、动画表情都能捕获（不依赖日志，事件实时驱动）
- 群号脱敏开启时，文件名与记录中的群号会同步使用哈希

开启 `cleanup_images` 后，会按 `image_retention_days`（默认 7 天）自动清理 `tu/` 目录下过期的图片，避免占用过多空间。

### AI 图片命名（可选）

开启 `image_caption` 后，保存的图片会调用**识图模型**自动生成 5-6 字名称并重命名（如 `img_20260800000000_0绫地宁宁.jpg`），归档记录同步更新：

- `image_caption_provider` 留空时自动选择支持视觉的模型（优先模型名含 vision/vl/mimo/glm-4v/qwen-vl 的）
- 识别前自动压缩图片（仅用于识别，**保存的仍是原图**），速度提升 10 倍+（约 3 秒）
- xiaomi/mimo 系推理模型直连 API 并读取推理内容；其他模型走 AstrBot 标准 LLM 接口
- 命名在**后台异步**进行，不影响消息收发与处理；失败时自动保持原名
- 注意：需要模型支持图片识别，且会消耗 API token
- 隐私说明：xiaomi/mimo 系模型直连时，插件会读取本机 `cmd_config.json` 中的该模型 API Key 用于直接调用（**仅本机使用，不外传、不转发**）；介意可关闭 `image_caption` 或改用其他 provider

## 归档格式

每个群一个文件，文件名 `astrbot_<群号>_YYYY-MM-DD.log`，每行一条群消息（原始日志行），形如：

```
[2026-08-22 01:33:55.519] [Plug] [DBUG] [astrbot.group_chat_context:158]: group_chat_context | pre-config:GroupMessage:123456789 | [昵称/01:33:55]: 消息内容
```

包含：群号、发送者昵称、时间、消息内容（含引用与 @ 标记）。文件按群号+日期路由，未加密。

- **为什么偶发 `pre-config:pre-config:` 双前缀？** AstrBot 偶发会输出双重平台标识，
  插件导出时会自动规范化，不影响群号提取与分群。

## 常见问题（FAQ）

**Q：装了插件但没有日志输出？**
A：一般是 AstrBot 没开**文件日志**或日志级别不是 DEBUG。优先在插件配置里打开 `auto_enable_debug`（会自动修改 AstrBot 配置，重启生效）；或手动在 WebUI 设置里开 `log_file_enable=true`、`log_level=DEBUG`。

**Q：一定要开 DEBUG 吗？**
A：不开也能用——插件会**自动检测**并回退到 INFO 级别的 `event_bus` 日志（`log_source=auto`），消息照常记录；但 event_bus 行**不含群号**，归档到 `astrbot_unknown_日期.log`。想按群分文件，还是建议开 DEBUG（`group_chat_context` 含群号）。

**Q：图片没有自动保存？**
A：检查插件配置里 `track_images` 是否开启；开启后图片实时保存到归档目录的 `tu/` 子文件夹（保存的是原图）。

**Q：AI 命名没生效？**
A：确认 `image_caption` 已开启、`image_caption_provider` 指向支持识图的模型（留空自动选视觉模型）。命名是后台异步的，稍等片刻；失败会自动保持原名。注意会消耗模型 API token。

**Q：归档日志一直在重复？**
A：一般是**旧版导出脚本（`export_group_logs.py`）和插件同时在跑**，共用状态文件互相覆盖导致重复导出。插件启动时会自动检测旧脚本进程并警告（`pgrep -f export_group_logs.py` 可手动确认），停掉旧脚本、只保留插件即可。如果已重复，删除 `.export_state.json` 并清掉重复的归档文件后重来。

**Q：归档文件在哪？**
A：默认 `data/workspaces/group_logs/`，群里发 `/log_archive status` 可直接查看实际路径和文件列表。

## 设计说明

- **为什么只匹配 `[astrbot.group_chat_context:` 行？**
  它是 AstrBot 处理群消息时打印的记录，一行一条消息，信息完整（群号/昵称/时间/内容）。
  `[core.event_bus:74]` 行记录的是同一条消息，保留会重复；用行首锚定正则可避免误匹配
  LLM 请求日志中嵌入的对话历史文本。
- **为什么清空源日志用 truncate 而不是删除？**
  AstrBot 的 loguru 持有活跃日志文件句柄，直接删除会导致日志持续写入不可见的 inode，
  白白占用磁盘空间；truncate 保留文件，loguru 以 append 模式写入会从 0 重新增长。
- **为什么纯图片消息走事件监听而不是日志匹配？**
  纯图片/文件/表情消息不会进入 group_chat_context 日志，因此插件通过 AstrBot 事件
  系统实时拦截保存，保证不漏图。

## 故障排查（AI/Bot 指引）

> 此部分面向 AI 助手/Bot，可照着步骤执行，帮用户排查常见问题。

### 症状：归档日志一直重复、没有新内容

1. **确认是否多导出源并存**（最常见原因）：
   ```
   pgrep -f "export_group_logs.py"
   ```
   如果有输出（存在旧版导出脚本进程），执行 `kill <PID>` 停掉它，只保留本插件作为唯一导出源。旧脚本与本插件共用 `.export_state.json`，互相覆盖 offset 导致重复导出。

2. **确认插件唯一实例**：查看插件是否被重复加载（AstrBot 插件管理里只应有一个 Group Log Archive）。

3. **检查状态文件是否正常**：
   ```
   cat <output_dir>/.export_state.json
   ```
   正常情况 `offset` 应持续增长；若反复归零/变小，说明存在竞争写入者。

4. **清理已重复的数据**：
   - 删除 `.export_state.json`（让插件重新开始，会丢失断点，但不会重复）
   - 删除归档目录下重复内容的日志文件
   - 重启 AstrBot 或重载插件

5. **验证**：等待一个导出周期（60 秒），检查归档文件新内容是否只有一份；重复的行不再出现即为解决。

### 症状：归档文件是 `astrbot_unknown_日期.log`

- 说明走的是 **event_bus 兼容模式**（日志级别或文件日志未配置到位），该模式无群号信息、无法分群。
- 解决：开启 DEBUG + 文件日志（可配置 `auto_enable_debug` 自动修改并重启），插件会自动切换到 `group_chat_context` 模式按群分文件。
- 若已开 DEBUG 仍 unknown：确认插件版本 ≥ 1.4.3（旧版不兼容新版 AstrBot 的 `账号名:GroupMessage:群号` 格式）。

### 症状：图片没有保存 / AI 命名没生效

- 检查配置 `track_images` / `image_caption` 是否开启。
- AI 命名需要支持识图的模型（`image_caption_provider` 留空自动选视觉模型），且会消耗 API token；命名是后台异步的，稍等片刻，失败自动保持原名。

### 症状：归档里只有管理员/被 @ 的消息，普通成员消息缺失

- 一般是 **AstrBot 的消息过滤/唤醒配置**导致只有部分消息进入处理管道，从而没有 `group_chat_context` 记录。
- 检查 AstrBot 设置项：
  - `empty_mention_waiting`（空 @ 等待）：开启后可能只处理 @ 机器人的消息
  - `enable_id_white_list` / `id_whitelist`（白名单模式）
  - 其他唤醒/过滤相关配置
- 确认已开启 DEBUG + 文件日志；插件自身不会过滤消息来源（宁宁侧测试各成员消息均正常归档）。

### 其他

- 归档路径、状态查询：群内管理员发送 `/log_archive status`（仅管理员可用）。
- 日志清理：配置 `log_cleanup`（如 `3day/00:00:00:000`）可自动清理过期归档。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。

## 兼容性

- 支持 Windows / Linux / macOS；Android proot 等不支持 `rename` 的文件系统亦可运行
  （状态文件保存有降级路径）
- 支持日志轮转文件（`astrbot.log.1/.2/...`），全部导出后删除
- 兼容新旧版 AstrBot 日志格式：旧版 `pre-config:GroupMessage:群号` 与新版（4.27+）`账号名:GroupMessage:群号` 均可识别分群

## License

MIT License
