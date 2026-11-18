"""Datasets, immutable versions, column metadata, transformations and relationships."""
from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IdMixin, TimestampMixin


class Dataset(IdMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    original_filename: Mapped[str] = mapped_column(String(255))  # metadata only, never a path
    source_type: Mapped[str] = mapped_column(String(16))  # csv|xlsx|xls|demo|join
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # uploaded → needs_sheet → processing → ready | failed
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    status_message: Mapped[str] = mapped_column(Text, default="")
    original_key: Mapped[str] = mapped_column(String(80), default="")  # storage key of original upload
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    sheets: Mapped[list] = mapped_column(JSON, default=list)
    sheet_name: Mapped[str] = mapped_column(String(120), default="")
    import_report: Mapped[dict] = mapped_column(JSON, default=dict)
    current_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class DatasetVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "version_number"),)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parquet_key: Mapped[str] = mapped_column(String(80))
    row_count: Mapped[int] = mapped_column(Integer)
    column_count: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
    profile: Mapped[dict] = mapped_column(JSON, default=dict)  # quality + stats
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    columns: Mapped[list["DatasetColumn"]] = relationship(
        order_by="DatasetColumn.position", cascade="all, delete-orphan")


class DatasetColumn(IdMixin, Base):
    __tablename__ = "dataset_columns"
    version_id: Mapped[str] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))  # stable internal identifier (validated, quoted in SQL)
    original_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    dtype: Mapped[str] = mapped_column(String(16))  # integer|float|string|date|datetime|boolean
    semantic_type: Mapped[str] = mapped_column(String(20))  # measure|currency|dimension|date|identifier|text|boolean
    semantic_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    business_meaning: Mapped[str] = mapped_column(String(40), default="")
    meaning_confidence: Mapped[float] = mapped_column(default=0.0)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    null_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_count: Mapped[int] = mapped_column(Integer, default=0)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0)
    examples: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class DatasetTransformation(IdMixin, TimestampMixin, Base):
    __tablename__ = "dataset_transformations"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    from_version_id: Mapped[str] = mapped_column(String(32))
    to_version_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class DataRelationship(IdMixin, TimestampMixin, Base):
    __tablename__ = "data_relationships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    left_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    right_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    left_column: Mapped[str] = mapped_column(String(64))
    right_column: Mapped[str] = mapped_column(String(64))
    join_type: Mapped[str] = mapped_column(String(8))  # inner|left
    cardinality: Mapped[str] = mapped_column(String(16))  # one_to_one|many_to_one|one_to_many|many_to_many
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    materialized_dataset_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
