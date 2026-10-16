"""Index market windows and source joins without rewriting registered evidence."""
from alembic import op

revision = '0046_alpha_desk_indexes'
down_revision = '0045_alpha_call_registry'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_alpha_calls_market_registered', 'alpha_call_registrations', ['market', 'registered_at', 'id'])
    op.create_index('ix_alpha_calls_source', 'alpha_call_registrations', ['source_type', 'source_id'])


def downgrade():
    op.drop_index('ix_alpha_calls_source', table_name='alpha_call_registrations')
    op.drop_index('ix_alpha_calls_market_registered', table_name='alpha_call_registrations')
