"""Persist bounded ASCENT generations, experiments and single-use evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0044_ascent_evolution"
down_revision = "0043_agent_council"
branch_labels = None
depends_on = None
JSON_TYPE = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade():
    op.create_table("ascent_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation_uid", sa.String(80), nullable=False, unique=True),
        sa.Column("parent_uid", sa.String(80)),
        sa.Column("market_family", sa.String(24), nullable=False),
        sa.Column("evidence_lane", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_revision", sa.String(80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("snapshot_json", JSON_TYPE, nullable=False),
        sa.Column("manifest_json", JSON_TYPE, nullable=False),
        sa.Column("summary_json", JSON_TYPE, nullable=False),
        sa.Column("selected_experiment_uid", sa.String(100)),
        sa.Column("holdout_opened", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()))
    op.create_index("ix_ascent_generations_status", "ascent_generations", ["status"])
    op.create_index("ix_ascent_generations_started_at", "ascent_generations", ["started_at"])
    op.create_table("ascent_experiments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("experiment_uid", sa.String(100), nullable=False, unique=True),
        sa.Column("generation_uid", sa.String(80), sa.ForeignKey("ascent_generations.generation_uid", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("development_json", JSON_TYPE, nullable=False),
        sa.Column("result_json", JSON_TYPE, nullable=False))
    op.create_index("ix_ascent_experiments_generation_uid", "ascent_experiments", ["generation_uid"])
    op.create_table("ascent_evidence_use",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_uid", sa.String(200), nullable=False, unique=True),
        sa.Column("decision_identity", sa.String(64), nullable=False, unique=True),
        sa.Column("generation_uid", sa.String(80), sa.ForeignKey("ascent_generations.generation_uid", ondelete="RESTRICT"), nullable=False),
        sa.Column("partition", sa.String(24), nullable=False))
    op.create_index("ix_ascent_evidence_use_generation_uid", "ascent_evidence_use", ["generation_uid"])


def downgrade():
    op.drop_table("ascent_evidence_use")
    op.drop_table("ascent_experiments")
    op.drop_table("ascent_generations")
