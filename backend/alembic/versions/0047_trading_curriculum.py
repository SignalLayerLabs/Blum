"""Persistent isolated curriculum packs and historical/prospective episodes."""

from alembic import op
import sqlalchemy as sa

revision = "0047_trading_curriculum"
down_revision = "0046_alpha_desk_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "trading_curriculum_sources",
        sa.Column("uid", sa.String(64), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "trading_curriculum_states",
        sa.Column("lane", sa.String(120), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_trading_curriculum_states_updated_at",
        "trading_curriculum_states",
        ["updated_at"],
    )
    op.create_table(
        "trading_curriculum_episodes",
        sa.Column("uid", sa.String(64), primary_key=True),
        sa.Column("lane", sa.String(120), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for name in ("lane", "phase", "created_at"):
        op.create_index(
            f"ix_trading_curriculum_episodes_{name}",
            "trading_curriculum_episodes",
            [name],
        )


def downgrade():
    op.drop_table("trading_curriculum_episodes")
    op.drop_table("trading_curriculum_states")
    op.drop_table("trading_curriculum_sources")
