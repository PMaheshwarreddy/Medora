"""Medical knowledge tables and the bookkeeping for ingesting into them.

The five knowledge tables keep the agreed names and columns (`diseases`,
`symptoms`, `drugs`, `disease_links`, `precautions`); the extra columns exist
so that ingestion can match, de-duplicate and undo.

These tables are deliberately NOT created at startup: a database may already
hold knowledge tables with the same names but another layout, and the app must
never fail on or alter those by accident. They are created explicitly with
`python -m app.ingest init-db`.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeBase(DeclarativeBase):
    pass


class IngestionRun(KnowledgeBase):
    """One source file's journey: plan -> approval -> load (-> undo)."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    # One run per distinct file content; a byte-identical copy is not planned twice.
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # planned | approved | loaded | failed | skipped | undone
    status: Mapped[str] = mapped_column(String(16))
    # Why the run is skipped or failed, in words a person can act on.
    note: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[dict] = mapped_column(JSON)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class IngestionReject(KnowledgeBase):
    """A sample of the rows a run refused, with the reason."""

    __tablename__ = "ingestion_rejects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True
    )
    reason: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)


class _Entity:
    """Columns shared by diseases, symptoms and drugs."""

    # sort_order keeps these ahead of each table's own columns.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, sort_order=-3)
    name: Mapped[str] = mapped_column(String(255), sort_order=-2)
    # Lower-cased, punctuation-free form of the name. Matching and uniqueness
    # use this, so "Skin_rash", "skin rash" and "Skin Rash" are one row.
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, sort_order=-1)
    # The run that first created the row; lets a bad file be undone.
    created_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class Disease(_Entity, KnowledgeBase):
    __tablename__ = "diseases"

    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    causes: Mapped[str] = mapped_column(Text, default="")


class Symptom(_Entity, KnowledgeBase):
    __tablename__ = "symptoms"

    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")


class Drug(_Entity, KnowledgeBase):
    __tablename__ = "drugs"

    # Brand and alternative names. Not in the original column list; needed so
    # a brand name resolves to its generic drug.
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    dosage: Mapped[str] = mapped_column(Text, default="")
    uses: Mapped[str] = mapped_column(Text, default="")
    side_effects: Mapped[str] = mapped_column(Text, default="")


class DiseaseLink(KnowledgeBase):
    """One fact per row: a disease has a symptom, or is treated with a drug."""

    __tablename__ = "disease_links"
    __table_args__ = (
        CheckConstraint(
            "(symptom_id IS NULL) <> (drug_id IS NULL)",
            name="disease_links_exactly_one_target",
        ),
        Index(
            "uq_disease_links_symptom",
            "disease_id",
            "symptom_id",
            unique=True,
            postgresql_where=text("symptom_id IS NOT NULL"),
            sqlite_where=text("symptom_id IS NOT NULL"),
        ),
        Index(
            "uq_disease_links_drug",
            "disease_id",
            "drug_id",
            unique=True,
            postgresql_where=text("drug_id IS NOT NULL"),
            sqlite_where=text("drug_id IS NOT NULL"),
        ),
        Index("ix_disease_links_symptom_id", "symptom_id"),
        Index("ix_disease_links_drug_id", "drug_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease_id: Mapped[int] = mapped_column(ForeignKey("diseases.id", ondelete="CASCADE"))
    symptom_id: Mapped[int | None] = mapped_column(
        ForeignKey("symptoms.id", ondelete="CASCADE"), nullable=True
    )
    drug_id: Mapped[int | None] = mapped_column(
        ForeignKey("drugs.id", ondelete="CASCADE"), nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class Precaution(KnowledgeBase):
    """Advice attached to a disease, a symptom, or both."""

    __tablename__ = "precautions"
    __table_args__ = (
        CheckConstraint(
            "disease_id IS NOT NULL OR symptom_id IS NOT NULL",
            name="precautions_has_subject",
        ),
        Index("ix_precautions_disease_id", "disease_id"),
        Index("ix_precautions_symptom_id", "symptom_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    disease_id: Mapped[int | None] = mapped_column(
        ForeignKey("diseases.id", ondelete="CASCADE"), nullable=True
    )
    symptom_id: Mapped[int | None] = mapped_column(
        ForeignKey("symptoms.id", ondelete="CASCADE"), nullable=True
    )
    precaution: Mapped[str] = mapped_column(Text)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


ENTITY_MODELS = {"diseases": Disease, "symptoms": Symptom, "drugs": Drug}

# Free-text columns each table accepts from a source file.
ENTITY_FIELDS = {
    "diseases": ("description", "causes"),
    "symptoms": ("description",),
    "drugs": ("dosage", "uses", "side_effects"),
}
