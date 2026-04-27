import json
import os
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
import logging
import asyncio
from typing import List, Dict, Optional
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


==================== 配置区 ====================
class Config:
    """插件配置类"""
    def init(self, context: Context):
        self.context = context
        plugin_dir = context.plugin_dir
        config_path = os.path.join(plugin_dir, "config.json")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self.raw_config = json.load(f)
        
        self.bilibili_uid = self.raw_config.get("bilibili_uid", "").strip()
        self.schedule = self.raw_config.get("schedule", "0 2 * * *")
        self.llm_config = self.raw_config.get("llm_config", {})
        self.knowledge_dir = self.raw_config.get("knowledge_dir", "data/knowledge/geng")
        self.max_videos = self.raw_config.get("max_videos_per_run", 3)
        self.cookies = self.raw_config.get("cookies", "")
        self.only_subtitle = self.raw_config.get("only_has_subtitle", True)

        # 确保目录存在
        os.makedirs("logs", exist_ok=True)
        os.makedirs(self.knowledge_dir, exist_ok=True)
        
        if not self.bilibili_uid:
            raise ValueError("config.json 中 bilibili_uid 为空，请填写UP主UID")
    
    def get_llm_model(self) -> str:
        """获取LLM模型名，无效时回退到AstrBot全局模型"""
        model_name = self.llm_config.get("model", "").strip()
        if not model_name or model_name == "gpt-3.5-turbo-placeholder":
            try:
                default_model = self.context.get_config().get("model", "gpt-3.5-turbo")
                logger.warning(f"配置的模型无效，已自动回退到AstrBot全局模型: {default_model}")
                return default_model
            except:
                return "gpt-3.5-turbo"
        return model_name


==================== 日志配置 ====================
def setup_logging():
    """设置日志轮转，每天新建日志文件，保留7天"""
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler = TimedRotatingFileHandler(
        "logs/geng_fetcher.log", when='midnight', interval=1, backupCount=7, encoding='utf-8'
    )
    handler.setFormatter(formatter)
    logger_obj = logging.getLogger("BiliGengFetcher")
    logger_obj.setLevel(logging.INFO)
    logger_obj.addHandler(handler)
    return logger_obj

logger = setup_logging()


==================== B站抓取 ====================
class BiliFetcher:
    """B站视频抓取器，带超时、重试、限频"""
    def init(self, uid: str, cookies: str = ""):
        self.uid = uid
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Cookie": cookies
        }
        self.last_req = 0
        self.min_interval = 6  # 限频10次/分钟

    def _rate_limit(self):
        now = time.time()
        if now - self.last_req < self.min_interval:
            time.sleep(self.min_interval - (now - self.last_req))
        self.last_req = time.time()

    def get_latest_videos(self, limit: int) -> List[Dict]:
        """获取UP主最新视频列表，3次重试"""
        url = f"https://api.bilibili.com/x/space/arc/search?mid={self.uid}&ps={limit}&tid=0&pn=1"
        for attempt in range(3):
            try:
                self._rate_limit()
                resp = requests.get(url, headers=self.headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") == 0:
                    videos = data.get("data", {}).get("list", {}).get("vlist", [])
                    return [{"bvid": v["bvid"], "title": v["title"], "desc": v.get("desc", ""), "pubdate": v["pubdate"]} for v in videos]
                else:
                    logger.warning(f"API错误码: {data.get('code')}")
                    return []
            except Exception as e:
                logger.warning(f"获取视频列表失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    logger.error("获取视频列表失败3次，放弃")
                    return []
                time.sleep(2  attempt)  # 指数退避

    def get_video_detail(self, bvid: str) -> Optional[Dict]:
        """获取单个视频详情（简介、字幕）"""
        video_url = f"https://www.bilibili.com/video/{bvid}"
        for attempt in range(3):
            try:
                self._rate_limit()
                resp = requests.get(video_url, headers=self.headers, timeout=60)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, 'html.parser')
                desc_meta = soup.find('meta', attrs={'name': 'description'})
                desc = desc_meta.get('content', '') if desc_meta else ""
                has_subtitle = "CC字幕" in resp.text
                return {"bvid": bvid, "description": desc, "has_subtitle": has_subtitle}
            except Exception as e:
                logger.warning(f"获取视频 {bvid} 详情失败 (尝试 {attempt+1}/3): {e}")
                if attempt == 2:
                    logger.error(f"视频 {bvid} 获取失败3次，仅简介模式")
                    return {"bvid": bvid, "description": "", "has_subtitle": False}
                time.sleep(2  attempt)


==================== LLM总结 ====================
class LLMSummarizer:
    """LLM总结器，带模型回退"""
    def init(self, config: Config):
        self.config = config
        self.model_name = config.get_llm_model()
        self.api_base = config.llm_config.get("api_base", "")
        self.api_key = config.llm_config.get("api_key", "")

    def summarize_geng(self, video_info: Dict) -> Optional[str]:
        """将视频信息总结成梗点"""
        prompt = f"""你是一名梗百科分析师，请帮我总结这个视频的核心梗点。
视频标题：{video_info['title']}
视频简介：{video_info['description']}
请用3句话内总结这个视频的核心梗点和笑点，要求：
1. 简洁准确，抓住重点
2. 不超过180个字
3. 用中文回答"""
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.3
            }
            resp = requests.post(f"{self.api_base}/chat/completions", headers=headers, json=payload, timeout=900)
            resp.raise_for_status()
            summary = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            return summary.strip() if summary else None
        except Exception as e:
            logger.error(f"LLM总结失败: {e}")
            return None


