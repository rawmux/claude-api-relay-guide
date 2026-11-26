# Claude Code 接入自定义网关 / Base URL：配置、验证与报错排查

在团队内部署 LLM 网关，或通过自定义 Anthropic 兼容端点接入 Claude Code 时，核心配置只有「网关地址」和「认证凭据」两项。本文依据 Claude Code 与 Claude API 官方文档，整理 CLI 与常见开发环境的配置方式、连通性验证步骤，以及 `401` / `403` / `429` / `529` / `400` 等常见报错的排查方法。

## 一、先选对凭据变量

Claude Code 支持三种向网关传递凭据的方式，环境变量名决定了凭据放进哪个 HTTP 请求头：

| 配置方式 | 发送的 HTTP 请求头 | 适用场景 |
|---|---|---|
| `ANTHROPIC_AUTH_TOKEN` | `Authorization: Bearer <token>` | 网关要求 Bearer Token 或读取 `Authorization` 头 |
| `ANTHROPIC_API_KEY` | `x-api-key: <key>` | 网关要求 API Key 或读取 `x-api-key` 头 |
| `apiKeyHelper`（写在设置文件） | 同时写入 `Authorization` 和 `x-api-key` | 凭据会定期轮换，或需从密钥库/SSO 脚本动态获取 |

如果不确定网关读取哪一个请求头，官方建议先尝试 `ANTHROPIC_AUTH_TOKEN`；验证时若返回 `401`，再改用 `ANTHROPIC_API_KEY`。把凭据填错变量名，是接入初期触发 `401` 最常见的原因。

### 与现有 claude.ai 登录的优先级

- **同时设置 `ANTHROPIC_BASE_URL` 与凭据变量**：请求优先携带网关凭据，不再消耗个人订阅额度。其中 `ANTHROPIC_AUTH_TOKEN` 立即生效；`ANTHROPIC_API_KEY` 在交互模式（非 `-p`）首次使用时会弹窗确认一次，拒绝后会被忽略（可在 `/config` 的 `Use custom API key` 中重新开启）；在 `-p` 非交互模式下始终生效。
- **只设置 `ANTHROPIC_BASE_URL`、不设任何凭据变量**：请求虽然发往网关，但仍携带本地已保存的 claude.ai 登录凭据。若希望彻底清除本地订阅登录、只用网关凭据，可在 Claude Code 内执行 `/logout`。
- **注意冲突提示**：若同时启用了网关凭据与已保存登录且出现冲突警告，按需 `unset` 环境变量或执行 `/logout` 保留其一即可。

## 二、CLI 两种配置方式

### 方式一：终端环境变量（适合临时测试）

Bash / Zsh：

```bash
export ANTHROPIC_BASE_URL=https://llm-gateway.example.com
export ANTHROPIC_AUTH_TOKEN=你的网关token
```

PowerShell：

```powershell
$env:ANTHROPIC_BASE_URL = "https://llm-gateway.example.com"
$env:ANTHROPIC_AUTH_TOKEN = "你的网关token"
```

终端 `export` 只对当前终端及从该终端启动的进程生效；从桌面图标或程序坞直接打开的编辑器读不到。若希望在每个新终端生效，可写入 `~/.zshrc`、`~/.bashrc` 或 PowerShell `$PROFILE`。注意：后台子代理（background agents）不会稳定继承仅在终端里导出的变量，长期使用建议改写进设置文件。

### 方式二：写入 Claude Code 设置文件（适合长期使用）

