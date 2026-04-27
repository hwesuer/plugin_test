# plugin_test
Repository for plugin testing only. The availability and stability of the content are not guaranteed.
B站梗百科插件

功能：定时抓取B站梗百科视频，提取字幕/简介，用LLM总结成梗点，存入知识库

配置

1. 修改 config.json 中的 bilibili_uid
2. 配置 llm_config 里的API地址和模型
3. 运行前确保LLM服务可用

安装

bash
在插件目录下
pip install -r requirements.txt
使用
重启AstrBot自动加载
定时任务每天凌晨2点执行（可在config改）
手动触发：发消息 "/geng_update"
