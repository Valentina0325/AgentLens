# AgentLens · Agent 调用链可观测与成本预测模块

> 📘 **给外部 AI / 新人看的完整项目说明**见 [`项目介绍.md`](项目介绍.md)（自包含，含功能、技术栈、数据模型、API、接入方式与踩坑记录）。
> 本 README 聚焦启动、API 与日常使用。

## 一、项目定位

**一句话描述**：记录 Agent 每次 LLM 调用的 token、延迟、成本，提供聚合查询与未来成本趋势预测，帮助开发者发现高成本调用并做预算预警。

**核心目标**：用最小实现验证“Agent 可观测性”的核心链路——

> 调用记录 → 成本计算 → 聚合展示 → 趋势预测

**不涉及**：LLM-as-Judge、安全扫描、数据集管理、多策略评估、RAG 指标计算。本模块只做可观测与成本预测。

## 二、技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI + Python 3.11 + SQLite + SQLAlchemy + Pydantic |
| 前端 | 单个 HTML 文件 + ECharts（CDN 引入），原生 JS，无框架 |
| 测试 | Pytest + FastAPI TestClient（httpx） |

> 不引入 LangChain / ChromaDB / OpenTelemetry SDK 等重型依赖。

## 三、文件结构

```
AgentLens/                      # 仓库名 agent-lens
├── backend/
│   ├── main.py              # FastAPI 入口，路由定义
│   ├── models.py            # Pydantic 模型：TraceSpan, TraceResponse 等
│   ├── database.py          # SQLAlchemy 引擎、Session、Base、Trace ORM
│   ├── cost.py              # 定价表加载 + 成本计算
│   ├── predictor.py         # 移动平均预测
│   ├── integration_example.py # NEXUS AI / 任意 AI 应用接入示例（上报函数）
│   ├── pricing.json         # 定价表（多模型、多币种）
│   ├── __init__.py
│   └── requirements.txt
├── frontend/
│   └── index.html           # 单页应用，ECharts CDN，调用后端 API
├── tests/
│   └── test_api.py          # Pytest 测试：记录、查询、预测
├── seed_data.py             # 生成 7 天模拟数据，供快速体验仪表盘
├── README.md                # 启动 / API / 接入指南
├── 项目介绍.md               # 完整项目说明（自包含，可交给外部 AI 理解项目）
└── .gitignore
```

## 四、字段与命名说明

字段命名遵循 **OpenTelemetry GenAI 语义约定** 的精神，例如：

- `input_tokens` 对应 `gen_ai.usage.input_tokens`
- `output_tokens` 对应 `gen_ai.usage.output_tokens`
- `model` 对应 `gen_ai.request.model`

本模块仅做命名参考与简化，并不引入 OpenTelemetry SDK。

**TraceSpan 关键字段**：`trace_id`、`span_id`、`parent_span_id`、`model`、`input_tokens`、`output_tokens`、`latency_ms`、`status`(success/error/timeout)、`timestamp`、`metadata`(可选 dict)。`cost` 与 `currency` 由后端在写入时自动计算，客户端无需提供。

**成本公式**（见 `pricing.json`）：

```
cost = (input_tokens / 1_000_000) * input_per_million
     + (output_tokens / 1_000_000) * output_per_million
```

模型不在定价表中时，`cost = null`、`currency = "UNKNOWN"`，并在日志中警告。

## 五、快速开始

### 1. 安装依赖

```bash
cd <项目根目录>
pip install -r backend/requirements.txt
```

### 2. 启动后端

```bash
uvicorn backend.main:app --reload
```

启动后：

- API 文档（Swagger）：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health> → `{"status":"ok"}`

### 3. 打开前端

后端已把 `frontend/index.html` 挂载到根路径，直接访问：

```
http://localhost:8000/
```

> 不要直接双击打开 `frontend/index.html`（那样会变成 `file://` 协议，导致请求失败并报 "Unexpected end of JSON input"）。
> 若前后端必须分开部署，再修改 `index.html` 顶部的 `const API = "";` 为后端地址，例如 `http://localhost:8000`。

前端包含：

1. **成本趋势折线图**：历史 7 天 + 预测点（红色虚线/菱形标记）。
2. **模型成本饼图**：按模型分组显示成本占比。
3. **最近调用表格**：最近 20 条记录。
4. **模型筛选下拉框**：自动列出已检测到的模型，切换即可只看该模型的监测与预测。
5. **来源筛选下拉框**：自动列出已检测到的来源/项目（如 `NEXUS_AI`），切换即可单独查看某个接入项目的监测与预测；表格额外显示“来源”列。
6. **刷新按钮 + API 文档按钮**：重新拉取数据 / 一键跳转 Swagger；预测超阈值时顶部显示红色预警横幅。

## 六、快速体验（模拟数据）

