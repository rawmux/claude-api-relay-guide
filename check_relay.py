#!/usr/bin/env python3
"""Claude API 中转站自测脚本（仅依赖标准库）。

用法:
    export RELAY_KEY=sk-xxx
    python3 check_relay.py --base-url https://example.com --model claude-sonnet-5-5

测试项:
    1. 流式延迟: 首字延迟 (TTFT)、总耗时、输出速度
    2. 计数: 固定文本的 input_tokens, 同模型同文本在真实 Claude 上应一致
    3. 缓存: 两次发送相同长前缀, 第二次 cache_read_input_tokens 应 > 0

注意: 每项测试都会真实扣费。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# 固定计数文本: 不要修改, 否则无法和别人的结果横向对比
COUNT_TEXT = (
    "Please reply with the single word OK. "
    "This is a fixed calibration paragraph for comparing token counts across API relays, version 1."
)

# 缓存前缀: 约 6000 tokens, 高于各模型缓存的最小长度要求
CACHE_PREFIX = "\n".join(
    f"Reference line {i}: the quick brown fox jumps over the lazy dog, checksum {i * 7919 % 10007}."
    for i in range(400)
)


def post(base_url, key, payload, stream=False, timeout=180):
    url = base_url.rstrip("/") + "/v1/messages"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "content-type": "application/json",
            "user-agent": "check-relay/1.0",
            "anthropic-version": "2023-06-01",
            "x-api-key": key,
            "authorization": f"Bearer {key}",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout)


def call_json(base_url, key, payload):
    with post(base_url, key, payload) as resp:
        return json.loads(resp.read().decode())


def test_stream(base_url, key, model):
    print("\n[1] 流式延迟")
    payload = {
        "model": model,
        "max_tokens": 300,
        "stream": True,
        "messages": [{"role": "user", "content": "用中文写一段 200 字左右的说明，介绍 HTTP 缓存的 ETag 机制。"}],
    }
    start = time.time()
    ttft = None
    out_tokens = 0
    resp_model = None
    with post(base_url, key, payload, stream=True) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                evt = json.loads(data)
            except json.JSONDecodeError:
                continue
            etype = evt.get("type")
            if etype == "message_start":
                resp_model = evt.get("message", {}).get("model")
            elif etype == "content_block_delta" and ttft is None:
                ttft = time.time() - start
            elif etype == "message_delta":
                out_tokens = evt.get("usage", {}).get("output_tokens", out_tokens)
    total = time.time() - start
    print(f"    返回 model 字段: {resp_model}")
    print(f"    首字延迟: {ttft:.2f}s" if ttft is not None else "    首字延迟: 未收到内容块")
    print(f"    总耗时: {total:.2f}s  输出 tokens: {out_tokens}")
    if ttft is not None and out_tokens and total > ttft:
        print(f"    输出速度: {out_tokens / (total - ttft):.1f} tokens/s")


def test_count(base_url, key, model):
    print("\n[2] 计数")
    data = call_json(base_url, key, {
        "model": model,
        "max_tokens": 5,
        "messages": [{"role": "user", "content": COUNT_TEXT}],
    })
    usage = data.get("usage", {})
    print(f"    input_tokens: {usage.get('input_tokens')}")
    print("    同一模型在不同站的这个数应该一致; 明显偏大可能被加了 system prompt, 差异很大可能不是同一个模型")


def test_cache(base_url, key, model):
    print("\n[3] 缓存")
    payload = {
        "model": model,
        "max_tokens": 5,
        "system": [{"type": "text", "text": CACHE_PREFIX, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Reply with OK."}],
    }
    for i in (1, 2):
        usage = call_json(base_url, key, payload).get("usage", {})
        print(
            f"    第 {i} 次: input={usage.get('input_tokens')} "
            f"cache_write={usage.get('cache_creation_input_tokens')} "
            f"cache_read={usage.get('cache_read_input_tokens')}"
        )
        if i == 1:
            time.sleep(2)
    if (usage.get("cache_read_input_tokens") or 0) > 0:
        print("    结论: 缓存生效")
    else:
        print("    结论: 第二次没有命中缓存 (可能未开启缓存, 或 usage 字段被改写)")


def main():
    ap = argparse.ArgumentParser(description="Claude API 中转站自测")
    ap.add_argument("--base-url", required=True, help="站点地址, 如 https://example.com")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--key", default=os.environ.get("RELAY_KEY"), help="默认读取环境变量 RELAY_KEY")
    ap.add_argument("--only", choices=["stream", "count", "cache"], help="只跑某一项")
    args = ap.parse_args()
    if not args.key:
        sys.exit("缺少 Key: 设置环境变量 RELAY_KEY 或传 --key")

    print(f"站点: {args.base_url}  模型: {args.model}")
    tests = {"stream": test_stream, "count": test_count, "cache": test_cache}
    for name, fn in tests.items():
        if args.only and args.only != name:
            continue
        try:
            fn(args.base_url, args.key, args.model)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            print(f"    HTTP {e.code}: {body}")
        except Exception as e:  # noqa: BLE001
            print(f"    失败: {e}")


if __name__ == "__main__":
    main()
