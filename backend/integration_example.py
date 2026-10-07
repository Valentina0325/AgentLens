"""NEXUS AI（或任意 AI 应用）接入 AgentLens 的示例。

设计原则（对照任务书）：
- 不新增任何 top-level 字段；项目身份放在 `metadata`（任务书允许的灵活 dict），
  例如 `metadata={"source": "NEXUS_AI"}`，便于在 AgentLens 中区分不同接入方。
- 只调用任务书定义的 `POST /api/traces` 接口，实现“接入即监测”。
- 零第三方依赖：优先用 requests，未安装时自动回退到标准库 urllib，
  因此本文件可直接拷进你自己的项目，无需额外 pip install。

典型接入点：在 NEXUS AI 完成一次流式对话、拿到最终 input/output token 数之后，
调用一次 `report_trace(...)` 即可把这次 LLM 调用上报到 AgentLens。
"""
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional


def report_trace(
    base_url: str = "http://localhost:8000",
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    status: str = "success",
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    source: str = "NEXUS_AI",
    extra_metadata: Optional[Dict[str, Any]] = None,
    timeout: float = 3.0,
) -> Optional[Dict[str, Any]]:
    """把一次 LLM 调用上报到 AgentLens。

    参数：
        base_url: AgentLens 后端地址（默认本地 8000，部署后改成实际地址）。
        model/input_tokens/output_tokens/latency_ms/status: 任务书 TraceSpan 必填项。
        trace_id/span_id: 可选，不传则自动生成（生产环境建议用真实调用链 ID）。
        source: 接入方标识，写入 metadata.source，用于在 AgentLens 区分项目。
        extra_metadata: 额外自定义标签（如 user_id、prompt_version），合并进 metadata。
        timeout: 上报超时（秒），避免阻塞主对话流程。

    返回：后端响应 JSON；若上报失败（网络错误/依赖缺失）返回 None，不抛异常，
          保证接入方的主流程（对话）不受影响。
    """
    if span_id is None:
        span_id = "span-" + uuid.uuid4().hex[:12]
    if trace_id is None:
        trace_id = "trace-" + uuid.uuid4().hex[:12]

    metadata: Dict[str, Any] = {"source": source}
    if extra_metadata:
        metadata.update(extra_metadata)

    payload = {
        "trace_id": trace_id,
        "span_id": span_id,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "metadata": metadata,
    }
    url = base_url.rstrip("/") + "/api/traces"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    try:
        try:
            import requests  # type: ignore

            resp = requests.post(url, data=data, headers=headers, timeout=timeout)
            status_code = resp.status_code
            text = resp.text
        except ImportError:
            # 标准库回退，无需 requests
            import urllib.request

            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status_code = r.status
                text = r.read().decode("utf-8", errors="replace")

        if status_code in (200, 201):
            try:
                return json.loads(text)
            except Exception:
                return {"message": "recorded"}
        # 重复 span_id 后端按幂等返回 200（message=already recorded），视为成功
        print(f"[AgentLens] 上报返回 HTTP {status_code}: {text}")
        return None
    except Exception as e:  # 网络异常等，不影响主业务
        print(f"[AgentLens] 上报异常（已忽略）：{e}")
        return None


# ---------------------------------------------------------------------------
# 示例：在 NEXUS AI 的流式对话完成处接入
# ---------------------------------------------------------------------------
def _demo_for_nexus_ai() -> None:
    """演示 NEXUS AI 在流式输出结束后如何上报一次调用。

    把下面这段“上报”逻辑放进你流式对话的收尾处即可：
    拿到本次请求累计的 input_tokens / output_tokens（以及耗时），调用 report_trace。
    """
    model = "glm-4-flash"
    input_tokens = 1280      #  prompt 的 token 数
    output_tokens = 640      #  本次流式回复的 token 数
    latency_ms = 1200        #  从发请求到流式结束的耗时
    user_id = "u_1001"       #  业务侧自定义标签

    report_trace(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        status="success",
        source="NEXUS_AI",                  # 标识这是 NEXUS AI 的上报
        extra_metadata={"user_id": user_id},  # 业务标签进 metadata，不动字段规范
    )
    # 之后在 http://localhost:8000/ 即可看到 NEXUS_AI 的监测与成本预测；
    # 若有多个模型，用页面顶部的“模型筛选”下拉框切换查看。


if __name__ == "__main__":
    print("这是接入示例模块，直接运行仅演示一次上报（需后端已启动）：")
    _demo_for_nexus_ai()
