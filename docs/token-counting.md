# Claude API Token 计数与上下文预算指南

在发正式请求前算清 token 消耗，可以避免意外触及速率限制、上下文窗口上限或高额长提示账单。本文依据 Anthropic 官方文档，整理新版分词器差异、免费预计算接口 `/v1/messages/count_tokens` 的用法，以及工具定义、图片、PDF 和思考块的隐藏 token 开销。

## 一、分词器版本差异：为什么同一段话 token 数会变

Claude 4.7 及后续模型（含 Opus 4.7/4.8/5/5.5、Sonnet 5/5.5、Haiku 5.5、Fable 5/5.1/5.2、Mythos 5/5.1/5.2）以及 Claude Mythos Preview 使用了新版分词器。

- **体积差异**：同一段输入文本，在新版分词器下产生的 token 数比 Claude Sonnet 4.6 及更早模型**大约多 30%**（具体增幅取决于文本内容与语言形态）。
- **迁移注意**：从 Claude Sonnet 4.6 或更早模型迁移到 Claude 4.7+、Fable 或 Mythos 系列时，不要直接沿用旧模型测出的 token 数来估算费用或上下文窗口余量，应当传入目标模型的 `model` ID 重新计数。

## 二、用 `/v1/messages/count_tokens` 免费预计算

官方提供专门的计数接口，在真正生成回复前就能返回完整的 `input_tokens` 估算值，支持 `system`、客户端 `tools`、`thinking`、base64 编码的图片和 PDF。

### 费用与独立限流（截至 2026 年 11 月）

- **接口免费**：调用 `/v1/messages/count_tokens` 不收取 token 费用。
- **独立限流**：与创建消息接口 `/v1/messages` 各自计算速率限制，互不占用配额。官方每分钟请求数（RPM）上限按账号等级划分：

| 用量等级（Usage tier） | 计数接口限流（RPM） |
|---|---|
| Start | 5,000 |
| Build | 10,000 |
| Scale | 20,000 |

### 适用边界与注意事项

- **计数结果是估算值**：实际调用 `/v1/messages` 时的 `input_tokens` 可能存在小幅差异；返回结果可能包含系统优化自动附加的 token，但计费仅按用户自身发送的内容计算。
- **以下输入会返回 `invalid_request_error`**：除 advisor tool 外的服务端工具（如 web search、web fetch、code execution、tool search）、MCP connector、以及使用 `url` 或 `file` 作为来源的 `image` / `document` 块。这类场景下图片和 PDF 需改用 base64 传入计数，或直接从 `/v1/messages` 响应的 `usage` 字段读取实际消耗。
- **不触发缓存**：请求中可以保留 `cache_control` 字段，但计数接口不会执行实际的缓存写入或读取。

### 可复制调用示例

#### 1. `curl` 计数基础文本与 `system` 提示

```bash
curl -sS https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2026-10-21" \
  -d '{
    "model": "claude-opus-5-5",
    "system": "You are a scientist",
    "messages": [
      {"role": "user", "content": "Hello, Claude"}
    ]
  }'
```

官方示例返回格式：

```json
{ "input_tokens": 14 }
```

#### 2. Python SDK 对比新旧模型分词差异

```python
import anthropic

client = anthropic.Anthropic()
text = "把需要估算的中文或英文提示词放在这里。"

for model in ("claude-sonnet-4-6", "claude-sonnet-5-5"):
    resp = client.messages.count_tokens(
        model=model,
        messages=[{"role": "user", "content": text}],
    )
    print(model, resp.input_tokens)
```

#### 3. 计数带工具定义的请求（`curl`）

```bash
curl -sS https://api.anthropic.com/v1/messages/count_tokens \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "content-type: application/json" \
  -H "anthropic-version: 2026-10-21" \
  -d '{
    "model": "claude-opus-5-5",
    "tools": [
      {
        "name": "get_weather",
        "description": "Get the current weather in a given location",
        "input_schema": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "The city and state, e.g. San Francisco, CA"
            }
          },
          "required": ["location"]
        }
      }
    ],
    "messages": [
      {"role": "user", "content": "What'\''s the weather like in San Francisco?"}
    ]
  }'
```

## 三、工具、图片、PDF 与思考块的隐藏 Token 开销

很多开发者只算了纯文本提示词，实际账单却多出几千 token，通常来自以下四类结构化内容（数字截至 2026 年 11 月）。

### 1. 工具定义附加的系统提示词

请求中只要包含至少 1 个工具（`tools` 数组非空），除了工具的名称、描述、JSON Schema 以及对话中的 `tool_use` / `tool_result` 内容块之外，API 还会自动注入一段启用工具调用的系统提示词：

| 模型 | `tool_choice` 为 `auto` 或 `none` | `tool_choice` 为 `any` 或 `tool` |
|---|---|---|
| Claude Opus 5.5 / Sonnet 5.5 | 286 tokens | 官方未单列（以响应 `usage` 为准） |
| Claude Haiku 5.5 | 286 tokens | 406 tokens |
| Claude Sonnet 5 | 354 tokens | 474 tokens |
| Claude Opus 4.8 | 290 tokens | 410 tokens |
| Claude Opus 4.7 | 675 tokens | 804 tokens |
| Claude Sonnet 4.6 / Opus 4.6 | 497 tokens | 589 tokens |
| Claude Haiku 4.5 | 496 tokens | 588 tokens |

