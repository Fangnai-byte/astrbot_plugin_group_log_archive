#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Group Log Archive - AstrBot 群聊日志归档插件
==============================================
定时将 AstrBot 文件日志中的群聊记录增量导出为按天归档的纯文本文件，
导出后可选清空源日志，避免 data/logs 与归档双份增长。

只保留聊天记录（[astrbot.group_chat_context: 行），格式：
  [时间] [Plug] [DBUG] [astrbot.group_chat_context:158]:
      group_chat_context | pre-config:GroupMessage:<群号> | [<昵称>/<时间>]: <内容>
"""
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except ImportError:  # 兼容旧版本 AstrBot
    def get_astrbot_data_path() -> str:
        return os.path.realpath(os.path.join(os.getcwd(), "data"))

# 聊天记录行（行首锚定正则，避免误匹配 openai 请求日志中嵌入的对话历史文本）。
# 注意：不能用裸 "group_chat_context" 子串，因为 LLM 请求日志里也会出现该字样。
# event_bus 行([core.event_bus:74])与 group_chat_context 行记录同一条消息，
# 保留会导致重复，因此只匹配 group_chat_context 行。
CHAT_RE = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+\] "
    r"\[Plug\] \[DBUG\] \[astrbot\.group_chat_context:\d+\]: "
    r"group_chat_context \| pre-config:GroupMessage:\d+ \| \["
)
LINE_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) \d{2}:\d{2}:\d{2}")
GROUP_ID_RE = re.compile(r"pre-config:GroupMessage:(\d+)")
QQ_ID_RE = re.compile(r"\((\d{6,12})\)")


class GroupLogArchive(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._scheduler: AsyncIOScheduler | None = None
        self._lock = asyncio.Lock()
        self._state: dict = {}
        self._load_state()

    # ---------------- 路径解析 ----------------
    def _log_dir(self) -> str:
        cfg = (self.config.get("log_dir", "") or "").strip()
        if cfg:
            return os.path.realpath(cfg)
        return os.path.join(get_astrbot_data_path(), "logs")

    def _out_dir(self) -> str:
        cfg = (self.config.get("output_dir", "") or "").strip()
        if cfg:
            return os.path.realpath(cfg)
        return os.path.join(get_astrbot_data_path(), "workspaces", "group_logs")

    @property
    def _log_prefix(self) -> str:
        return self.config.get("log_prefix", "astrbot.log")

    @property
    def _state_file(self) -> str:
        return os.path.join(self._out_dir(), ".export_state.json")

    # ---------------- 状态持久化 ----------------
    def _load_state(self) -> None:
        try:
            if os.path.exists(self._state_file):
                with open(self._state_file, encoding="utf-8") as f:
                    self._state = json.load(f)
        except Exception as e:
            logger.warning(f"[GroupLogArchive] 读取状态文件失败: {e}")
            self._state = {}

    def _save_state(self) -> None:
        os.makedirs(self._out_dir(), exist_ok=True)
        tmp = self._state_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
            try:
                os.replace(tmp, self._state_file)
            except OSError:
                # 部分文件系统（Android proot/FUSE）不支持 rename
                with open(self._state_file, "w", encoding="utf-8") as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[GroupLogArchive] 保存状态失败: {e}")

    # ---------------- 过滤与路由 ----------------
    def _is_chat_line(self, line: str) -> bool:
        if not self.config.get("only_chat", True):
            return True
        return bool(CHAT_RE.match(line))

    def _route_line(self, line: str, fallback_date: str) -> str:
        """按行首时间戳 + 群号路由到对应文件（分群、按天）"""
        m = LINE_TS_RE.match(line)
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        else:
            date = fallback_date
        gm = GROUP_ID_RE.search(line)
        gid = gm.group(1) if gm else "unknown"
        if self.config.get("mask_group_id", False) and gid != "unknown":
            gid = self._mask_id(gid)
        return os.path.join(self._out_dir(), f"astrbot_{gid}_{date}.log")

    def _mask_id(self, value: str) -> str:
        """群号哈希脱敏（md5 前 10 位）"""
        return hashlib.md5(value.encode("utf-8")).hexdigest()[:10]

    def _sanitize(self, text: str) -> str:
        """按配置对日志行做脱敏处理"""
        if self.config.get("mask_group_id", False):
            text = GROUP_ID_RE.sub(
                lambda m: f"pre-config:GroupMessage:{self._mask_id(m.group(1))}", text
            )
        if self.config.get("mask_qq_id", False):
            # QQ 号常出现在引用的括号中，如 (10001)
            text = QQ_ID_RE.sub(
                lambda m: f"({m.group(1)[:3]}****{m.group(1)[-3:]})", text
            )
        return text

    # ---------------- 增量导出 ----------------
    def _export_file(self, path: str, state_key: str) -> int:
        """增量导出单个日志文件，返回写入归档的字节数"""
        if not os.path.exists(path):
            return 0
        try:
            inode = os.stat(path).st_ino
        except OSError:
            return 0
        size = os.path.getsize(path)
        prev = self._state.get(state_key, {})
        prev_inode = prev.get("inode")
        offset = prev.get("offset", 0)

        # 文件被轮转/重建（inode 变了或文件变小了）→ 旧内容已导出，从头开始
        if prev_inode is not None and (prev_inode != inode or size < offset):
            offset = 0
            logger.info(f"[GroupLogArchive] 检测到日志轮转/重建: {path}")

        if size <= offset:
            return 0

        fallback_date = datetime.fromtimestamp(
            os.path.getmtime(path)
        ).strftime("%Y-%m-%d")
        exported = 0
        read_pos = offset  # 物理读取位置（过滤后必须按此更新，否则会错位）
        os.makedirs(self._out_dir(), exist_ok=True)
        with open(path, "rb") as f:
            f.seek(offset)
            buf = b""
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    read_pos += len(line) + 1
                    text = line.decode("utf-8", errors="replace")
                    if not self._is_chat_line(text):
                        continue
                    target = self._route_line(text, fallback_date)
                    text = self._sanitize(text)
                    with open(target, "a", encoding="utf-8") as out:
                        out.write(text + "\n")
                    exported += len(line) + 1
            # 剩余不带换行的尾部
            if buf:
                read_pos += len(buf)
                text = buf.decode("utf-8", errors="replace")
                if self._is_chat_line(text):
                    target = self._route_line(text, fallback_date)
                    text = self._sanitize(text)
                    with open(target, "a", encoding="utf-8") as out:
                        out.write(text + "\n")
                    exported += len(buf)

        self._state[state_key] = {"inode": inode, "offset": read_pos}
        return exported

    def _export_all(self) -> int:
        """导出当前所有日志文件（含轮转），返回写入归档的字节数"""
        total = 0
        log_dir = self._log_dir()
        if not os.path.isdir(log_dir):
            return 0
        prefix = self._log_prefix
        files = [
            f for f in os.listdir(log_dir) if f == prefix or f.startswith(prefix + ".")
        ]
        files.sort()  # astrbot.log, astrbot.log.1, ...
        for name in files:
            path = os.path.join(log_dir, name)
            try:
                total += self._export_file(path, name)
            except Exception as e:
                logger.warning(f"[GroupLogArchive] 导出 {name} 出错: {e}")
        self._save_state()
        return total

    def _clean_source(self) -> None:
        """导出后清理源日志：
        - 活跃日志用清空(truncate)而非删除——AstrBot(loguru)持有其句柄，
          直接删除会导致日志写入不可见 inode，浪费磁盘。
        - 轮转文件(.1/.2...)不再被写入，直接删除。
        """
        log_dir = self._log_dir()
        prefix = self._log_prefix
        if not os.path.isdir(log_dir):
            return
        for name in os.listdir(log_dir):
            if name != prefix and not name.startswith(prefix + "."):
                continue
            path = os.path.join(log_dir, name)
            try:
                if name == prefix:
                    with open(path, "w"):
                        pass
                    logger.debug(f"[GroupLogArchive] 已清空源日志: {path}")
                else:
                    os.remove(path)
                    logger.debug(f"[GroupLogArchive] 已删除轮转日志: {path}")
            except OSError as e:
                logger.warning(f"[GroupLogArchive] 清理 {path} 失败: {e}")

    # ---------------- 定时任务 ----------------
    async def _tick(self) -> None:
        try:
            async with self._lock:
                n = await asyncio.to_thread(self._export_all)
                if n:
                    logger.info(f"[GroupLogArchive] 增量导出 {n} 字节")
                if self.config.get("clean_source", True):
                    await asyncio.to_thread(self._clean_source)
        except Exception as e:
            logger.error(f"[GroupLogArchive] 导出任务异常: {e}")

    # ---------------- 生命周期 ----------------
    async def initialize(self) -> None:
        cron_expr = str(self.config.get("cron_expression", "") or "").strip()
        # 支持简单时间格式 HH:MM（如 12:00 = 每天中午12点）
        m = re.match(r"^(\d{1,2}):(\d{2})$", cron_expr)
        if m:
            cron_expr = f"{int(m.group(2))} {int(m.group(1))} * * *"
        interval = max(int(self.config.get("poll_interval", 60)), 5)
        self._scheduler = AsyncIOScheduler()
        if cron_expr:
            try:
                trigger = CronTrigger.from_crontab(cron_expr)
                self._scheduler.add_job(
                    self._tick,
                    trigger,
                    id="group_log_archive_cron",
                    max_instances=1,
                    coalesce=True,
                )
                logger.info(
                    f"[GroupLogArchive] 已启动 | 源: {self._log_dir()}/{self._log_prefix}* "
                    f"→ {self._out_dir()} | cron: {cron_expr}"
                )
            except Exception as e:
                logger.error(
                    f"[GroupLogArchive] cron 表达式无效({cron_expr})，回退到间隔模式: {e}"
                )
                self._scheduler.add_job(
                    self._tick,
                    "interval",
                    seconds=interval,
                    id="group_log_archive_tick",
                    max_instances=1,
                    coalesce=True,
                )
        else:
            self._scheduler.add_job(
                self._tick,
                "interval",
                seconds=interval,
                id="group_log_archive_tick",
                max_instances=1,
                coalesce=True,
            )
        self._scheduler.start()
        logger.info(
            f"[GroupLogArchive] 定时任务已启动 | 间隔 {interval}s"
            if not cron_expr
            else f"[GroupLogArchive] 定时任务已启动 | cron {cron_expr}"
        )
        # 启动后立即跑一次
        asyncio.create_task(self._tick())

    async def terminate(self) -> None:
        try:
            if self._scheduler:
                self._scheduler.shutdown(wait=False)
        except Exception as e:
            logger.warning(f"[GroupLogArchive] 关闭调度器失败: {e}")
        # 卸载前做最终导出，保证数据完整性
        try:
            async with self._lock:
                n = await asyncio.to_thread(self._export_all)
                logger.info(f"[GroupLogArchive] 最终导出完成，本次 {n} 字节")
        except Exception as e:
            logger.error(f"[GroupLogArchive] 最终导出失败: {e}")

    # ---------------- 指令 ----------------
    @filter.command("log_archive")
    async def log_archive(self, event: AstrMessageEvent):
        args = (event.message_str or "").split()
        sub = args[1].strip().lower() if len(args) > 1 else "status"

        if sub == "help":
            yield event.plain_result(
                "群聊日志归档插件指令：\n"
                "/log_archive status - 查看状态\n"
                "/log_archive now - 立即导出一轮\n"
                "/log_archive clean - 手动清空源日志\n"
                "/log_archive help - 显示帮助"
            )
            return

        if sub == "now":
            async with self._lock:
                n = await asyncio.to_thread(self._export_all)
            if self.config.get("clean_source", True):
                await asyncio.to_thread(self._clean_source)
            yield event.plain_result(f"已导出 {n} 字节到 {self._out_dir()}")
            return

        if sub == "clean":
            await asyncio.to_thread(self._clean_source)
            yield event.plain_result("已清空源日志")
            return

        # status
        out_dir = self._out_dir()
        total = 0
        dates = []
        try:
            for name in sorted(os.listdir(out_dir)):
                if name.startswith("astrbot_") and name.endswith(".log"):
                    path = os.path.join(out_dir, name)
                    total += os.path.getsize(path)
                    dates.append(f"{name}({os.path.getsize(path)//1024}KB)")
        except OSError:
            pass
        yield event.plain_result(
            f"群聊日志归档状态：\n"
            f"源: {self._log_dir()}/{self._log_prefix}*\n"
            f"归档: {out_dir}（共 {total//1024}KB）\n"
            f"文件: {', '.join(dates) if dates else '无'}"
        )