首次启动后数据库是空的，图表只有坐标轴。运行自带脚本生成 7 天模拟数据：

```bash
python seed_data.py
```

然后刷新 `http://localhost:8000/`，即可看到：

- 7 天成本趋势折线 + 次日预测点
- 按模型（glm-4-flash / gpt-4o / claude-sonnet-4.6）分组的成本饼图
- 最近 20 条调用表格

## 七、API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/traces` | 记录一次 LLM 调用，返回计算后的 `cost`/`currency` |
| GET | `/api/traces/summary?start=&end=&group_by=` | 聚合查询，按 `model`/`date`/`status` 分组 |
| GET | `/api/traces/prediction?days=7&threshold=10.0` | 简单移动平均预测次日成本，超阈值返回 `warning` |
| GET | `/api/models/pricing` | 返回 `pricing.json` 定价表 |
| GET | `/api/health` | 健康检查 |
| GET | `/api/traces?limit=20` | 最近调用列表（前端表格用，任务书前端必需的最小补充接口） |
| GET | `/api/traces/models` | 返回已上报数据中出现的全部模型（“已接入检测的模型”列表） |
| GET | `/api/traces/sources` | 返回已上报数据中出现的全部来源/项目（`metadata.source`，如 `NEXUS_AI`）及各自数量 |

> 上述 `summary` / `prediction` / `list_traces` 三个接口均支持可选的 `model` 与 `source` 参数（如 `?model=glm-4-flash&source=NEXUS_AI`），传入后仅统计匹配模型/来源的调用——用于“按接入的模型/项目进行监测与预测”。`source` 对应上报数据 `metadata.source` 字段，未带该字段的记录记为 `unknown`。

### 示例：记录一次调用

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
    "metadata": {"prompt_version": "v2", "user_id": "u123"}
  }'
```

响应：

```json
{ "span_id": "span-001", "cost": 0.3, "currency": "CNY", "message": "recorded" }
```

## 八、两种监测模式（设计核心）

AgentLens 同时支持两种数据来源，**互不冲突**：

| 模式 | 谁在用 | 数据怎么来 | 适用场景 |
| --- | --- | --- | --- |
| **A. 自动监测接入的模型/项目** | NEXUS AI 等真实 AI 应用 | 接入方在每次 LLM 调用后自动 `POST /api/traces` 上报 | 生产环境持续观测成本与趋势 |
| **B. 手动 API 测试** | 开发者 | 在 `/docs` 里手填参数发送，或 `python seed_data.py` 灌模拟数据 | 本地验证、演示、调参 |

两种模式写入的是同一张 `traces` 表，仪表盘统一展示。前端顶部「模型筛选」下拉框会自动列出**已检测到的模型**，切换即可只看某个接入模型的监测与预测成本。

> **关于“项目/接入方”身份**：任务书 §2.1 要求字段严格按表，不再新增 top-level 字段。因此“是哪个项目接入的”统一放进 `metadata`，例如 `metadata={"source":"NEXUS_AI"}`。仪表盘以 `model` 为主要监测维度，项目身份作为可扩展标签保留。

### 模式 A：接入 NEXUS AI（或其他 AI 应用）

AgentLens 没有黑盒，接入只需一步：**在每次 LLM 调用结束后，向 `POST /api/traces` 发送一条 TraceSpan 即可。** 仓库已提供现成函数 `backend/integration_example.py::report_trace()`，复制或导入即可用。

> **跨项目接入（NEXUS AI 是独立项目时）**：直接把 `backend/integration_example.py` 整个文件**拷贝**到 NEXUS AI 的任意目录/模块里（例如 `nexus/agentlens_reporter.py`），然后 `from agentlens_reporter import report_trace`。该函数**零第三方依赖**（优先 requests，未安装时自动回退标准库 urllib），拷贝过去就能用，无需在 NEXUS AI 项目里额外 `pip install`。

```python
# 在 NEXUS AI 流式对话结束、拿到最终 token 数后调用一次
from agentlens_reporter import report_trace   # 或 from backend.integration_example import report_trace

report_trace(
    base_url="http://localhost:8000",          # 部署后改成 AgentLens 实际地址
    model="glm-4-flash",
    input_tokens=input_tokens,     # 本次 prompt 的 token 数
    output_tokens=output_tokens,   # 本次流式回复的 token 数
    latency_ms=latency_ms,         # 发请求到流式结束的耗时(ms)
    status="success",              # success / error / timeout
    source="NEXUS_AI",             # 写入 metadata.source，标识接入方
    extra_metadata={"user_id": "u1001"},
)
```

`report_trace()` 已做容错：网络异常或依赖缺失时返回 `None` 且**不抛异常**，绝不阻塞主对话流程；后端 `span_id` 重复时也按幂等返回已有记录（200，message=`already recorded`），可安全重试。接入后访问 `http://localhost:8000/` 即可看到 NEXUS_AI 的监测与成本预测。

