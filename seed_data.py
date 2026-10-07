r"""生成模拟历史数据，用于快速体验 AgentLens 仪表盘。

运行方式（确保后端已停止或运行均可，脚本直接写 SQLite）：
    cd D:\ch4\Efficient\AgentLens
    python seed_data.py

然后用浏览器打开 http://localhost:8000/ 即可看到趋势图与饼图。
"""
import random
import uuid
from datetime import datetime, timedelta

from backend import cost
from backend.database import SessionLocal, Trace


MODELS = ["glm-4-flash", "gpt-4o", "claude-sonnet-4.6"]
STATUSES = ["success", "success", "success", "error", "timeout"]


def random_tokens(model: str) -> tuple[int, int]:
    """根据模型返回随机的输入/输出 token 数。"""
    if model == "glm-4-flash":
        return random.randint(200, 2000), random.randint(100, 800)
    if model == "gpt-4o":
        return random.randint(500, 4000), random.randint(200, 1500)
    return random.randint(800, 6000), random.randint(300, 2000)


def main() -> None:
    db = SessionLocal()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0

    # 清除旧数据（可选，若不想覆盖请注释掉）
    db.query(Trace).delete()

    for day_offset in range(7, 0, -1):
        date = today - timedelta(days=day_offset)
        # 每天 5~15 条调用，成本逐天轻微波动
        n_calls = random.randint(5, 15)
        for _ in range(n_calls):
            model = random.choice(MODELS)
            input_tokens, output_tokens = random_tokens(model)
            latency_ms = random.randint(80, 2500)
            status = random.choices(STATUSES, weights=[70, 0, 0, 20, 10])[0]

            # 均匀分布在当天 08:00~23:00
            hour = random.randint(8, 22)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            timestamp = date.replace(hour=hour, minute=minute, second=second)

            calculated_cost, currency = cost.calculate_cost(model, input_tokens, output_tokens)
            record = Trace(
                trace_id=f"trace-{day_offset}-{uuid.uuid4().hex[:6]}",
                span_id=f"span-{uuid.uuid4().hex[:12]}",
                parent_span_id=None,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                status=status,
                timestamp=timestamp.isoformat(),
                metadata=None,
                cost=calculated_cost,
                currency=currency,
            )
            db.add(record)
            total += 1

    db.commit()
    print(f"已生成 {total} 条模拟调用记录（最近 7 天）。")
    print("启动后端后访问 http://localhost:8000/ 查看仪表盘。")


if __name__ == "__main__":
    main()
