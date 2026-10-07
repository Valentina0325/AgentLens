"""简单移动平均预测次日成本（不使用任何机器学习库）。

逻辑：
1. 取最近 `days` 个自然日（含今天）的每日总成本，缺失日补 0。
2. 预测值 = 这 `days` 天每日成本的算术平均（简单移动平均）。
3. 若预测值超过预算阈值（默认 10.0），warning = true。
"""
import json
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .database import Trace


def _source_from_meta(meta_str: Optional[str]) -> str:
    """从 metadata(JSON 字符串) 提取 source；无则记为 unknown。"""
    if not meta_str:
        return "unknown"
    try:
        return json.loads(meta_str).get("source") or "unknown"
    except Exception:
        return "unknown"


def _daily_costs(
    db: Session, days: int, model: Optional[str] = None, source: Optional[str] = None
) -> List[Dict[str, Any]]:
    """返回最近 days 天（含今天）的每日总成本列表。

    每一天：筛选 [当天 00:00:00, 次日 00:00:00) 区间内的记录并求和。
    使用 ISO 字符串比较，timestamp 以 ISO 格式存储，字典序即时间序。
    model 非空时仅统计该模型的调用；source 非空时仅统计该来源（用于“按接入模型/项目监测”）。
    """
    today = datetime.now().date()
    result: List[Dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        next_day = day + timedelta(days=1)
        start_iso = day.isoformat() + "T00:00:00"
        end_iso = next_day.isoformat() + "T00:00:00"
        query = db.query(Trace).filter(
            Trace.timestamp >= start_iso, Trace.timestamp < end_iso
        )
        if model:
            query = query.filter(Trace.model == model)
        rows = query.all()
        if source:
            rows = [r for r in rows if _source_from_meta(r.meta) == source]
        total = sum((r.cost or 0.0) for r in rows)
        result.append({"date": day.isoformat(), "cost": round(total, 6)})
    return result


def predict_next_day_cost(
    db: Session,
    days: int = 7,
    threshold: float = 10.0,
    model: Optional[str] = None,
    source: Optional[str] = None,
) -> Dict[str, Any]:
    """预测明天的成本。

    返回历史列表、预测日期、预测成本、是否超阈值、阈值。
    model 或 source 非空时仅基于该模型/来源的调用进行预测。
    """
    history = _daily_costs(db, days, model=model, source=source)
    costs = [h["cost"] for h in history]
    predicted_cost = round(sum(costs) / len(costs), 6) if costs else 0.0
    predicted_date = (date.today() + timedelta(days=1)).isoformat()
    warning = predicted_cost > threshold
    return {
        "history": history,
        "predicted_date": predicted_date,
        "predicted_cost": predicted_cost,
        "warning": warning,
        "threshold": threshold,
    }