==================== 知识库存储 ====================
class KnowledgeStorage:
    """知识库存储，带权限检查"""
    def init(self, storage_dir: str):
        self.storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def save_knowledge(self, bvid: str, video_info: Dict, summary: Optional[str]):
        """保存梗点到知识库"""
        filename = f"{datetime.now().strftime('%Y-%m-%d')}.md"
        filepath = os.path.join(self.storage_dir, filename)
        if not summary:
            content = f"## 视频 {bvid}\n标题: {video_info['title']}\n简介: {video_info['description']}\n备注: 总结失败，保留原始信息\n"
        else:
            content = f"## 视频 {bvid}\n标题: {video_info['title']}\n梗点: {summary}\n"
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(content + "\n\n")
            logger.info(f"知识已写入: {filepath}")
        except Exception as e:
            logger.error(f"写入知识库失败: {e}")
            print(f"错误: 无法写入知识库 {filepath}: {e}")


==================== 插件主类 ====================
@register("bili_geng_plugin", "白明", "B站梗百科自动抓取并总结到知识库", "1.0.0")
class BiliGengPlugin(Star):
    """B站梗百科插件主类"""
    
    def init(self, context: Context):
        super().init(context)
        self.config = Config(context)
        self.config = Config(context)
        self.fetcher = BiliFetcher(self.config.bilibili_uid, self.config.cookies)
        self.summarizer = LLMSummarizer(self.config)
        self.storage = KnowledgeStorage(self.config.knowledge_dir)
        self.last_run_file = os.path.join(self.context.plugin_dir, "logs/last_run.json")

    async def initialize(self):
        """插件初始化：注册定时任务"""
        logger.info("B站梗百科插件初始化")
        try:
            # 注册定时任务
            from astrbot.core.scheduler import Scheduler
            scheduler = Scheduler()
            scheduler.add_cron_job(self.run, self.config.schedule)
            logger.info(f"已注册定时任务: {self.config.schedule}")
        except Exception as e:
            logger.error(f"注册定时任务失败: {e}")
    
    async def run(self):
        """主运行逻辑"""
        logger.info("B站梗百科插件开始运行")
        start = datetime.now()
        record = {"start": start.isoformat(), "status": "running", "processed": 0, "failed": 0, "errors": []}
        
        try:
            videos = self.fetcher.get_latest_videos(self.config.max_videos)
            logger.info(f"获取到 {len(videos)} 个视频")
            
            for video in videos:
                try:
                    detail = self.fetcher.get_video_detail(video['bvid'])
                    if not detail:
                        record["failed"] += 1
                        continue
                    if self.config.only_subtitle and not detail['has_subtitle']:
                        logger.info(f"视频 {video['bvid']} 无字幕，跳过")
                        continue
                    video.update(detail)
                    summary = self.summarizer.summarize_geng(video)
                    self.storage.save_knowledge(video['bvid'], video, summary)
                    record["processed"] += 1
                except Exception as e:
                    logger.error(f"处理视频失败: {e}")
                    record["failed"] += 1
                    record["errors"].append(str(e))
            
            record["status"] = "success"
        except Exception as e:
            logger.error(f"插件运行失败: {e}")
            record["status"] = "failed"
            record["errors"].append(str(e))
        finally:
            record["end"] = datetime.now().isoformat()
            try:
                with open(self.last_run_file, 'w', encoding='utf-8') as f:
                    json.dump(record, f, ensure_ascii=False, indent=2)
            except:
                pass
            logger.info(f"完成：成功 {record['processed']}，失败 {record['failed']}")

    async def terminate(self):
        """插件销毁（卸载时调用）"""
        logger.info("B站梗百科插件卸载")


==================== 手动触发命令 ====================
@filter.command("geng_update")
async def cmd_geng_update(event: AstrMessageEvent, ctx: Context):
    """手动触发梗百科更新"""
    logger.info("收到手动触发指令 /geng_update")
    try:
        plugin = BiliGengPlugin(ctx)
        await plugin.run()
        yield event.plain_result("梗百科知识更新完成，请查看日志了解详情")
    except Exception as e:
        yield event.plain_result(f"更新失败: {e}")