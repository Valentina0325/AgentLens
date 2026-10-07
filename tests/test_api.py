"""AgentLens API 测试（FastAPI TestClient）。

运行方式（在项目根目录）：
    pytest

测试使用独立的临时 SQLite 数据库，并自动清空表，互不干扰。
"""
import os
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 将项目根目录加入路径，便于导入 backend 包
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.database import Base, Trace  # noqa: E402
from backend.main import app, get_db  # noqa: E402

# 独立测试数据库（临时文件）
_TEST_DB = os.path.join(tempfile.gettempdir(), "agent_lens_test.db")
_test_engine = create_engine(
    f"sqlite:///{_TEST_DB}", connect_args={"check_same_thread": False}
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
Base.metadata.create_all(bind=_test_engine)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _clear_tables():
    """每个测试前清空 traces 表，保证用例独立。"""
    with _TestingSessionLocal() as db:
        db.execute(text("DELETE FROM traces"))
        db.commit()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def _sample_span(span_id="s1", model="glm-4-flash", **overrides):
    payload = {
        "trace_id": "t1",
        "span_id": span_id,
        "model": model,
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "latency_ms": 500,
        "status": "success",
        "timestamp": "2026-09-29T10:00:00",
        "metadata": {"prompt_version": "v2"},
    }
    payload.update(overrides)
    return payload


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_pricing(client):
    r = client.get("/api/models/pricing")
    assert r.status_code == 200
    data = r.json()
    assert "glm-4-flash" in data
    assert data["glm-4-flash"]["currency"] == "CNY"


def test_create_trace_cost_calculated(client):
    # glm-4-flash: 0.1/1M 输入 + 0.2/1M 输出 -> 各 100 万 token 时 cost = 0.3
    r = client.post("/api/traces", json=_sample_span())
    assert r.status_code == 200
    body = r.json()
    assert body["span_id"] == "s1"
    assert abs(body["cost"] - 0.3) < 1e-9
    assert body["currency"] == "CNY"
    assert body["message"] == "recorded"


def test_create_trace_unknown_model(client):
    r = client.post("/api/traces", json=_sample_span(span_id="s2", model="unknown-model"))
    assert r.status_code == 200
    body = r.json()
    assert body["cost"] is None
    assert body["currency"] == "UNKNOWN"


def test_create_trace_duplicate_span_id_idempotent(client):
    r1 = client.post("/api/traces", json=_sample_span(span_id="dup"))
    r2 = client.post("/api/traces", json=_sample_span(span_id="dup"))
    # 重复 span_id 应幂等返回已有记录（200），而非 409
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json()["message"] == "already recorded"
    # 数据库里只应有一条记录
    with _TestingSessionLocal() as db:
        assert db.query(Trace).filter(Trace.span_id == "dup").count() == 1


def test_summary_group_by_model(client):
    client.post("/api/traces", json=_sample_span(span_id="a", model="glm-4-flash"))
    client.post("/api/traces", json=_sample_span(span_id="b", model="gpt-4o"))
    r = client.get("/api/traces/summary?group_by=model")
    assert r.status_code == 200
    data = r.json()
    # glm-4-flash 成本 0.3；gpt-4o: 2.5+10.0 = 12.5
    assert abs(data["total_cost"] - (0.3 + 12.5)) < 1e-6
    assert data["total_input_tokens"] == 2_000_000
    by_model = {g["model"]: g for g in data["groups"]}
    assert abs(by_model["glm-4-flash"]["cost"] - 0.3) < 1e-9
    assert by_model["glm-4-flash"]["call_count"] == 1


def test_summary_group_by_date(client):
    r = client.get("/api/traces/summary?group_by=date")
    assert r.status_code == 200
    assert all("date" in g for g in r.json()["groups"])


def test_summary_invalid_group_by(client):
    r = client.get("/api/traces/summary?group_by=foo")
    assert r.status_code == 400


def test_prediction(client):
    # 插入今日两条调用，便于验证移动平均逻辑
    client.post("/api/traces", json=_sample_span(span_id="p1"))
    client.post("/api/traces", json=_sample_span(span_id="p2", input_tokens=2_000_000, output_tokens=2_000_000))
    # 今日合计成本 = 0.3 + (0.2 + 0.4) = 0.9
    r = client.get("/api/traces/prediction?days=7")
    assert r.status_code == 200
    data = r.json()
    assert len(data["history"]) == 7
    # 仅今天有数据，其余 6 天为 0 -> 预测 = 0.9 / 7
    assert abs(data["predicted_cost"] - (0.9 / 7)) < 1e-6
    assert isinstance(data["warning"], bool)


def test_list_traces(client):
    client.post("/api/traces", json=_sample_span(span_id="l1"))
    client.post("/api/traces", json=_sample_span(span_id="l2"))
    r = client.get("/api/traces?limit=20")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert rows[0]["span_id"] == "l2"  # 最新在前


def test_models_endpoint_lists_distinct_models(client):
    client.post("/api/traces", json=_sample_span(span_id="m1", model="glm-4-flash"))
    client.post("/api/traces", json=_sample_span(span_id="m2", model="gpt-4o"))
    client.post("/api/traces", json=_sample_span(span_id="m3", model="gpt-4o"))
    r = client.get("/api/traces/models")
    assert r.status_code == 200
    models = r.json()
    assert set(models) == {"glm-4-flash", "gpt-4o"}


def test_summary_model_filter(client):
    client.post("/api/traces", json=_sample_span(span_id="f1", model="glm-4-flash"))
    client.post("/api/traces", json=_sample_span(span_id="f2", model="gpt-4o"))
    # 仅统计 glm-4-flash
    r = client.get("/api/traces/summary?group_by=model&model=glm-4-flash")
    assert r.status_code == 200
    data = r.json()
    assert abs(data["total_cost"] - 0.3) < 1e-9
    assert {g["model"] for g in data["groups"]} == {"glm-4-flash"}


def test_prediction_model_filter(client):
    client.post("/api/traces", json=_sample_span(span_id="pf1", model="glm-4-flash"))
    client.post("/api/traces", json=_sample_span(span_id="pf2", model="gpt-4o", input_tokens=2_000_000, output_tokens=2_000_000))
    # 仅 glm-4-flash：今日 0.3，其余 6 天 0 -> 预测 0.3/7
    r = client.get("/api/traces/prediction?days=7&model=glm-4-flash")
    assert r.status_code == 200
    assert abs(r.json()["predicted_cost"] - (0.3 / 7)) < 1e-6


def test_list_model_filter(client):
    client.post("/api/traces", json=_sample_span(span_id="lf1", model="glm-4-flash"))
    client.post("/api/traces", json=_sample_span(span_id="lf2", model="gpt-4o"))
    r = client.get("/api/traces?limit=20&model=gpt-4o")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["model"] == "gpt-4o"


def test_metadata_stored_and_propagated(client):
    r = client.post("/api/traces", json=_sample_span(
        span_id="md1", model="glm-4-flash", metadata={"source": "NEXUS_AI"}
    ))
    assert r.status_code == 200
    # 列表接口应回传解析后的 metadata，且包含 source
    rows = client.get("/api/traces?limit=20").json()
    assert rows[0]["metadata"] == {"source": "NEXUS_AI"}
    # 数据库列应确实写入（不出现 metadata 被丢弃为 None 的回归）
    with _TestingSessionLocal() as db:
        rec = db.query(Trace).filter(Trace.span_id == "md1").first()
        assert rec.meta is not None
        assert "NEXUS_AI" in rec.meta


def test_sources_endpoint_and_filter(client):
    client.post("/api/traces", json=_sample_span(
        span_id="src1", model="glm-4-flash", metadata={"source": "NEXUS_AI"}
    ))
    client.post("/api/traces", json=_sample_span(
        span_id="src2", model="gpt-4o", metadata={"source": "OTHER_APP"}
    ))
    client.post("/api/traces", json=_sample_span(
        span_id="src3", model="claude-sonnet-4.6"
    ))  # 无 source -> unknown
    r = client.get("/api/traces/sources")
    assert r.status_code == 200
    sources = {it["source"]: it["count"] for it in r.json()}
    assert sources.get("NEXUS_AI") == 1
    assert sources.get("OTHER_APP") == 1
    assert sources.get("unknown") == 1
    # 按来源过滤：仅 NEXUS_AI
    summ = client.get("/api/traces/summary?group_by=model&source=NEXUS_AI").json()
    assert {g["model"] for g in summ["groups"]} == {"glm-4-flash"}
    assert abs(summ["total_cost"] - 0.3) < 1e-9
    # 列表按来源过滤
    rows = client.get("/api/traces?limit=20&source=NEXUS_AI").json()
    assert len(rows) == 1 and rows[0]["span_id"] == "src1"
