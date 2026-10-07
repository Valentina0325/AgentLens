"""Pydantic 数据模型定义。

字段命名遵循 OpenTelemetry GenAI 语义约定的精神：
- `input_tokens` 对应 `gen_ai.usage.input_tokens`
- `output_tokens` 对应 `gen_ai.usage.output_tokens`
- `model` 对应 `gen_ai.request.model`
本文件仅做命名参考与简化，不引入 OpenTelemetry SDK。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TraceSpan(BaseModel):
    """单次 LLM 调用记录（客户端上报，不含 cost / currency，由后端计算）。"""

    trace_id: str = Field(..., description="一次用户请求的调用链 ID，同一请求多次调用共享")
    span_id: str = Field(..., description="单次 LLM 调用的唯一 ID")
    parent_span_id: Optional[str] = Field(None, description="父 span ID，无则为 null")
    model: str = Field(..., description="模型名，如 glm-4-flash / gpt-4o")
    input_tokens: int = Field(..., ge=0, description="输入 token 数")
    output_tokens: int = Field(..., ge=0, description="输出 token 数")
    latency_ms: int = Field(..., ge=0, description="调用耗时（毫秒）")
    status: str = Field(..., description="success / error / timeout")
    timestamp: str = Field(..., description="调用发生时间，ISO 8601 字符串，如 2026-09-29T10:00:00")
    metadata: Optional[Dict[str, Any]] = Field(None, description="自定义标签，如 prompt_version / user_id")


class TraceResponse(BaseModel):
    """记录接口响应：返回后端计算后的 cost / currency。"""

    span_id: str
    cost: Optional[float] = None
    currency: str
    message: str = "recorded"


class SummaryResponse(BaseModel):
    """聚合查询响应。groups 中分组键名与 group_by 一致（model / date / status）。"""

    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    groups: List[Dict[str, Any]]


class PredictionResponse(BaseModel):
    """成本趋势预测响应。"""

    history: List[Dict[str, Any]]  # [{"date": "YYYY-MM-DD", "cost": float}, ...]
    predicted_date: str
    predicted_cost: float
    warning: bool
    threshold: float


class TraceListItem(BaseModel):
    """最近调用列表项（供前端表格使用）。"""

    span_id: str
    trace_id: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: str
    timestamp: str
    cost: Optional[float] = None
    currency: str
    metadata: Optional[Dict[str, Any]] = None
