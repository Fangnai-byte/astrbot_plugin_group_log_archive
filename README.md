# Group Log Archive (群聊日志归档)

<p align="center">
  <img src="logo.png" width="120" alt="logo"/>
</p>

一个 [AstrBot](https://github.com/Soulter/AstrBot) 插件：定时将 AstrBot 文件日志中的**群聊记录**增量导出为按天归档的纯文本文件，只保留聊天内容，省空间、省上下文。

## 功能

- 定时（默认 60 秒）增量导出群聊记录，只保留聊天内容
- 只保留聊天记录行，过滤掉系统调试、LLM 请求等无关日志（体积可缩小 99%+）
- 按天归档：`astrbot_YYYY-MM-DD.log`
- 导出后自动清空源日志（truncate），避免 `data/logs` 与归档双份增长
- 增量断点续传（`.export_state.json`），AstrBot 重启/日志轮转不丢不重
- 插件卸载时执行最终导出，保证数据完整性
- 提供 `/log_archive` 指令查看状态、手动导出

## 前提条件

1. AstrBot 需开启**文件日志**并设为 **DEBUG** 级别（这样日志里才会记录群消息原文）：
   - WebUI → 设置 → 日志相关：`log_file_enable=true`、`log_level=DEBUG`
   - 修改后需重启 AstrBot 生效
2. 本插件依赖 `apscheduler`（AstrBot 自带，无需额外安装）

## 安装

将本插件目录放入 AstrBot 的 `data/plugins/` 下，然后在 WebUI 的插件市场/管理页启用即可。

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
| `log_dir` | 源日志目录，留空自动使用 `data/logs` | 空 |
| `log_prefix` | 源日志文件名前缀 | `astrbot.log` |
| `output_dir` | 归档输出目录，留空自动使用 `data/workspaces/group_logs` | 空 |
| `only_chat` | 只保留聊天记录 | `true` |
| `clean_source` | 导出后清空源日志 | `true` |

## 归档格式

每行一条群消息（原始日志行），形如：

```
[2026-08-22 01:33:55.519] [Plug] [DBUG] [astrbot.group_chat_context:158]: group_chat_context | pre-config:GroupMessage:748791823 | [昵称/01:33:55]: 消息内容
```

包含：群号、发送者昵称、时间、消息内容（含引用与 @ 标记）。文件按行首时间戳路由到对应日期，未加密。

## 设计说明

- **为什么只匹配 `[astrbot.group_chat_context:` 行？**
  它是 AstrBot 处理群消息时打印的记录，一行一条消息，信息完整（群号/昵称/时间/内容）。
  `[core.event_bus:74]` 行记录的是同一条消息，保留会重复；用行首锚定正则可避免误匹配
  LLM 请求日志中嵌入的对话历史文本。
- **为什么清空源日志用 truncate 而不是删除？**
  AstrBot 的 loguru 持有活跃日志文件句柄，直接删除会导致日志持续写入不可见的 inode，
  白白占用磁盘空间；truncate 保留文件，loguru 以 append 模式写入会从 0 重新增长。

## 兼容性

- 支持 Windows / Linux / macOS；Android proot 等不支持 `rename` 的文件系统亦可运行
  （状态文件保存有降级路径）
- 支持日志轮转文件（`astrbot.log.1/.2/...`），全部导出后删除

## License

MIT License