在用户级配置文件 `~/.claude/settings.json`（Windows 为 `%USERPROFILE%\.claude\settings.json`）的 `env` 字段中写入：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://llm-gateway.example.com",
    "ANTHROPIC_AUTH_TOKEN": "你的网关token"
  }
}
```

配置作用域与优先级说明：

1. **用户级** `~/.claude/settings.json`：对本机所有项目生效。
2. **项目本地** `.claude/settings.local.json`：只对当前项目生效。首次由 Claude Code 生成时会自动加入全局 git excludes；若是手动创建，请先将其加入 `.gitignore`。
3. **不要把密钥写进 `.claude/settings.json`**：该文件会随代码库提交并共享给所有协作者。
4. **与 Shell 变量冲突时**：`settings.json` 中的 `env` 字段优先于 Shell 导出的同名变量（由更高优先级的托管策略或 CLI 参数设置的除外）。

### 动态凭据：`apiKeyHelper`

若凭据需动态获取，可在 `~/.claude/settings.json` 中配置只向 stdout 输出纯密钥字符串的脚本（Claude Code v2.1.227 起，脚本额外打印横幅或日志会导致失败）：

```json
{
  "apiKeyHelper": "~/bin/get-gateway-key.sh"
}
```

输出默认缓存 5 分钟，可通过 `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`（毫秒，如 `900000` 表示 15 分钟）调整缓存时长。

### 常用可选环境变量

| 变量名 | 作用 |
|---|---|
| `ANTHROPIC_CUSTOM_HEADERS` | 附加自定义请求头（`Name: Value` 格式）；写在 JSON 的 `env` 中时多个请求头用 `\n` 分隔（v2.1.227+） |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` | 关闭版本检查、遥测、发行说明等非核心外发请求（同时会关闭自动更新，并跳过 `/fast` 可用性探测） |
| `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` | 启动时向网关拉取模型列表并加入 `/model` 选择器；排障时可用 `claude --debug` 查看 `[gatewayDiscovery]` 日志 |

## 三、其他入口的配置差异

### VS Code 扩展

VS Code 扩展会在启动进程前自行校验凭据，仅写在 `~/.claude/settings.json` 不够。需在命令面板打开 **Preferences: Open User Settings (JSON)**，添加 `claudeCode.environmentVariables`：

```json
{
  "claudeCode.environmentVariables": [
    { "name": "ANTHROPIC_BASE_URL", "value": "https://llm-gateway.example.com" },
    { "name": "ANTHROPIC_AUTH_TOKEN", "value": "你的网关token" }
  ]
}
```

### GitHub Actions

使用 `anthropics/claude-code-action@v1` 时：

- 若网关读取 `x-api-key`：在 `env` 中设 `ANTHROPIC_BASE_URL`，通过 `with.anthropic_api_key` 传入密钥。
- 若网关读取 `Authorization: Bearer`：除了在 `env` 中设置 `ANTHROPIC_BASE_URL` 与 `ANTHROPIC_AUTH_TOKEN`，仍需同时传入 `with.anthropic_api_key`（或 OAuth / WIF）以满足 Action 的启动前凭据校验：

```yaml
env:
  ANTHROPIC_BASE_URL: https://llm-gateway.example.com
  ANTHROPIC_AUTH_TOKEN: ${{ secrets.GATEWAY_API_KEY }}

steps:
  - uses: anthropics/claude-code-action@v1
    with:
      anthropic_api_key: ${{ secrets.GATEWAY_API_KEY }}
```

### Agent SDK

- **TypeScript**：传入 `options.env` 会替换子进程整个环境变量，务必展开 `...process.env` 保留宿主变量。
- **Python**：`ClaudeAgentOptions(env=...)` 会合并到继承的环境变量之上。

## 四、两步验证连通性

### 第 1 步：先用 `curl` 发最小请求

在已导出变量的终端里运行（若用 `ANTHROPIC_API_KEY`，把 `Authorization` 请求头替换为 `-H "x-api-key: $ANTHROPIC_API_KEY"`）：

```bash
curl -sS -w '\n%{http_code}\n' -X POST "$ANTHROPIC_BASE_URL/v1/messages" \
  -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model": "claude-sonnet-4-6", "max_tokens": 1, "messages": [{"role": "user", "content": "."}]}'
```

返回结果判断：

- **JSON 以 `{"id":"msg_` 开头且含 `"content":[...]`**：网关地址与凭据均正常。
- **返回模型不存在或未授权该模型**：同样说明 URL 连通且网关已通过鉴权，只需核对可用模型名。
- **返回 `401`**：凭据无效，或 `ANTHROPIC_AUTH_TOKEN` 与 `ANTHROPIC_API_KEY` 选反了。
- **连接报错或超时**：地址、DNS、代理或防火墙问题，先于 Claude Code 本身排查网络。

### 第 2 步：在 Claude Code 内用 `/status` 核对

从同一终端启动 `claude`，发送一条测试消息后输入 `/status`，查看 **Status** 页签的两行：

