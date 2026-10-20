"""Append-only source evidence, causal links and provider cursors."""

from alembic import op
import sqlalchemy as sa

revision = "0049_information_evidence"
down_revision = "0048_forex_order_accounting"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "information_evidence",
        sa.Column("evidence_id", sa.String(64), primary_key=True),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language", sa.String(24), nullable=False),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column(
            "revision_of",
            sa.String(64),
            sa.ForeignKey("information_evidence.evidence_id", ondelete="RESTRICT"),
        ),
        sa.Column("historical_availability_verified", sa.Boolean(), nullable=False),
        sa.Column("extraction_version", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_information_family_observed",
        "information_evidence",
        ["family_id", "observed_at"],
    )
    op.create_index(
        "ix_information_available",
        "information_evidence",
        ["available_at", "observed_at"],
    )
    op.create_table(
        "information_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "evidence_id",
            sa.String(64),
            sa.ForeignKey("information_evidence.evidence_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_key", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("mapping_version", sa.String(80), nullable=False),
        sa.UniqueConstraint(
            "evidence_id",
            "entity_key",
            "kind",
            "mapping_version",
            name="uq_information_link",
        ),
    )
    op.create_index(
        "ix_information_link_entity", "information_links", ["entity_key", "evidence_id"]
    )
    op.create_table(
        "information_provider_states",
        sa.Column("provider", sa.String(80), primary_key=True),
        sa.Column("cursor", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_at", sa.DateTime()),
        sa.Column("retry_at", sa.DateTime()),
        sa.Column("last_success_at", sa.DateTime()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("coverage", sa.JSON(), nullable=False),
    )


def downgrade():
    op.drop_table("information_provider_states")
    op.drop_table("information_links")
    op.drop_table("information_evidence")
