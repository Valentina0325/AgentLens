"""SQLAlchemy 引擎、会话、Base 与 Trace ORM 模型。"""
from sqlalchemy import Column, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite 单文件数据库，位于项目根目录（运行时生成 agent_lens.db）
DATABASE_URL = "sqlite:///./agent_lens.db"

# check_same_thread=False 允许 FastAPI 跨线程使用同一连接（开发环境足够）
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Trace(Base):
    """单次 LLM 调用记录表（对应第二节 TraceSpan）。"""

    __tablename__ = "traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String, index=True)          # 调用链 ID
    span_id = Column(String, unique=True, index=True)  # 单次调用唯一 ID
    parent_span_id = Column(String, nullable=True)  # 父 span
    model = Column(String, index=True)              # 模型名
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    latency_ms = Column(Integer)
    status = Column(String)
    timestamp = Column(String, index=True)          # 存 ISO 字符串，便于字符串范围比较
    # 列名仍为 metadata（符合数据模型规范）；Python 属性用 meta，
    # 避免与 SQLAlchemy 声明基类保留的 Base.metadata（MetaData）冲突。
    meta = Column("metadata", Text, nullable=True)   # JSON 字符串
    cost = Column(Float, nullable=True)             # 自动计算，模型未知时为 null
    currency = Column(String)                       # 定价表币种，未知为 UNKNOWN


def init_db() -> None:
    """创建所有表（幂等）。"""
    Base.metadata.create_all(bind=engine)
