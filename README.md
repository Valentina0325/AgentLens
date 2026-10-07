# AgentLens

Agent 调用链的可观测 + 成本预测模块。记录每次 LLM 调用的 token、延迟、成本，提供聚合查询与简单的次日成本趋势预测。

完整的自包含项目说明（功能、技术栈、数据模型、API、踩坑记录）见 [`项目介绍.md`](项目介绍.md)。本文件偏「怎么跑起来、怎么接进来」。

## 功能

- 记录 LLM 调用：`trace_id` / `span_id` / `model` / token 数 / 延迟 / 状态 / 时间戳
- 写入时按 `pricing.json` 自动计算成本，不硬编码
- 聚合查询：按 `model` / `date` / `status` 分组
- 简单移动平均（SMA）预测次日成本，超阈值返回 `warning`
- 单页 ECharts 仪表盘：成本趋势折线（含预测点）、模型成本饼图、最近调用表、按模型/来源筛选、超阈值预警横幅
- 零侵入接入任意 Python / Node.js AI 应用：每次 LLM 调用后上报一条记录即可

不引入 LangChain / ChromaDB / OpenTelemetry SDK 等重型依赖，预测只用简单移动平均，无机器学习库。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI + Python + SQLite + SQLAlchemy + Pydantic |
| 前端 | 单个 HTML 文件 + ECharts（CDN）+ 原生 JS |
| 测试 | Pytest + FastAPI TestClient |

## 项目结构

```
AgentLens/
├── backend/
│   ├── main.py              # FastAPI 入口，路由
│   ├── models.py            # Pydantic 模型 TraceSpan / TraceResponse
│   ├── database.py          # SQLAlchemy 引擎、Session、Trace ORM
│   ├── cost.py              # 定价表加载 + 成本计算
│   ├── predictor.py         # 移动平均预测
│   ├── integration_example.py # 上报函数（零依赖，可直接拷到别的项目）
│   ├── pricing.json         # 多模型定价表
│   └── requirements.txt
├── frontend/
│   └── index.html           # 单页仪表盘
├── tests/
│   └── test_api.py
├── seed_data.py             # 生成 7 天模拟数据
└── 项目介绍.md
```

## 快速开始

### 安装依赖

```bash
pip install -r backend/requirements.txt
```

### 启动后端

```bash
uvicorn backend.main:app --reload
```

启动后：

- API 文档（Swagger）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health → `{"status":"ok"}`

### 打开仪表盘

后端已把 `frontend/index.html` 挂到根路径，直接访问 http://localhost:8000/ 即可。

> 不要直接双击打开 `frontend/index.html`，那样会变成 `file://` 协议导致请求失败。必须经由后端服务访问。

### 灌入模拟数据

首次启动数据库为空，图表只有坐标轴。运行自带脚本生成 7 天三模型混合数据：

```bash
python seed_data.py
```

然后刷新仪表盘即可看到趋势、饼图与表格。

## 数据模型

上报一条 `TraceSpan`：

```json
{
  "trace_id": "trace-001",
  "span_id": "span-001",
  "model": "glm-4-flash",
  "input_tokens": 1000000,
  "output_tokens": 1000000,
  "latency_ms": 480,
  "status": "success",
  "timestamp": "2026-09-29T10:00:00",
  "metadata": {"source": "NEXUS_AI", "user_id": "u123"}
}
```

- `status` 取值：`success` / `error` / `timeout`
- `cost` / `currency` 由后端写入时自动计算，客户端不传
- `metadata` 是可扩展标签位。接入方身份建议放这里（如 `{"source": "NEXUS_AI"}`），不新增 top-level 字段
- `span_id` 幂等：重复上报返回已有记录（200），可安全重试

成本公式（见 `pricing.json`）：

```
cost = (input_tokens  / 1_000_000) * input_per_million
     + (output_tokens / 1_000_000) * output_per_million
```

模型不在定价表时 `cost = null`、`currency = "UNKNOWN"`。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/traces` | 记录一次调用，返回计算后的 `cost` / `currency` |
| GET | `/api/traces/summary?start=&end=&group_by=` | 聚合查询，按 `model` / `date` / `status` 分组 |
| GET | `/api/traces/prediction?days=7&threshold=10.0` | 移动平均预测次日成本，超阈值返回 `warning` |
| GET | `/api/traces?limit=20` | 最近调用列表 |
| GET | `/api/traces/models` | 已上报数据中出现的全部模型 |
| GET | `/api/traces/sources` | 已上报数据的全部来源（`metadata.source`）及数量 |
| GET | `/api/models/pricing` | 返回定价表 |
| GET | `/api/health` | 健康检查 |

`summary` / `prediction` / 列表接口均支持可选 `model` 与 `source` 参数，用于只看某个模型或接入项目的统计。

### 记录一次调用

```bash
curl -X POST http://localhost:8000/api/traces \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "trace-001",
    "span_id": "span-001",
    "model": "glm-4-flash",
    "input_tokens": 1000000,
    "output_tokens": 1000000,
    "latency_ms": 480,
    "status": "success",
    "timestamp": "2026-09-29T10:00:00",
    "metadata": {"source": "NEXUS_AI"}
  }'
```

响应：

```json
{ "span_id": "span-001", "cost": 0.3, "currency": "CNY", "message": "recorded" }
```

## 接入你的 AI 应用

核心就一步：**在每次 LLM 调用结束后，向 `POST /api/traces` 发一条 TraceSpan。** 仓库提供零依赖上报函数 `backend/integration_example.py::report_trace()`，可直接拷贝到你的项目里用（优先 requests，缺失时回退 urllib，无需额外安装）。

```python
from agentlens_reporter import report_trace   # 把 integration_example.py 拷过去改名即可

report_trace(
    base_url="http://localhost:8000",
    model="glm-4-flash",
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    latency_ms=latency_ms,
    status="success",
    source="NEXUS_AI",
    extra_metadata={"user_id": "u1001"},
)
```

`report_trace()` 容错：网络异常或依赖缺失时返回 `None` 且不抛异常，不阻塞主流程。

Node.js（Express + axios）示例：

```js
const AGENTLENS_BASE = process.env.AGENTLENS_BASE || 'http://localhost:8000'
async function reportToAgentLens({ model, inputTokens, outputTokens, latencyMs, status = 'success' }) {
  const payload = {
    trace_id: 'trace-' + Date.now() + '-' + Math.round(Math.random() * 1e9),
    span_id: 'span-' + Date.now() + '-' + Math.round(Math.random() * 1e9),
    model,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    latency_ms: latencyMs,
    status,
    timestamp: new Date().toISOString().slice(0, 19),
    metadata: { source: 'NEXUS_AI' }
  }
  try {
    const resp = await axios.post(`${AGENTLENS_BASE}/api/traces`, payload, { timeout: 3000 })
    console.log(`[AgentLens] 上报成功 -> ${resp.status}`)
  } catch (e) {
    console.error(`[AgentLens] 上报失败 -> ${e.message}`)
  }
}
```

上报失败不影响主对话；终端的 `[AgentLens]` 日志可用来排查（常见：AgentLens 未启动 / 地址不对）。

## 测试

```bash
pytest
```

测试使用独立临时 SQLite，每用例自动清空表。覆盖健康检查、定价、成本计算、未知模型、`span_id` 幂等、聚合、预测、列表、模型筛选。
