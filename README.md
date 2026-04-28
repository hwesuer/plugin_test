# 关键词屏蔽插件 (BlockWords)

AstrBot 插件：当用户发送的消息**完全匹配**预设屏蔽词时，拦截该消息使其不发送给 LLM。

## 功能

- 自动拦截与屏蔽词**完全匹配**的消息（不是子串匹配）
  - 屏蔽词为 `"好"` → 拦截 `"好"`，放行 `"好我这就去"`
  - 屏蔽词为 `"ok"` → 拦截 `"ok"`，放行 `"token"`
- 默认屏蔽词：`好`
- 支持通过 `_conf_schema.json` 预设初始关键词，也支持指令动态管理
- 可配置静默屏蔽（不回复）或提示屏蔽
- 屏蔽词持久化存储，重启后保留

## 配置

插件的 `_conf_schema.json` 提供以下配置项，可在 AstrBot 管理面板中修改：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `keywords` | list | `["好"]` | 初始屏蔽关键词列表 |
| `silent_block` | bool | `true` | 是否静默屏蔽（`true`=不回复，`false`=提示发送者） |

## 使用

| 命令 | 说明 |
|------|------|
| `/blockword add <关键词>` | 添加屏蔽词 |
| `/blockword remove <关键词>` | 移除屏蔽词 |
| `/blockword list` | 查看所有屏蔽词 |
| `/blockword sync` | 从 `_conf_schema.json` 配置重新同步

### 示例

```
/blockword add ok
> 已添加屏蔽词: ok

/blockword list
> 当前屏蔽关键词（2个）: 好, ok

/blockword remove 好
> 已移除屏蔽词: 好
```

## 匹配规则

- **完全匹配**：用户发送的消息去掉首尾空格后，必须与屏蔽词逐字符一致才拦截
- 指令消息（以 `/` 开头）不会被拦截
- 大小写敏感（`ok` 和 `OK` 是不同的关键词）

## 数据存储

- 插件默认从 `_conf_schema.json` 的 `keywords` 读取屏蔽词
- 执行 `/blockword add` 或 `/blockword remove` 后，屏蔽词会持久化到 `data/astrbot_plugin_blockwords_data.json`
- 数据文件存在时，以文件为准；若文件内容与配置完全一致，插件会判定为旧版自动生成的数据，自动删除并切回配置管理模式
- 可用 `/blockword sync` 随时从配置重新同步
