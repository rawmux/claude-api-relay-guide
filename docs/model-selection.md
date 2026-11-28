# Claude 模型选型与 Effort 调优指南（Haiku / Sonnet / Opus / Fable）

挑选 Claude 模型时，只看每百万 token 的标价容易误判实际账单：高一档的模型往往一次就能把任务跑通，而便宜模型如果反复试错、多跑几轮工具调用，总花销反而可能反超。本文依据 Anthropic 与 Claude Code 官方文档，整理当前主力模型的规格定价、按任务计费的官方对比数据、`effort` 调优方法，以及 Claude Code 中的可复制配置。

## 一、四款主力模型规格与官方价格（截至 2026 年 11 月）

面向所有用户开放的四款最新模型均默认配备 **1M token 上下文窗口**与最高 **128K token 输出**（在 Batch API 下使用 `output-300k-2026-03-24` beta 请求头最高可输出 300K tokens），均支持文本与图像输入、视觉理解及工具调用。

| 模型（API ID） | 基础输入 / 输出（美元 / MTok） | 缓存读倍率 / 单价 | 默认 `effort`（API / Claude Code） | 典型适用场景 |
|---|---|---|---|---|
| **Claude Haiku 5.5**（`claude-haiku-5-5`） | 提示 ≤100K：`$0.10 / $0.50`<br>提示 >100K：`$0.50 / $2.50` | `0.1x`（`$0.01` / `$0.05`） | `medium` / `medium` | 高并发、低延迟任务：分类、结构化抽取、路由、子代理执行 |
| **Claude Sonnet 5.5**（`claude-sonnet-5-5`） | `$2 / $10` | `0.05x`（`$0.10`） | `high` / `medium` | 速度与能力兼顾的日常开发、常规编码、数据分析、工具调用 |
| **Claude Opus 5.5**（`claude-opus-5-5`） | `$4 / $20` | `0.05x`（`$0.20`） | `medium` / `medium` | 长程自主编码、大规模重构、视觉密集流程、官方默认首选起点 |
| **Claude Fable 5.2**（`claude-fable-5-2`） | `$8 / $40` | `0.025x`（`$0.20`） | `high` / `medium` | 高难度推理、数小时跨度的长程研究与根因排查 |

补充说明：

- **5 分钟与 1 小时缓存写入**：全系均为基础输入价的 `1.25x` 与 `2x`；Batch API 全系输入与输出均享 **5 折**。
- **受限可用型号**：`Claude Mythos 5.2`（`claude-mythos-5-2`）定价与能力对齐 Fable 5.2（`$8 / $40`，缓存读 `0.025x`），仅向通过 Cyber Verification Program 等 Anthropic 验证项目的组织开放。
- **极速模式（Fast mode）**：设置 `speed: "fast"` 可将输出速度提升最高 **2.5 倍**，同时 token 单价翻倍（Opus 5.5 为 `$8 / $40`，Fable 5.2 为 `$16 / $80`）。Fast mode 不支持与 Batch API 组合使用，且对话中途切换 `speed` 会导致前缀缓存失效。

可以通过 `/v1/models` 接口实时核对当前端点支持的模型列表与能力字段：

```bash
curl -sS https://api.anthropic.com/v1/models \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2026-10-21"
```

## 二、按「完成任务成本」对比，而非只看 Token 单价

官方选型指南给出的核心原则是：**拿不准用哪个模型时，优先从 Claude Opus 5.5 起步**；评估模型贵不贵，应当按「完成一个任务总共花多少钱」计算，而不是只比较单价。

以下为 Anthropic 官方公开的内部基准测试计费对比（按 5 分钟缓存客户实际计费口径核算，仅作方向性参考）：

