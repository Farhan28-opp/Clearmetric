"""Semantic metrics, conversations, analysis runs, saved visualisations, insights and reports."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class MetricDefinition(IdMixin, TimestampMixin, Base):
    __tablename__ = "metric_definitions"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(40), default="General")
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|archived
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    versions: Mapped[list["MetricVersion"]] = relationship(order_by="MetricVersion.version", cascade="all, delete-orphan")


class MetricVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "metric_versions"
    metric_id: Mapped[str] = mapped_column(ForeignKey("metric_definitions.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text)
    aggregation_type: Mapped[str] = mapped_column(String(20))  # additive|ratio|distinct|average|extreme
    unit: Mapped[str] = mapped_column(String(16))  # currency|count|percent|number
    decimals: Mapped[int] = mapped_column(Integer, default=2)
    default_date_column: Mapped[str] = mapped_column(String(64), default="")
    dimensions: Mapped[list] = mapped_column(JSON, default=list)  # applicable dimension columns ([] = all)
    columns_used: Mapped[list] = mapped_column(JSON, default=list)
    change_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Conversation(IdMixin, TimestampMixin, Base):
    """An analytical investigation (chat thread + canvas)."""
    __tablename__ = "conversations"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="New analysis")
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    messages: Mapped[list["Message"]] = relationship(order_by="Message.seq", cascade="all, delete-orphan")


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(12))  # user|assistant
    content: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text|answer|clarification|unsupported|error
    run_id: Mapped[str | None] = mapped_column(ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")


class AnalysisRun(IdMixin, TimestampMixin, Base):
    """Provenance record: validated plan + execution details + result for one calculation."""
    __tablename__ = "analysis_runs"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[str] = mapped_column(String(32))
    metric_version_ids: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20))  # analyst|explore|insight|report|api
    question: Mapped[str] = mapped_column(Text, default="")
    interpreter: Mapped[str] = mapped_column(String(40), default="")  # local-deterministic | anthropic:<model>
    plan: Mapped[dict] = mapped_column(JSON)
    plan_notes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16))  # succeeded|failed
    error: Mapped[str] = mapped_column(Text, default="")
    sql: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    rows_scanned: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class SavedVisualization(IdMixin, TimestampMixin, Base):
    __tablename__ = "saved_visualizations"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    chart_type: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Insight(IdMixin, TimestampMixin, Base):
    __tablename__ = "insights"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(8))  # high|medium|low
    score: Mapped[float] = mapped_column(default=0.0)
    title: Mapped[str] = mapped_column(String(300))
    finding: Mapped[str] = mapped_column(Text)
    metric_label: Mapped[str] = mapped_column(String(120), default="")
    baseline: Mapped[str] = mapped_column(String(200), default="")
    date_range: Mapped[str] = mapped_column(String(120), default="")
    method: Mapped[str] = mapped_column(Text)
    limitations: Mapped[str] = mapped_column(Text, default="")
    calculations: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    suggested_question: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="new")  # new|saved|dismissed
    note: Mapped[str] = mapped_column(Text, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class Report(IdMixin, TimestampMixin, Base):
    __tablename__ = "reports"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    period_start: Mapped[str] = mapped_column(String(10), default="")
    period_end: Mapped[str] = mapped_column(String(10), default="")
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft|final
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sections: Mapped[list["ReportSection"]] = relationship(order_by="ReportSection.position", cascade="all, delete-orphan")


class ReportSection(IdMixin, TimestampMixin, Base):
    __tablename__ = "report_sections"
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # text|kpis|chart|table|insight|summary|recommendations
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # frozen computed result + provenance
    source_ref: Mapped[str] = mapped_column(String(64), default="")
