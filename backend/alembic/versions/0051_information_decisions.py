"""Immutable information decisions precede the single native order ledger."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0051_information_decisions"
down_revision = "0050_information_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alpha_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("decision_uid", sa.String(220), nullable=False, unique=True),
        sa.Column("market_family", sa.String(24), nullable=False),
        sa.Column("asset_key", sa.String(32), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("decision_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("live_forward_paper_games.game_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("trial_uid", sa.String(220)),
        sa.Column(
            "manifest_json",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("native_order_type", sa.String(24)),
        sa.Column("native_order_id", sa.Integer()),
        sa.Column("native_order_uid", sa.String(220)),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_alpha_decisions_market_clock",
        "alpha_decisions",
        ["market_family", "decision_at", "id"],
    )
    op.add_column("forex_pending_orders", sa.Column("submitted_at", sa.DateTime()))


def downgrade():
    op.drop_column("forex_pending_orders", "submitted_at")
    op.drop_index("ix_alpha_decisions_market_clock", table_name="alpha_decisions")
    op.drop_table("alpha_decisions")