| 评测集 | 模型与 `effort` | 完成率 / 得分 | 单任务平均成本 |
|---|---|---|---|
| SWE-bench Pro 子集（478 题） | Sonnet 5.5（默认 `high`） | 87.6% | $0.11 |
| SWE-bench Pro 子集（478 题） | Opus 5.5（`low`） | 87.4% | $0.12 |
| SWE-bench Pro 子集（478 题） | Opus 5.5（默认 `medium`） | 92.8% | $0.22 |
| SWE-bench Pro 子集（478 题） | Fable 5.1（默认 `high`） | 92.3% | $1.19 |
| SWE-bench Pro 无网子集（463 题） | Fable 5.2（`low`） | 94.6% | $0.39 |
| SWE-bench Pro 无网子集（463 题） | Fable 5.2（API 默认 `high`） | 96.3% | $1.39 |
| SWE-bench Pro 无网子集（463 题） | Opus 5.5（`xhigh`） | 96.5% | $0.75 |
| GPQA Diamond（198 题） | Haiku 5.5（默认 `medium`） | 85%（Opus 5.5 与 Sonnet 5.5 为 91%） | 约为 Opus 5.5 的 1/20、Sonnet 5.5 的 1/10 |

从这组数据可以读出三个结论：

1. **高单价不一定高总价**：Opus 5.5 的每个 token 标价是 Sonnet 5.5 的 2 倍，但在 SWE-bench Pro 上把 Opus 5.5 降到 `low` 后，解决率与 Sonnet 5.5 默认档处于同一水平，单任务总花费仅高约 7%（输出 token 和缓存读取量都更少）。
2. **新代次通常更省**：Opus 5.5 默认 `medium` 档即达到上代旗舰 Fable 5.1 的解决率，而单任务成本降至约五分之一。
3. **最贵模型并不在所有任务上都占优**：在 44 项 DeepResearch Bench II 深度研究评测中（Messages API 默认档），Fable 5.2 花费是 Opus 5.5 的 2.9 倍、Sonnet 5.5 的 4.3 倍，平均分却比 Opus 5.5 低 1.9 分。遇到特定垂直场景时，先用自己的业务评测集实测再切顶配。

## 三、各档模型的边界与常见踩坑

### 1. Haiku 5.5：严防越过 100K token 阶梯线

- **长上下文 5 倍跳价**：Haiku 5.5 是当前 5.x 系列中唯一按提示长度分档计价的模型。单次请求总提示长度（普通输入 + 缓存写入 + 缓存读取）一旦超过 **100,000 tokens**，整笔请求的输入单价从 `$0.10` 升至 `$0.50`/MTok，输出从 `$0.50` 升至 `$2.50`/MTok，缓存读从 `$0.01` 升至 `$0.05`/MTok。
- **控制手段**：使用 Messages API 自动压缩时，建议将 `trigger` 设为低于 100K 的数值（例如 `90,000`，默认是 `150,000`）；在长对话场景中一旦经常接近 100K，不如直接换用 Sonnet 5.5。
- **思考与 `max_tokens`**：Haiku 5.5 默认开启思考且思考过程计入 `max_tokens` 上限，把 `max_tokens` 设得过小会导致思考耗尽额度、正文字段为空；此外 `thinking: {"type": "disabled"}` 仅支持 `high` 及以下 `effort`，在 `xhigh` 或 `max` 下传入会返回 HTTP `400`。

### 2. Sonnet 5.5：高性价比常规主力

- 延迟低于 Opus 与 Fable，缓存命中倍率已压至 `0.05x`（`$0.10/MTok`），适合常规业务代码生成、数据处理与延迟敏感的交互场景。
- **思考参数兼容**：Sonnet 5.5 不再接受 `thinking: {"type": "disabled"}`（调用会返回 `400`）。需要跳过前置思考时，可改传 `thinking: {"type": "between_tools"}`，且该模式仅支持 `low`、`medium`、`high` 三档，在 `xhigh` 或 `max` 下同样返回 `400`。

### 3. Opus 5.5 与 Fable 5.2：强制自适应思考与分词器差异

- **强制自适应思考**：两者均为 always-on adaptive thinking，旧代码中如果保留了 `thinking: {"type": "disabled"}` 或手动 `budget_tokens`，在任意 `effort` 档位都会直接返回 HTTP `400`。
- **新版分词器体积**：从 Claude 4.7 及后续模型（含整个 5.x 系列与 Fable 5.x）起启用了新版分词器，同一段文本生成的 token 数比 Sonnet 4.6 及更早模型大约多 **30%**。从旧模型迁移时，应使用 `/v1/messages/count_tokens` 重新核算长度。

