"""定价表加载与成本计算。

成本公式：
    cost = (input_tokens / 1_000_000) * input_per_million
         + (output_tokens / 1_000_000) * output_per_million

若模型不在定价表中，返回 (None, "UNKNOWN") 并在日志中警告。
"""
import json
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger("agentlens.cost")

# pricing.json 与当前文件同目录
_PRICING_PATH = os.path.join(os.path.dirname(__file__), "pricing.json")


def load_pricing() -> dict:
    """加载定价表 JSON。"""
    with open(_PRICING_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# 模块加载时读取一次（可观测模块，定价表不会频繁变更）
PRICING: dict = load_pricing()


def calculate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> Tuple[Optional[float], str]:
    """根据定价表计算单次调用成本。

    返回 (cost, currency)；模型未知时返回 (None, "UNKNOWN")。
    """
    info = PRICING.get(model)
    if not info:
        logger.warning("模型 %s 不在定价表中，成本记为 null", model)
        return None, "UNKNOWN"

    cost = (input_tokens / 1_000_000) * info["input_per_million"] + (
        output_tokens / 1_000_000
    ) * info["output_per_million"]
    # 保留 8 位小数，避免浮点噪声；展示层可再做四舍五入
    return round(cost, 8), info["currency"]
