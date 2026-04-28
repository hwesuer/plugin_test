import os
import json
import logging

from astrbot.api import AstrBotConfig
from astrbot.api.all import AstrMessageEvent, CommandResult, Context
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

logger = logging.getLogger("astrbot")

PLUGIN_NAME = "astrbot_plugin_blockwords"
DEFAULT_KEYWORDS = ["好"]  # 硬编码默认关键词，与 _conf_schema.json 保持一致


@register(PLUGIN_NAME, "User", "关键词屏蔽插件：消息完全匹配屏蔽词时拦截，不发送给LLM", "1.0.0")
class BlockWords(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.keywords = []
        
        # 使用插件自身目录下的 data 文件夹存储数据文件（确保路径唯一）
        data_dir = os.path.join(self.plugin_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        self.data_file = os.path.join(data_dir, f"{PLUGIN_NAME}_data.json")
        
        # 优先从数据文件加载，如果文件不存在则从配置加载并保存
        if os.path.exists(self.data_file):
            self._load_from_file()
        else:
            self._load_from_config()
            # 如果从配置也没加载到任何关键词，则使用硬编码默认值
            if not self.keywords:
                self.keywords = DEFAULT_KEYWORDS.copy()
                logger.info(f"[BlockWords] 使用硬编码默认屏蔽词: {self.keywords}")
            self._save_data_file()

    def _load_from_file(self):
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.keywords = data.get("keywords", [])
            logger.info(f"[BlockWords] 从数据文件加载 {len(self.keywords)} 个屏蔽关键词")
        except Exception as e:
            logger.error(f"[BlockWords] 读取数据文件失败: {e}")
            self._load_from_config()

    def _load_from_config(self):
        raw = self.config.get("keywords", [])
        if isinstance(raw, list):
            self.keywords = [str(k).strip() for k in raw if str(k).strip()]
        elif isinstance(raw, str) and raw.strip():
            self.keywords = [k.strip() for k in raw.split(",") if k.strip()]
        else:
            self.keywords = []
        logger.info(f"[BlockWords] 从配置加载 {len(self.keywords)} 个屏蔽关键词")

    def _save_data_file(self):
        try:
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump({"keywords": self.keywords}, f, ensure_ascii=False, indent=2)
            logger.debug(f"[BlockWords] 数据已保存至 {self.data_file}")
        except Exception as e:
            logger.error(f"[BlockWords] 保存数据文件失败: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message_check(self, message: AstrMessageEvent):
        message_str = message.message_str.strip()
        if message_str.startswith("/"):
            return
        if self.keywords and message_str in self.keywords:
            logger.info(f"[BlockWords] 已屏蔽消息: \"{message_str}\"")
            if self.config.get("silent_block", True):
                return CommandResult()
            else:
                return CommandResult().message(f"消息已被屏蔽: {message_str}")

    @filter.command("屏蔽词")
    @filter.command("blockword")
    async def blockword(self, message: AstrMessageEvent):
        message_str = message.message_str.strip()
        # 去除命令前缀（装饰器已处理，但为了兼容保留）
        for prefix in ("/屏蔽词", "/blockword"):
            if message_str.startswith(prefix):
                message_str = message_str[len(prefix):].strip()
                break

        if not message_str:
            return CommandResult().message(
                "关键词屏蔽插件 — 消息完全匹配屏蔽词时拦截，不发送给LLM\n\n"
                "用法:\n"
                "/blockword add <关键词> — 添加屏蔽词\n"
                "/blockword remove <关键词> — 移除屏蔽词\n"
                "/blockword list — 查看所有屏蔽词"
            ).use_t2i(False)

        parts = message_str.split(maxsplit=1)
        subcmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "add":
            if not arg:
                return CommandResult().message("错误：请指定要添加的关键词，例如: /blockword add 好")
            if arg in self.keywords:
                return CommandResult().message(f"屏蔽词已存在: {arg}")
            self.keywords.append(arg)
            self._save_data_file()
            return CommandResult().message(f"已添加屏蔽词: {arg}")

        elif subcmd in ("remove", "del", "delete"):
            if not arg:
                return CommandResult().message("错误：请指定要移除的关键词，例如: /blockword remove 好")
            if arg in self.keywords:
                self.keywords.remove(arg)
                self._save_data_file()
                return CommandResult().message(f"已移除屏蔽词: {arg}")
            else:
                return CommandResult().message(f"未找到屏蔽词: {arg}")

        elif subcmd in ("list", "ls", "show"):
            if self.keywords:
                return CommandResult().message(
                    f"当前屏蔽关键词（{len(self.keywords)}个）: {', '.join(self.keywords)}"
                ).use_t2i(False)
            else:
                return CommandResult().message("当前无屏蔽关键词")

        else:
            return CommandResult().message("错误：未知子命令，有效命令为 add / remove / list")

    async def terminate(self):
        self._save_data_file()
        logger.info("[BlockWords] 插件已卸载，数据已保存")