from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, ForeignKeyConstraint, String, Text, create_engine, event, CheckConstraint, Index, JSON, UniqueConstraint, false, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm import Session

# 数据库位置固定在项目根目录下，不受终端当前目录影响。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_PATH = DATA_DIR / "salesaibot.db"

# engine 是应用与数据库之间的连接入口。
engine = create_engine(
    f"sqlite:///{DATABASE_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    """所有数据库模型的共同基类。"""

    pass


class OperatorAccount(Base):
    __tablename__ = "operator_accounts"
    __table_args__ = (
        UniqueConstraint("username", name="uq_operator_accounts_username"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class OperatorSession(Base):
    __tablename__ = "operator_sessions"

    token_digest: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operator_accounts.id"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[int] = mapped_column(nullable=False)


class Customer(Base):
    """一个明确创建的客户身份。"""

    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("id", "owner_operator_id", name="uq_customers_id_owner"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )

    display_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    owner_operator_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_accounts.id", name="fk_customers_owner_operator"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class Conversation(Base):
    """一个客户会话对应表中的一行。"""

    __tablename__ = "conversations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "owner_operator_id"],
            ["customers.id", "customers.owner_operator_id"],
            name="fk_conversations_customer_owner",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )

    customer_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    customer_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(
            "customers.id",
            name="fk_conversations_customer_id",
        ),
        nullable=True,
        index=True,
    )

    owner_operator_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_accounts.id", name="fk_conversations_owner_operator"),
        nullable=True,
        index=True,
    )

    version: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )

    suggestions_paused: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class Message(Base):
    """一个会话中的一条实际消息。"""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "(source_suggestion_id IS NULL AND adoption_mode IS NULL) OR "
            "(source_suggestion_id IS NOT NULL AND actor = 'human' "
            "AND adoption_mode IS NOT NULL "
            "AND adoption_mode IN ('verbatim', 'edited'))",
            name="ck_messages_suggestion_adoption",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )

    actor: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_suggestion_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey(
            "reply_suggestions.id",
            name="fk_messages_source_suggestion_id",
        ),
        nullable=True,
    )

    adoption_mode: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class MessageSubmission(Base):
    """记录一次消息提交对应的已保存消息。"""

    __tablename__ = "message_submissions"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"),
        primary_key=True,
    )

    request_key: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"),
        nullable=False,
    )


class ScreenshotImport(Base):
    """一次已确认的截图导入回执。"""

    __tablename__ = "screenshot_imports"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), primary_key=True
    )
    request_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    message_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)


class ConversationFact(Base):
    """一条由人工确认、可追溯到客户消息的会话事实。"""

    __tablename__ = "conversation_facts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'superseded', 'revoked')",
            name="ck_conversation_facts_status",
        ),
        Index(
            "ix_conversation_facts_lookup",
            "conversation_id",
            "fact_key",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
    )

    fact_key: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="confirmed",
        server_default="confirmed",
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )

    superseded_at: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    revoked_at: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )


class ReplySuggestion(Base):
    """保存一次生成的回复建议及其依据。"""

    __tablename__ = "reply_suggestions"
    __table_args__ = (
        CheckConstraint(
            "based_on_version >= 0",
            name="ck_reply_suggestions_version",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"),
        nullable=False,
        index=True,
    )

    based_on_version: Mapped[int] = mapped_column(
        nullable=False,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    reply_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    generation_snapshot: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class SuggestionCopyEvent(Base):
    """记录客户端报告的草稿复制事件。"""

    __tablename__ = "suggestion_copy_events"
    __table_args__ = (
        UniqueConstraint(
            "suggestion_id",
            "request_key",
            name="uq_suggestion_copy_request",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )

    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("reply_suggestions.id"),
        nullable=False,
        index=True,
    )

    request_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class SuggestionGenerationRequest(Base):
    """记录一次草稿生成请求的输入、状态和结果。"""

    __tablename__ = "suggestion_generation_requests"
    __table_args__ = (
        CheckConstraint(
            "based_on_version >= 0",
            name="ck_generation_request_version",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_generation_request_status",
        ),
        CheckConstraint(
            "("
            "(status = 'running' "
            "AND suggestion_id IS NULL "
            "AND error_code IS NULL "
            "AND finished_at IS NULL)"
            " OR "
            "(status = 'succeeded' "
            "AND suggestion_id IS NOT NULL "
            "AND error_code IS NULL "
            "AND finished_at IS NOT NULL)"
            " OR "
            "(status = 'failed' "
            "AND suggestion_id IS NULL "
            "AND error_code IS NOT NULL "
            "AND finished_at IS NOT NULL)"
            ")",
            name="ck_generation_request_result",
        ),
        UniqueConstraint(
            "suggestion_id",
            name="uq_generation_request_suggestion",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"),
        primary_key=True,
    )

    request_key: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    based_on_version: Mapped[int] = mapped_column(
        nullable=False,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
    )

    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("reply_suggestions.id"),
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    started_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )

    finished_at: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )


class SuggestionAbandonment(Base):
    __tablename__ = "suggestion_abandonments"

    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("reply_suggestions.id"), primary_key=True
    )
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operator_accounts.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )


class HumanHandoff(Base):
    __tablename__ = "human_handoffs"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('refund_request', 'complaint', 'payment_dispute', "
            "'model_unavailable', 'other')",
            name="ck_handoff_reason",
        ),
        CheckConstraint(
            "(resolved_at IS NULL AND resolved_by_operator_id IS NULL AND resolution IS NULL)"
            " OR (resolved_at IS NOT NULL AND resolved_by_operator_id IS NOT NULL "
            "AND resolution IS NOT NULL)",
            name="ck_handoff_resolution",
        ),
    )

    source_message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id"), primary_key=True, autoincrement=False
    )
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operator_accounts.id"), nullable=False
    )
    created_at: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=lambda: datetime.now(timezone.utc).isoformat(),
    )
    resolved_by_operator_id: Mapped[str | None] = mapped_column(
        ForeignKey("operator_accounts.id"), nullable=True
    )
    resolved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(500), nullable=True)


def get_db():
    """为一次请求提供数据库会话，请求结束后关闭。"""

    with Session(engine) as session:
        yield session


def init_db():
    """根据模型定义创建尚不存在的表。"""

    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print(f"数据库初始化完成：{DATABASE_PATH}")