- `Anthropic base URL`：只有成功读取自定义地址时才会出现，且应显示你的网关地址。
- `Auth token` 或 `API key`：应显示你配置的变量名（或 `apiKeyHelper`），而不是 `Login method: claude.ai`。

若配置文件修改后未生效或报格式错误，可在终端执行 `claude doctor` 查看被跳过或解析失败的配置项。

## 五、常见报错排查速查

官方 SDK 与 Claude Code 默认会对连接错误、超时以及 `408`、`409`、`429`、`5xx` 自动重试 2 次（共 3 次尝试），无 `retry-after` 头时采用 0.5–8 秒指数退避，因此部分网络故障会停顿几秒后才报错。

| 报错现象 / 状态码 | 常见原因 | 排查与处理 |
|---|---|---|
| 启动提示两个凭据来源冲突（`auth may not work as expected`） | 网关凭据变量与已保存的 claude.ai 登录同时存在 | 用网关就执行 `/logout`；用个人订阅就 `unset` 对应环境变量 |
| `401 authentication_error` | Token/Key 错误、过期，或放错了请求头变量 | 在 `ANTHROPIC_AUTH_TOKEN` 与 `ANTHROPIC_API_KEY` 之间切换验证；用本地登录走网关时检查网关是否透传了 `Authorization` 和 `anthropic-beta` |
| `403 permission_error` | 当前 Key 无权访问目标模型或工作区资源 | 联系网关管理员确认账号权限与模型白名单 |
| `403 Forbidden`（返回 HTML 且网关侧无日志） | 网关前置 WAF/反代误拦截了包含 XML 标签或代码的请求体，而短 `curl` 能通过 | 将网关 `/v1/messages` 路径从请求体 XSS 规则检查中豁免（如 AWS WAF `CrossSiteScripting_Body` 或 ModSecurity 对应规则） |
| `429 rate_limit_error` | 触发限速（RPM/TPM）、突发爬坡限制，或月度消费上限（`enforced_spend_limit_reached`） | 有 `retry-after` 头时按秒数等待（超过 60 秒会停止自动重试并直接报错）；无 `retry-after` 且持续失败多为消费上限 |
| `529 overloaded_error` / `500` / `504` | 服务端过载、内部错误或处理超时 | 非本地配置问题，等待自动退避重试或稍后再试 |
| `ConnectionRefused` / `ENOTFOUND` | Base URL 写错、DNS 不可达，或被防火墙/代理阻断 | 用第四节 `curl` 复现，检查地址、端口及系统代理设置 |
| `API returned an empty or malformed response (HTTP 200)` | 网关或中间代理返回了非 API 内容（常见为 HTML 登录页或错误页） | 用 `curl` 打印原始响应体，排查网关路由与鉴权拦截 |
| `400` 含 `Extra inputs are not permitted` 或 `context_management` | 网关将 Anthropic 格式请求转给不兼容预发布字段的上游 | 设置 `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`（v2.1.304+ 会对部分拒绝自动去除对应字段后重试） |
| `400` 含 `thinking` 或 `adaptive`（如 `Input tag 'adaptive' found`） | 上游模型版本不支持自适应思考 | 升级网关上游；Opus 4.6 / Sonnet 4.6 可设 `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` |
| `400` 报网关自定义上下文超限（如 `ContextWindowExceededError`） | 网关限制窗口小于模型原生窗口且改写了报错文案，导致未触发自动压缩 | 手动执行 `/compact` 恢复会话；长期可设 `CLAUDE_CODE_AUTO_COMPACT_WINDOW`（Claude Code 会将其钳制在至少 100,000 token 到模型窗口之间）并限制 `CLAUDE_CODE_MAX_OUTPUT_TOKENS` |
| `SSL certificate verification failed`（但 `curl` 正常） | 企业 TLS 拦截代理的根证书未被 Claude Code 运行时信任 | 设置 `NODE_EXTRA_CA_CERTS` 指向对应的 CA 证书文件 |

## 参考

- [Connect Claude Code to an LLM gateway](https://code.claude.com/docs/en/llm-gateway-connect)
- [Claude Code gateway compatibility guide](https://code.claude.com/docs/en/llm-gateway-protocol)
- [Settings files and precedence](https://code.claude.com/docs/en/settings)
- [Claude API errors](https://platform.claude.com/docs/en/api/errors)

以官方页面为准，本文内容截至 2026 年 11 月。