更底层的接入（不依赖本仓库函数）示例：

```python
import json
import urllib.request
from datetime import datetime

def report_to_agentlens(model, input_tokens, output_tokens, latency_ms,
                        status="success", source="NEXUS_AI"):
    payload = {
        "trace_id": "trace-" + __import__("uuid").uuid4().hex[:12],
        "span_id": "span-" + __import__("uuid").uuid4().hex[:12],
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "latency_ms": latency_ms,
        "status": status,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "metadata": {"source": source},
    }
    req = urllib.request.Request(
        "http://localhost:8000/api/traces",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass  # 上报失败不影响主对话
```

要点：

- `trace_id` 串联同一次用户请求内的多次 LLM 调用；`span_id` 每次唯一。**接口对 `span_id` 做幂等保护**：同一 `span_id` 重复上报时直接返回已有记录（200），不报错，便于重试与手动重复测试。
- `status` 用 `error`/`timeout` 记录失败调用，便于在聚合中按状态下钻。
- `metadata` 放自定义标签（接入方、版本、用户、场景），后续可按需扩展分析。
- 上报建议走旁路/异步，避免影响主调用延迟。

### Node.js 项目接入（NEXUS AI 实际形态）

NEXUS AI 后端是 **Node.js**（Express + axios 流式调用智谱 BigModel SSE）。接入代码已直接写入其 `index.js` 的 `/api/chat` 路由：定义 `reportToAgentLens()`（用 axios 上报，零额外依赖），在流式解析中捕获智谱最后一个 chunk 的 `usage.prompt_tokens` / `completion_tokens`，于流 `end` / `error` 时上报一次。核心片段：

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
    console.log(`[AgentLens] 上报成功 model=${model} in=${inputTokens} out=${outputTokens} status=${status} -> ${resp.status}`)
  } catch (e) {
    // 上报失败不影响主对话；但打印原因便于排查（常见：AgentLens 未启动 / 端口不对 / 地址不可达）
    const detail = e.response ? `${e.response.status} ${JSON.stringify(e.response.data)}` : e.message
    console.error(`[AgentLens] 上报失败 model=${model} -> ${detail}`)
  }
}
```

> 注：上方 Python 版 `integration_example.py` 适用于 Python 项目；NEXUS AI 是 Node 项目，请使用上述 JS 片段（已落地到其 `index.js`）。部署时在 NEXUS AI 的 `.env` 加 `AGENTLENS_BASE=<AgentLens 实际地址>`，本地默认 `http://localhost:8000`。
>
> **排查技巧**：现在上报成功/失败都会在 NEXUS AI 运行终端打印 `[AgentLens]` 日志。跑一次对话后看终端：若看到「上报成功」则数据已进库；若看到「上报失败 ECONNREFUSED」之类，说明 AgentLens 没在 `localhost:8000` 运行，或地址不对。

### 模式 B：手动 API 测试

- **Swagger**：`http://localhost:8000/docs` → `POST /api/traces` → Try it out → 填入参数 → Execute。页面右上角也有「🔗 API 文档」按钮一键跳转。
- **模拟数据**：`python seed_data.py` 生成 7 天三模型混合数据，刷新页面即可看效果。
- **curl**：见上方「示例：记录一次调用」。

## 九、测试

```bash
pytest
```

测试使用独立的临时 SQLite 数据库，每个用例自动清空表，互不干扰。覆盖：健康检查、定价表、成本计算、未知模型、`span_id` 幂等（重复上报返回已有记录）、聚合查询（含非法 `group_by`）、预测、列表、模型筛选接口。

## 十、验收对照

- [x] 启动后端后 `/docs` 可见全部 API
- [x] `POST /api/traces` 返回计算后的 cost
- [x] `agent_lens.db` 中可查到记录
- [x] `GET /api/traces/summary?group_by=model` 返回按模型聚合成本
- [x] `GET /api/traces/prediction` 返回历史 7 天成本与预测值
- [x] 前端展示折线图、饼图、表格、模型筛选，数据与后端一致
- [x] `pytest` 全部通过
- [x] README 含清晰启动步骤与项目说明
- [x] 支持按 `model` 筛选监测/预测 + 列出已接入模型（`/api/traces/models`）
- [x] 提供 NEXUS AI 接入示例（`backend/integration_example.py`）

## 十一、注意事项

- 不要引入重型依赖（LangChain / ChromaDB / OpenTelemetry SDK）。
- 所有代码可直接运行，无 `TODO`。
- 字段命名严格按第二节，不随意更改。
- 成本计算来自 `pricing.json`，不硬编码。
- 预测使用简单移动平均（过去 N 天平均），无机器学习库。
- 前端仅原生 JS + ECharts CDN，无 React/Vue。
