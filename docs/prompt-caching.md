# Claude API Prompt Caching 原理与命中排查

使用 Claude Code 或自建多轮对话应用时，提示词缓存（Prompt Caching）的命中率往往比单次输入单价更能决定最终账单。本文依据 Anthropic 官方文档整理其工作机制、计费规则、最小长度限制及不命中排查方法。

## 一、缓存如何工作

多轮对话每一轮都会把历史上下文重新发送给模型。缓存按请求**前缀**精确匹配，顺序固定为：

`tools → system → messages`

只要前缀中有一个字节发生变化，从变化位置往后的内容都需要重新写入缓存；未变化的前缀直接从缓存读取。

### 两种标记方式

1. **自动缓存（Automatic caching）**：在请求体顶层加一个 `"cache_control": {"type": "ephemeral"}`，系统会自动把缓存断点放在最后一个可缓存块上，并随对话增长自动前移。适合多轮对话。
2. **显式断点（Explicit breakpoints）**：直接把 `cache_control` 放在具体的 `system`、`tools` 或 `messages` 内容块上，单个请求最多 4 个断点。两者也可混用（共占 4 个断点名额）。

## 二、计费与有效期（截至 2026 年 11 月）

| 操作 | 费率（相对基础输入价） | 说明 |
|---|---|---|
| 5 分钟缓存写入 | 1.25 倍 | 默认有效期 5 分钟，每次命中重新计时 |
| 1 小时缓存写入 | 2 倍 | 适合两轮间隔 5–60 分钟的场景 |
| 缓存读取（命中） | 大多数模型 0.1 倍；Opus 5.5 / Sonnet 5.5 为 0.05 倍；Fable 5.2 为 0.025 倍 | 读取同时刷新 TTL |

- 5 分钟缓存：写完后只要被命中 1 次即回本。
- 1 小时缓存：写完后被命中 2 次即回本。

## 三、最小可缓存长度（不达标静默跳过）

低于最小长度的前缀即使标记了 `cache_control` 也不会被缓存，且 **API 不会报错**（只会看到 `cache_creation_input_tokens` 与 `cache_read_input_tokens` 均为 0）：

| 最小长度 | 适用模型 |
|---|---|
| 512 tokens | Claude Fable 5.2 / 5.1 / 5、Opus 5.5 / 5、Sonnet 5.5、Haiku 5.5 等 |
| 1,024 tokens | Claude Opus 4.8、Sonnet 5、Sonnet 4.6 |
| 2,048 tokens | Claude Opus 4.7 |
| 4,096 tokens | Claude Opus 4.6、Haiku 4.5 |

## 四、如何验证是否命中

查看响应 JSON 的 `usage` 字段（或使用仓库根目录的 [`check_relay.py`](../check_relay.py)）：

```json
{
  "usage": {
    "input_tokens": 120,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 32000
  }
}
```

- `cache_creation_input_tokens > 0`：本次写入了新缓存。
- `cache_read_input_tokens > 0`：本次命中了已有缓存。
- 若使用 OpenAI 兼容格式，缓存读取数通常在 `prompt_tokens_details.cached_tokens` 中查看。

### 常见不命中原因排查

1. **系统提示中含动态字段**：例如每次请求拼入当前时间戳、请求 UUID，导致前缀每次都变。
2. **改动了历史消息或工具顺序**：编辑早期对话或重排 `tools` 数组会使后续缓存全部失效。
3. **请求间隔超过 5 分钟**：未指定 1 小时 TTL 时，超时后缓存过期需重新写入。
4. **前缀长度不足最小阈值**：短提示词不会触发缓存。
5. **多并发单轮任务**：彼此无共享前缀时，应将公共的长指令/示例放到最前并加断点。

## 参考

- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

以官方页面为准，本文数字截至 2026 年 11 月。
