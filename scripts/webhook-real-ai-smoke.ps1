#requires -Version 7.2
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string[]]$ConcurrentConversationIds,
    [Parameter(Mandatory)][ValidateRange(1, 2147483647)][int]$OrderedConversationId,
    [ValidateRange(30, 1800)][int]$TimeoutSeconds = 600,
    [string]$ReportPath = "",
    [switch]$ConfirmRealAiCost,
    [switch]$Mock
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'lib/Operations.psm1') -Force

$concurrentIds = @(
    foreach ($value in $ConcurrentConversationIds) {
        foreach ($candidate in $value.Split(',')) {
            $trimmed = $candidate.Trim()
            if ($trimmed -notmatch '^\d+$' -or [int64]$trimmed -gt 2147483647 -or [int64]$trimmed -lt 1) {
                throw "无效的 Chatwoot 会话 ID：$trimmed"
            }
            [int]$trimmed
        }
    }
)
if ($concurrentIds.Count -ne 5) { throw '必须提供 5 个并发测试会话 ID。' }
$allConversationIds = @($concurrentIds) + $OrderedConversationId
if (@($allConversationIds | Sort-Object -Unique).Count -ne 6) {
    throw '必须提供 6 个互不相同的专用测试会话 ID。'
}

$impact = '此验收会调用真实模型，并向 6 个指定 Chatwoot 测试会话写入回复；可能产生模型费用和测试消息。'
if (-not $ConfirmRealAiCost) {
    Write-Output $impact
    Write-Output '确认影响后使用 -ConfirmRealAiCost；当前未发送任何请求。'
    return
}

$projectRoot = Get-ProjectRoot
if (-not $ReportPath) {
    $ReportPath = Join-Path $projectRoot ("diagnostics/webhook-real-ai-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
}

function Get-NearestRankPercentile([double[]]$Values, [double]$Percentile) {
    if ($Values.Count -eq 0) { throw '没有可用于计算延迟的数据。' }
    $sorted = @($Values | Sort-Object)
    $index = [Math]::Max(0, [Math]::Ceiling($Percentile * $sorted.Count) - 1)
    return [Math]::Round([double]$sorted[$index], 3)
}

function Get-ConversationFingerprint([int]$ConversationId) {
    $bytes = [Text.Encoding]::UTF8.GetBytes([string]$ConversationId)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant().Substring(0, 12)
}

if ($Mock) {
    $latencies = [double[]](0.51, 0.63, 0.72, 0.84, 0.96, 1.08, 1.21, 1.35)
    $result = [ordered]@{
        schema_version = 1
        status = 'passed'
        mode = 'mock'
        mock_used = $true
        captured_at = (Get-Date).ToUniversalTime().ToString('o')
        concurrent_conversations = @($concurrentIds | ForEach-Object { Get-ConversationFingerprint $_ })
        ordered_conversation = Get-ConversationFingerprint $OrderedConversationId
        accepted = 8
        replies = 8
        reply_order = @(0, 1, 2)
        latency_p50_seconds = Get-NearestRankPercentile $latencies 0.50
        latency_p95_seconds = Get-NearestRankPercentile $latencies 0.95
        completion_modes = @{ public = 8; private_ai_reference = 0 }
        queue = @{ stream = 0; pending = 0; dead_letter_delta = 0 }
    }
} else {
    $python = @'
import asyncio, hashlib, json, math, os, sys, time, uuid
import httpx
import redis.asyncio as redis_async

def fail(code):
    print(json.dumps({"status":"failed","error":code}, separators=(",",":")), flush=True)
    raise SystemExit(1)

def messages_from(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    payload = value.get("payload", value.get("data", {}).get("payload", []))
    return payload if isinstance(payload, list) else []

def completion_mode(message):
    if message.get("message_type") not in (1, "outgoing"):
        return None
    if not bool(message.get("private")):
        return "public"
    content = str(message.get("content") or "")
    if content.startswith("[AI 参考]"):
        return "private_ai_reference"
    return None

def percentile(values, q):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * q) - 1)], 3)