如果使用了 Anthropic 内置工具，在通用工具系统提示词之外还会产生固定定义开销：

- **Bash 工具**：Claude 4.7 及以上模型与 Mythos Preview 附加 **325 tokens**；Claude 4.6 及更早模型附加 **244 tokens**。
- **Text editor 工具（`text_editor_20250728`）**：Claude 4.7 及以上模型与 Mythos Preview 附加 **974 tokens**；Claude 4.6 及更早模型附加 **745 tokens**。
- **Web fetch 网页抓取常见体积参考**：普通网页（10 kB）约 2,500 tokens；大型文档页（100 kB）约 25,000 tokens；研究论文 PDF（500 kB）约 125,000 tokens。建议配合 `max_content_tokens` 限制抓取上限。

### 2. 图片（Vision）按 28×28 像素块计数

Claude 支持 `image/jpeg`、`image/png`、`image/gif`、`image/webp`（动态图仅取首帧）。图片按 28×28 像素切片为视觉 token，计算公式为：

`视觉 token 数 = ceil(宽度 / 28) × ceil(高度 / 28)`

不同模型对应两档默认分辨率上限（超过长边或视觉 token 上限的图片会被自动等比缩小）：

| 分辨率档位 | 适用模型 | 最大长边 | 单图最大视觉 token |
|---|---|---|---|
| 高分辨率（High-resolution） | Claude 4.7 及以上模型 | 2,576 px | 4,784 |
| 标准（Standard） | 其他更早模型 | 1,568 px | 1,568 |

常见尺寸实算对照：

| 原始尺寸 | 标准档缩放后 / token | 高分辨率档缩放后 / token |
|---|---|---|
| 1000×1000 px | 不缩放 / 1,296 | 不缩放 / 1,296 |
| 1920×1080 px | 1456×819 px / 1,560 | 不缩放 / 2,691 |
| 2000×1500 px | 1269×952 px / 1,564 | 不缩放 / 3,888 |
| 3840×2160 px（4K） | 1456×819 px / 1,560 | 2576×1449 px / 4,784 |

高分辨率模型下，同一张大图最多消耗标准档约 3 倍的视觉 token。对细节精度要求不高的截图或批量图片处理，提前缩小分辨率能直接省下对应比例的输入成本。

### 3. PDF 文档的文本 + 图像双计费

处理标准 PDF（无加密）时，每页的 token 由提取文本和页面截图两部分组成：

- **文本部分**：每页通常消耗 **1,500–3,000 tokens**（取决于排版密度）。
- **图像部分**：每页图像按标准分辨率上限缩放，最多消耗 **1,568 个视觉 token**。
- **请求限制**：第 1 方 Claude API 单次请求总大小上限为 **128 MB**，单次最多 **600 页**（200k 上下文窗口模型为 **100 页**）。

### 4. 扩展思考（Thinking）在多轮中的累加

思考内容占用 `max_tokens` 额度，按输出 token 计费并计入速率限制。在多轮对话中：

- **默认保留历史思考块的模型**：Claude Opus 4.5 及以上、Sonnet 4.6 及以上、Haiku 5.5、Fable 5/5.1/5.2、Mythos 5/5.1/5.2 与 Mythos Preview 会在后续轮次中保留历史思考块，这些历史思考块在后续请求里会作为输入 token 计入上下文窗口和账单。
- **自动剥离历史思考块的模型**：更早的 Opus/Sonnet 与 Haiku 4.5 在传入历史思考块时，API 会自动剥离旧轮次思考内容，不占用后续轮次输入配额。

## 四、上下文窗口容量与超限表现

截至 2026 年 11 月，Claude 模型的上下文窗口分为两档：

- **1M token 窗口（默认开启，无需 beta 请求头）**：Claude Fable 5.2 / 5.1 / 5、Mythos 5.2 / 5.1 / 5 / Preview、Opus 5.5 / 5 / 4.8 / 4.7 / 4.6、Sonnet 5.5 / 5 / 4.6、Haiku 5.5。单次请求最大输出 `max_tokens` 为 **128k tokens**。
- **200k token 窗口**：其余早期模型。

使用大容量窗口时有两个常见误区：

1. **缓存命中依然占满窗口容量**：开启 Prompt Caching 后，总输入占用是 `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`。缓存只降低单价，不释放上下文空间。
2. **Claude Haiku 5.5 超过 10 万 token 会跳档计价**：其余 1M 窗口模型全区间按标准单价计费，但 Claude Haiku 5.5 单次请求的总提示长度（普通输入 + 缓存写入 + 缓存读取）一旦超过 **100,000 tokens**，整笔请求的基础输入单价会从 $0.10/MTok 升至 $0.50/MTok，输出从 $0.50/MTok 升至 $2.50/MTok。

当接近窗口上限时，API 会有两种报错或截断表现：

- **输入本身已超过窗口**：所有模型均返回 HTTP `400 invalid_request_error`（错误信息含 `prompt is too long`）。
- **输入未超限，但「输入 + `max_tokens`」超过窗口**：Claude 4.5 及以上模型会接收并开始生成；一旦输出触及窗口边界，请求会停止并返回 `stop_reason: "model_context_window_exceeded"`。

## 参考

- [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support)
- [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)

以官方页面为准，本文数字截至 2026 年 11 月。
