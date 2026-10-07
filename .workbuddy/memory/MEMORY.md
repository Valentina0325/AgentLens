# AgentLens 项目长期记忆

## 项目定位
AgentLens = FastAPI + 单页 ECharts 的「Agent 可观测 / 成本预测」模块。
任务书原始文件名：`D:\ch4\Efficient\AgentLens .md`（带空格）。
启动：项目根目录 `uvicorn backend.main:app --reload`，仪表盘 `http://localhost:8000/`。
受管 Python venv：`C:\Users\mei\.workbuddy\binaries\python\envs\default`。

## 关键设计纪律（对照任务书，不得跑偏）
- `TraceSpan` 字段严格按任务书 §2.1；**不得新增 top-level 字段**。项目/接入方身份统一放 `metadata`（如 `{"source":"NEXUS_AI"}`）。
- 数据模型：models.py 只用规范字段；`timestamp` 为 **str（ISO 字符串）**，非 datetime（避免 Swagger date-time 校验标红）。
- `span_id` 幂等：重复上报返回已有记录（200, message="already recorded"），不抛 409。

## 接入方：NEXUS AI（用户自研智能对话助手，流式输出）
- 技术栈：后端为 **Node.js（Express + axios 调智谱 BigModel SSE 流式）**，模型 glm-4-flash；**不是 Python**。前端另有独立仓库。
- 接入方式：**已直接改写 NEXUS AI 的 `index.js`**——在 `/api/chat` 路由内新增 `reportToAgentLens()`（axios 上报，零额外依赖），流式解析捕获智谱最后一个 chunk 的 `usage.prompt_tokens/completion_tokens`，于流 `end`/`error` 事件上报一次；用 `reported` 标志防重复上报。`AGENTLENS_BASE` 环境变量控制上报地址，默认 `http://localhost:8000`。
- token 取值：智谱 SSE 流最后一个 `data:` chunk 含 `usage` 字段；`latency_ms` 用 `Date.now()` 前后差。
- 多轮/多步调用：每步各上报一次，`trace_id` 用时间戳+随机数（未串联同请求）；`span_id` 自动唯一。
- 注意：AgentLens 的 `backend/integration_example.py` 是 **Python 版**，NEXUS AI 用不上；README 第八节已补 Node.js 接入小节。

## 接入方 2：MiniAgentRuntime（用户第二个自研 Agent 运行时，TypeScript）
- 工作空间：`D:\ch4\Efficient\MiniAgentRuntime`。定位：零依赖 TS Agent 运行时（主循环/只读并行+写入串行调度/MCP/上下文压缩/Checkpoint）。
- 接入方式：`src/observability/reporter.ts` 在每次 LLM 调用后 POST `/api/traces`；`metadata.source = MINI_AGENT_RUNTIME`（另带 step、tool_calls），上报失败仅打日志不阻塞。地址由 `AGENTLENS_BASE` 控制，默认 `http://localhost:8000`。
- **字段纪律**：`status` 必须为 §2.1 的 success/error/timeout。MiniAgentRuntime 初版误用 `'ok'`（Pydantic 是纯 str 不会 422，但会污染 status 分组），2026-10-06 已改为 `'success'`。
- 联调已实证（2026-10-06）：`/api/traces/sources` 现为 `MINI_AGENT_RUNTIME(4)` / `NEXUS_AI(5)` / `unknown(58)` 三来源并列，cost 按 pricing.json 自动计算。NEXUS_AI 历史数据未受影响。