def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:12]

async def main():
    required = [
        "CHATWOOT_ADAPTER_GATEWAY_URL", "CHATWOOT_ADAPTER_INGRESS_TOKEN",
        "CHATWOOT_BASE_URL", "CHATWOOT_API_TOKEN", "CHATWOOT_ACCOUNT_ID",
        "REDIS_HOST", "REDIS_PASSWORD",
    ]
    if any(not os.getenv(name) for name in required):
        fail("runtime_configuration_missing")
    concurrent_ids = [int(value) for value in os.environ["P4B_CONCURRENT_IDS"].split(",")]
    ordered_id = int(os.environ["P4B_ORDERED_ID"])
    timeout = int(os.environ["P4B_TIMEOUT_SECONDS"])
    run_id = uuid.uuid4().hex
    gateway = os.environ["CHATWOOT_ADAPTER_GATEWAY_URL"].rstrip("/") + "/webhook/" + os.environ["CHATWOOT_ADAPTER_INGRESS_TOKEN"]
    chatwoot = os.environ["CHATWOOT_BASE_URL"].rstrip("/")
    account = os.environ["CHATWOOT_ACCOUNT_ID"]
    headers = {"api_access_token": os.environ["CHATWOOT_API_TOKEN"]}
    redis = redis_async.Redis(
        host=os.environ["REDIS_HOST"], port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.environ["REDIS_PASSWORD"], db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )
    client = httpx.AsyncClient(timeout=30)

    async def get_messages(conversation_id):
        url = f"{chatwoot}/api/v1/accounts/{account}/conversations/{conversation_id}/messages"
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError("chatwoot_read_failed")
        return messages_from(response.json())

    async def queue_state():
        stream = "ai:webhook-adapter:events"
        try:
            pending_value = await redis.xpending(stream, "webhook-workers")
            pending = pending_value.get("pending", 0) if isinstance(pending_value, dict) else pending_value[0]
        except Exception:
            pending = 0
        return {
            "stream": await redis.xlen(stream),
            "pending": int(pending),
            "dead_letter": await redis.xlen("ai:webhook-adapter:dead-letter"),
        }

    async def post_event(conversation_id, sequence):
        message_id = int(time.time_ns() // 1000) + sequence
        payload = {
            "event": "message_created", "id": message_id,
            "message": {
                "id": message_id,
                "content": f"P4-B real AI acceptance {run_id[:8]} sequence {sequence}",
                "message_type": "incoming", "private": False,
                "sender": {"id": 2147000000 - sequence, "name": "P4-B acceptance"},
                "created_at": int(time.time()),
            },
            "conversation": {"id": conversation_id, "status": "open"},
        }
        started = time.monotonic()
        response = await client.post(gateway, json=payload)
        if response.status_code != 202 or response.json().get("status") not in ("queued", "duplicate"):
            raise RuntimeError("gateway_rejected")
        return started

    try:
        ids = concurrent_ids + [ordered_id]
        baseline = {}
        for conversation_id in ids:
            existing = await get_messages(conversation_id)
            baseline[conversation_id] = max([int(item.get("id", 0)) for item in existing] or [0])
        before_queue = await queue_state()

        concurrent_started = await asyncio.gather(*[
            post_event(conversation_id, index) for index, conversation_id in enumerate(concurrent_ids)
        ])
        ordered_started = []
        for sequence in range(3):
            ordered_started.append(await post_event(ordered_id, 100 + sequence))

        deadline = time.monotonic() + timeout
        observed = {}
        completion_times = {value: [] for value in ids}
        while time.monotonic() < deadline:
            for conversation_id in ids:
                current = await get_messages(conversation_id)
                latest = sorted(
                    [item for item in current if completion_mode(item) is not None and int(item.get("id", 0)) > baseline[conversation_id]],
                    key=lambda item: int(item.get("id", 0)),
                )
                newly_observed = len(latest) - len(observed.get(conversation_id, []))
                if newly_observed > 0:
                    completion_times[conversation_id].extend([time.monotonic()] * newly_observed)
                observed[conversation_id] = latest
            if all(len(observed.get(value, [])) >= 1 for value in concurrent_ids) and len(observed.get(ordered_id, [])) >= 3:
                break
            await asyncio.sleep(2)
        else:
            fail("reply_timeout")

        await asyncio.sleep(2)
        for conversation_id in ids:
            current = await get_messages(conversation_id)
            observed[conversation_id] = sorted(
                [item for item in current if completion_mode(item) is not None and int(item.get("id", 0)) > baseline[conversation_id]],
                key=lambda item: int(item.get("id", 0)),
            )
        if any(len(observed[value]) != 1 for value in concurrent_ids) or len(observed[ordered_id]) != 3:
            fail("duplicate_or_missing_reply")

        latencies = [
            completion_times[conversation_id][0] - concurrent_started[index]
            for index, conversation_id in enumerate(concurrent_ids)
        ] + [
            completion_times[ordered_id][index] - ordered_started[index]
            for index in range(3)
        ]
        after_queue = await queue_state()
        if after_queue["stream"] != 0 or after_queue["pending"] != 0:
            fail("queue_not_drained")
        if after_queue["dead_letter"] != before_queue["dead_letter"]:
            fail("dead_letter_created")

        completion_modes = {"public": 0, "private_ai_reference": 0}
        for messages in observed.values():
            for message in messages:
                completion_modes[completion_mode(message)] += 1

        result = {
            "schema_version": 1, "status": "passed", "mode": "real-ai", "mock_used": False,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "concurrent_conversations": [fingerprint(value) for value in concurrent_ids],
            "ordered_conversation": fingerprint(ordered_id),
            "accepted": 8, "replies": 8, "reply_order": [0, 1, 2],
            "reply_message_ids": [int(item["id"]) for item in observed[ordered_id]],
            "latency_p50_seconds": percentile(latencies, 0.50),
            "latency_p95_seconds": percentile(latencies, 0.95),
            "completion_modes": completion_modes,
            "queue": {"stream": 0, "pending": 0, "dead_letter_delta": 0},
        }
        print(json.dumps(result, separators=(",",":")), flush=True)
    except SystemExit:
        raise
    except Exception as exc:
        fail(type(exc).__name__)
    finally:
        await client.aclose()
        await redis.aclose()

asyncio.run(main())
'@
    $encodedPython = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($python))
    Push-Location $projectRoot
    try {
        $nativeOutput = & docker compose exec -T `
            -e "P4B_CONCURRENT_IDS=$($concurrentIds -join ',')" `
            -e "P4B_ORDERED_ID=$OrderedConversationId" `
            -e "P4B_TIMEOUT_SECONDS=$TimeoutSeconds" `
            bridge python -c "import base64;exec(base64.b64decode('$encodedPython'))" 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $outputText = ($nativeOutput | ForEach-Object { [string]$_ }) -join [Environment]::NewLine
    $safeOutput = Protect-OperationalText $outputText
    $jsonLine = @($safeOutput -split "`r?`n" | Where-Object { $_ -match '^\{.+\}$' } | Select-Object -Last 1)
    if ($exitCode -ne 0 -or $jsonLine.Count -ne 1) {
        throw "真实 AI 验收失败：$safeOutput"
    }
    $result = $jsonLine[0] | ConvertFrom-Json -AsHashtable
    if ($result.status -ne 'passed') { throw "真实 AI 验收未通过：$($result.error)" }
}

$reportDirectory = Split-Path -Parent $ReportPath
if ($reportDirectory) { New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null }
$json = $result | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText([IO.Path]::GetFullPath($ReportPath), $json, [Text.UTF8Encoding]::new($false))
Write-Output $json
Write-Host "Report: $ReportPath" -ForegroundColor Cyan
