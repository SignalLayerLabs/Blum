"""Durable native outcome outbox and bounded source cursors."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0050_information_feedback"
down_revision = "0049_information_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "information_feedback_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("consumer_version", sa.String(80), nullable=False),
        sa.Column("source_uid", sa.String(220), nullable=False),
        sa.Column("decision_uid", sa.String(220), nullable=False),
        sa.Column("market_family", sa.String(24), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("conflict_hash", sa.String(64)),
        sa.Column(
            "payload_json",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("feature_published_at", sa.DateTime()),
        sa.Column("model_published_at", sa.DateTime()),
        sa.Column("quarantine_published_at", sa.DateTime()),
        sa.UniqueConstraint(
            "consumer_version", "source_uid", name="uq_information_feedback_source"
        ),
    )
    op.create_index(
        "ix_information_feedback_status_id",
        "information_feedback_outbox",
        ["status", "id"],
    )
    op.create_table(
        "information_feedback_cursors",
        sa.Column("source", sa.String(80), primary_key=True),
        sa.Column("source_updated_at", sa.DateTime(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("information_feedback_cursors")
    op.drop_index(
        "ix_information_feedback_status_id", table_name="information_feedback_outbox"
    )
    op.drop_table("information_feedback_outbox")