## 四、用 `effort` 调优与多模型组合策略

### 1. 五档 `effort` 取值与调用示例

5.x 系列全系支持五个档位：`low`、`medium`、`high`、`xhigh`、`max`（早期 Opus 4.6 与 Sonnet 4.6 不支持 `xhigh`）。通过请求体 `output_config.effort` 指定，同时影响思考深度、工具调用次数与解释篇幅，但不会可靠缩短最终回复字数（需要简短回答应在提示词里明确要求）。

`curl` 调用示例：

```bash
curl -sS https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2026-10-21" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-opus-5-5",
    "max_tokens": 64000,
    "output_config": {
      "effort": "medium"
    },
    "messages": [
      {
        "role": "user",
        "content": "分析微服务与单体架构在当前十人研发团队下的维护成本差异，用五条以内要点回答。"
      }
    ]
  }'
```

Python SDK 示例（并按官方文档公式精确计算本次请求的美元花费）：

```python
import anthropic

INPUT_PER_MTOK = 4.00       # Claude Opus 5.5
CACHE_READ_PER_MTOK = 0.20  # Opus 5.5 为基础输入的 0.05x
OUTPUT_PER_MTOK = 20.00

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=64000,
    output_config={"effort": "medium"},
    messages=[{"role": "user", "content": "Hello, Claude"}],
)

usage = response.usage
cache_creation = usage.cache_creation
writes_1h = cache_creation.ephemeral_1h_input_tokens if cache_creation else 0
writes_5m = cache_creation.ephemeral_5m_input_tokens if cache_creation else 0

cost = (
    usage.input_tokens * INPUT_PER_MTOK
    + writes_1h * INPUT_PER_MTOK * 2.0
    + writes_5m * INPUT_PER_MTOK * 1.25
    + (usage.cache_read_input_tokens or 0) * CACHE_READ_PER_MTOK
    + usage.output_tokens * OUTPUT_PER_MTOK
) / 1_000_000
print(f"Request cost: ${cost:.6f}")
```

### 2. 低档先跑 + 失败重跑高档

如果任务有明确的程序化验收条件（例如单元测试、Schema 校验或 CI 检查），先全量跑低档再对失败项重跑高档，往往比直接全量跑高档更划算。Anthropic 对 Opus 5.5 在 SWE-bench Pro 子集上的逐题测算如下：

| 策略 | 任务解决率 | 单任务平均成本 |
|---|---|---|
| 全部用 `low`，仅失败项（13%）用 `high` 重跑 | 约 97% | 约 $0.17 |
| 全部用 `medium`，失败项用 `high` 重跑 | 约 97% | 约 $0.24 |
| 全部直接用 `high` | 95.3% | $0.29 |

该策略需要付出两次串行等待的延迟代价（仅针对首轮失败的样本），因此更适合批处理、CI 自动修复和离线评测任务。

### 3. 别用压低 `max_tokens` 来省钱

模型无法感知 `max_tokens` 上限，调小该值不会让模型主动精简输出，反而会在极少数长推理回合直接截断（`stop_reason: "max_tokens"`），导致前面已生成的 token 全部计费作废。在 Anthropic 内部仓库任务测试中，将 Fable 5.2 的 `max_tokens` 从 `16,384` 提高到 `64,000` 后，截断率从 **85% 降至 2%**，单任务解决成本反而从 **$27.96 降至 $24.42**。Agent 编码任务建议默认设置 `64,000` 或上限 `128,000` 并开启流式输出，改用 `effort` 控制思考开销。

另外注意：在未启用消息级 `effort`（per-message `output_config`）的条件下，对话中途改动顶层 `output_config.effort` 会打断前缀缓存，导致整段历史重新按缓存写入计费。

### 4. 何时用多模型组合（Orchestrator vs Advisor）

官方建议**先单模型扫完 `effort` 曲线，确实不够用再引入第二个模型**：

