"""FastAPI 入口：实现第三节定义的全部 API。

启动：
    cd <项目根目录>
    uvicorn backend.main:app --reload
文档：
    http://localhost:8000/docs
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import cost, predictor
from .database import Base, SessionLocal, Trace, engine
from .models import (
    PredictionResponse,
    SummaryResponse,
    TraceListItem,
    TraceResponse,
    TraceSpan,
)

# 启动时建表（幂等）
Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentlens")

app = FastAPI(
    title="AgentLens",
    version="1.0.0",
    description="Agent 调用链可观测与成本预测模块",
)

# 允许前端本地文件（file:// 或任意本地端口）跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Session:
    """依赖注入：为每个请求提供数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _source_from_meta(meta_str: Optional[str]) -> str:
    """从 metadata(JSON 字符串) 中提取 source 标识；无则记为 unknown。"""
    if not meta_str:
        return "unknown"
    try:
        data = json.loads(meta_str)
        return data.get("source") or "unknown"
    except Exception:
        return "unknown"


@app.get("/api/health")
def health() -> Dict[str, str]:
    """健康检查。"""
    return {"status": "ok"}


@app.post("/api/traces", response_model=TraceResponse)
def create_trace(span: TraceSpan, db: Session = Depends(get_db)) -> TraceResponse:
    """记录一次 LLM 调用，后端自动计算 cost / currency。

    对 span_id 做幂等保护：若同一 span_id 已存在，直接返回已有记录（200），
    不抛 409——遥测场景下重复上报应被忽略而非报错。
    """
    existing = db.query(Trace).filter(Trace.span_id == span.span_id).first()
    if existing:
        return TraceResponse(
            span_id=existing.span_id,
            cost=existing.cost,
            currency=existing.currency,
            message="already recorded",
        )

    calculated_cost, currency = cost.calculate_cost(
        span.model, span.input_tokens, span.output_tokens
    )

    record = Trace(
        trace_id=span.trace_id,
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        model=span.model,
        input_tokens=span.input_tokens,
        output_tokens=span.output_tokens,
        latency_ms=span.latency_ms,
        status=span.status,
        timestamp=span.timestamp,
        meta=json.dumps(span.metadata, ensure_ascii=False) if span.metadata is not None else None,
        cost=calculated_cost,
        currency=currency,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("记录调用 span_id=%s model=%s cost=%s", record.span_id, record.model, calculated_cost)
    return TraceResponse(span_id=record.span_id, cost=calculated_cost, currency=currency, message="recorded")


@app.get("/api/traces/summary", response_model=SummaryResponse)
def get_summary(
    start: str = Query(None, description="开始日期 YYYY-MM-DD，含当天"),
    end: str = Query(None, description="结束日期 YYYY-MM-DD，含当天"),
    group_by: str = Query("model", description="分组维度：model / date / status"),
    model: Optional[str] = Query(None, description="仅统计该模型（按接入模型监测，可选）"),
    source: Optional[str] = Query(None, description="仅统计该来源（如 NEXUS_AI，按接入项目监测，可选）"),
    db: Session = Depends(get_db),
) -> SummaryResponse:
    """按维度聚合查询成本、token 与调用次数。

    若传入 model，则仅聚合该模型的调用；若传入 source，则仅聚合该来源的调用——
    这是“根据接入的模型/项目进行监测”的支撑能力。
    """
    if group_by not in ("model", "date", "status"):
        raise HTTPException(status_code=400, detail="group_by 仅支持 model / date / status")

    query = db.query(Trace)
    if model:
        query = query.filter(Trace.model == model)
    if start:
        query = query.filter(Trace.timestamp >= start + "T00:00:00")
    if end:
        next_day = (datetime.fromisoformat(end) + timedelta(days=1)).isoformat()
        query = query.filter(Trace.timestamp < next_day + "T00:00:00")
    rows = query.all()
    if source:
        rows = [r for r in rows if _source_from_meta(r.meta) == source]

    groups_map: Dict[Any, Dict[str, Any]] = {}
    total_cost = 0.0
    total_in = 0
    total_out = 0

    for r in rows:
        key = {"model": r.model, "date": r.timestamp[:10], "status": r.status}[group_by]
        bucket = groups_map.setdefault(
            key, {"cost": 0.0, "input_tokens": 0, "output_tokens": 0, "call_count": 0}
        )
        bucket["cost"] += r.cost or 0.0
        bucket["input_tokens"] += r.input_tokens
        bucket["output_tokens"] += r.output_tokens
        bucket["call_count"] += 1
        total_cost += r.cost or 0.0
        total_in += r.input_tokens
        total_out += r.output_tokens

    groups: List[Dict[str, Any]] = []
    for key, bucket in groups_map.items():
        item = {
            group_by: key,
            "cost": round(bucket["cost"], 6),
            "input_tokens": bucket["input_tokens"],
            "output_tokens": bucket["output_tokens"],
            "call_count": bucket["call_count"],
        }
        groups.append(item)

    return SummaryResponse(
        total_cost=round(total_cost, 6),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        groups=groups,
    )


@app.get("/api/traces/prediction", response_model=PredictionResponse)
def get_prediction(
    days: int = Query(7, ge=1, le=90, description="回溯天数，默认 7"),
    threshold: float = Query(10.0, description="预算阈值，超过则 warning"),
    model: Optional[str] = Query(None, description="仅基于该模型预测（按接入模型预测，可选）"),
    source: Optional[str] = Query(None, description="仅基于该来源预测（如 NEXUS_AI，可选）"),
    db: Session = Depends(get_db),
) -> PredictionResponse:
    """基于过去 days 天的每日总成本，用简单移动平均预测明天成本。

    若传入 model 或 source，则仅基于该模型/来源的调用进行预测。
    """
    return predictor.predict_next_day_cost(db, days=days, threshold=threshold, model=model, source=source)


@app.get("/api/models/pricing")
def get_pricing() -> Dict[str, Any]:
    """返回定价表（pricing.json 内容）。"""
    return cost.PRICING


@app.get("/api/traces/models", response_model=List[str])
def list_models(db: Session = Depends(get_db)) -> List[str]:
    """返回已上报数据中出现的全部模型（即“已接入检测的模型”列表）。

    供前端下拉框使用，让用户可切换查看不同接入模型的监测与预测。
    """
    rows = db.query(Trace.model).distinct().all()
    return sorted({r.model for r in rows})


@app.get("/api/traces/sources", response_model=List[Dict[str, Any]])
def list_sources(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """返回已上报数据中出现的全部来源（即“已接入检测的项目”列表，如 NEXUS_AI）。

    供前端下拉框使用，让用户可单独查看某个接入项目（来源）的监测与预测。
    """
    rows = db.query(Trace.meta).all()
    counter: Dict[str, int] = {}
    for (meta_str,) in rows:
        s = _source_from_meta(meta_str)
        counter[s] = counter.get(s, 0) + 1
    return [{"source": k, "count": v} for k, v in sorted(counter.items())]


@app.get("/api/traces", response_model=List[TraceListItem])
def list_traces(
    limit: int = Query(20, ge=1, le=100, description="返回最近 N 条"),
    model: Optional[str] = Query(None, description="仅返回该模型（按接入模型监测，可选）"),
    source: Optional[str] = Query(None, description="仅返回该来源（如 NEXUS_AI，按接入项目监测，可选）"),
    db: Session = Depends(get_db),
) -> List[TraceListItem]:
    """返回最近的调用记录（供前端表格使用）。

    注：任务书前端要求展示“最近 20 条调用记录”，但第三节未显式定义列表接口，
    此处作为前端必需的最小补充接口提供。model/source 非空时仅返回匹配的模型/来源记录。
    """
    query = db.query(Trace)
    if model:
        query = query.filter(Trace.model == model)
    rows = query.order_by(Trace.id.desc()).all()
    if source:
        rows = [r for r in rows if _source_from_meta(r.meta) == source]
    rows = rows[:limit]
    result: List[TraceListItem] = []
    for r in rows:
        result.append(
            TraceListItem(
                span_id=r.span_id,
                trace_id=r.trace_id,
                model=r.model,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                latency_ms=r.latency_ms,
                status=r.status,
                timestamp=r.timestamp,
                cost=r.cost,
                currency=r.currency,
                metadata=json.loads(r.meta) if r.meta else None,
            )
        )
    return result


@app.get("/favicon.ico")
def favicon() -> Response:
    """浏览器自动请求 /favicon.ico，返回 204 避免 404 日志噪音。"""
    return Response(status_code=204)


# 将 frontend/index.html 作为单页应用挂载到根路径，访问 http://localhost:8000/ 即可打开仪表盘。
# API 路由优先匹配，未命中的路径回退到静态文件（html=True）。
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
