"""Persist native Forex order remainders and exactly-once fill observations."""

from alembic import op
import sqlalchemy as sa

revision = "0048_forex_order_accounting"
down_revision = "0047_trading_curriculum"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forex_pending_orders",
        sa.Column(
            "account_id",
            sa.String(80),
            sa.ForeignKey("live_forward_paper_games.game_id", ondelete="RESTRICT"),
        ),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_uid", sa.String(220), nullable=False, unique=True),
        sa.Column(
            "decision_id",
            sa.Integer(),
            sa.ForeignKey("forex_decisions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("pair", sa.String(32), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("decision_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("requested_lots", sa.Float(), nullable=False),
        sa.Column("filled_lots", sa.Float(), nullable=False),
        sa.Column("remaining_lots", sa.Float(), nullable=False),
        sa.Column("stop_activated_at", sa.DateTime()),
        sa.Column("last_observation_at", sa.DateTime()),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    for field in ("pair", "status"):
        op.create_index(
            "ix_forex_pending_orders_" + field, "forex_pending_orders", [field]
        )
    op.create_table(
        "forex_order_fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fill_uid", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "order_uid",
            sa.String(220),
            sa.ForeignKey("forex_pending_orders.order_uid", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observation_uid", sa.String(64), nullable=False),
        sa.Column("market_timestamp", sa.DateTime(), nullable=False),
        sa.Column("quantity_lots", sa.Float(), nullable=False),
        sa.Column("executed_price", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "order_uid", "observation_uid", name="uq_forex_order_observation"
        ),
    )
    op.create_index(
        "ix_forex_order_fills_order_uid", "forex_order_fills", ["order_uid"]
    )


def downgrade():
    op.drop_table("forex_order_fills")
    op.drop_table("forex_pending_orders")