- **编排者模式（Orchestrator + 子代理）**：由强模型拆解并汇总，把可独立并行的子任务分发给低一级模型。适合工作量超出单个上下文窗口，或跨数十上百个独立文件的检索场景。在 Anthropic 2,200 万 token 的跨包缺陷检索测试中，Opus 5.5 调度 Sonnet 5.5 子代理比单用 Opus 5.5 默认档节省约三分之一成本，F1 分数保持持平。
- **顾问模式（Advisor tool）**：由便宜模型跑主循环，遇到难点再调用强模型顾问。只在执行模型确实会在少数关键卡点主动咨询时有效；如果执行模型几乎不咨询，或每次请求白白多带约 1,000 token 的工具定义且串联额外等待，性价比往往不如直接把单模型 `effort` 调高一档。

## 五、Claude Code 中的模型、Effort 与子代理配置

### 1. 常用别名与最低客户端版本

| 别名 | Anthropic API 解析目标 | 最低客户端版本要求 | 说明 |
|---|---|---|---|
| `opus` / `best` | `claude-opus-5-5` | `v2.1.280+` | 复杂推理与主力编码 |
| `sonnet` | `claude-sonnet-5-5` | `v2.1.284+` | 日常开发与快速迭代 |
| `haiku` | `claude-haiku-5-5` | `v2.1.293+` | 轻量任务与后台辅助 |
| `fable` | `claude-fable-5-2` | `v2.1.321+` | 长程高难任务；不作任何订阅套餐默认模型，在 Claude apps gateway 会话默认指 Fable 5，需显式写 `/model claude-fable-5-2` |
| `opusplan` | 规划用 `opus`，执行切回 `sonnet` | 内置模式 | 适合先出方案再落代码的日常工作流 |

版本过低导致无法识别新模型时，先执行 `claude update`。注意：`ANTHROPIC_BASE_URL` 仅决定请求发往哪个端点，不改变模型别名或参数语义；如果自定义网关尚未放行某个新版模型 ID，可先通过自定义模型选项或具体型号 ID 指定。

### 2. 可复制 CLI 命令与环境变量

启动时指定模型与 `effort`（仅影响当前终端会话，不覆盖全局默认）：

```bash
claude --model opus --effort medium
```

在交互会话内常用控制命令：

- `/model`：打开模型与 `effort` 滑块选择器；按 `Enter` 写入 `~/.claude/settings.json` 成为默认，按 `s` 仅作用于当前会话（需 `v2.1.257+`）。
- `/model opusplan`：启用「Opus 规划 + Sonnet 执行」组合模式。
- `/effort low` / `/effort status`：调整当前会话或查看实际向接口发送的 `effort` 值（设 `CLAUDE_CODE_EFFORT_LEVEL=auto` 可让客户端不传 `effort`，由服务端使用模型默认值）。
- `/status`：查看当前生效模型与账号状态。

推荐在启动脚本或 Shell 配置中固定子代理与压缩上限（尤其是使用 Haiku 5.5 时防止越过 100K 跳价线）：

```bash
# 主会话切到 Opus 时，避免未显式指定模型的子代理/团队成员跟着继承高价模型
export CLAUDE_CODE_SUBAGENT_MODEL=haiku

# 在未指定 --model 且用户配置无覆盖时，指定新会话默认模型（需 v2.1.236+）
export ANTHROPIC_DEFAULT_MODEL=sonnet

# 限制自动压缩触发窗口（如配合 Haiku 5.5 避开 100K 阶梯价，或适配仅支持 200K 的网关）
export CLAUDE_CODE_AUTO_COMPACT_WINDOW=90000
```

若习惯通过 `~/.claude/settings.json` 持久化默认配置，可直接写入：

```json
{
  "model": "opusplan",
  "autoCompactWindow": 200000
}
```

## 参考

- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)
- [Models overview](https://platform.claude.com/docs/en/models/overview)
- [Choosing the right model](https://platform.claude.com/docs/en/about-claude/models/choosing-a-model)
- [Optimizing for cost and intelligence](https://platform.claude.com/docs/en/about-claude/models/optimizing-for-cost-and-intelligence)
- [Effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Claude Code Model configuration](https://code.claude.com/docs/en/model-config)

以官方页面为准，本文数字截至 2026 年 11 月。
