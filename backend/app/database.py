import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, DateTime, ForeignKey, JSON, Integer, UniqueConstraint
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

url = os.getenv("DATABASE_URL")
if not url:
    url = URL.create("mysql+pymysql", username=os.getenv("DB_USER", "mcms"), password=os.getenv("DB_PASSWORD", ""),
                     host=os.getenv("DB_HOST", "localhost"), database=os.getenv("DB_NAME", "mcms"))
engine = create_engine(url, pool_pre_ping=True, **({"connect_args": {"check_same_thread": False}} if str(url).startswith("sqlite") else {}))
SessionLocal = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Record(Base):
    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("records.id"), nullable=True, index=True)
    site_id: Mapped[str | None] = mapped_column(ForeignKey("records.id"), nullable=True, index=True)
    # Unique natural key is enforced by MySQL as well as service validation.
    natural_key: Mapped[str | None] = mapped_column(String(500), unique=True, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", index=True)
    stage: Mapped[int] = mapped_column(Integer, default=0)
    workflow: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    modified_by: Mapped[str] = mapped_column(String(150))
    modified_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[str] = mapped_column(String(150), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(60))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("records.id"), nullable=True)
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("records.id"), nullable=True)
    active: Mapped[int] = mapped_column(Integer, default=1)

class AuthSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)

class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str | None] = mapped_column(ForeignKey("records.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(150))
    action: Mapped[str] = mapped_column(String(60))
    reason: Mapped[str] = mapped_column(Text, default="")
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=now)

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    document_type: Mapped[str] = mapped_column(String(100))
    uploaded_by: Mapped[str] = mapped_column(String(150))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Config(Base):
    __tablename__ = "configuration"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)

class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    rows: Mapped[list] = mapped_column(JSON)
    posted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
