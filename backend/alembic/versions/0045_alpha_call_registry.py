"""Register prospective alpha calls without modifying legacy evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0045_alpha_call_registry'
down_revision = '0044_ascent_evolution'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alpha_call_registrations',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('source_uid',sa.String(220),nullable=False,unique=True),
        sa.Column('source_type',sa.String(32),nullable=False),
        sa.Column('source_id',sa.Integer(),nullable=False),
        sa.Column('market',sa.String(16),nullable=False),
        sa.Column('asset',sa.String(32),nullable=False),
        sa.Column('decision_at',sa.DateTime(),nullable=False),
        sa.Column('registered_at',sa.DateTime(),nullable=False),
        sa.Column('source_revision',sa.String(40),nullable=False),
        sa.Column('source_content_hash',sa.String(64),nullable=False),
        sa.Column('manifest_json',sa.JSON().with_variant(JSONB,'postgresql'),nullable=False),
        sa.Column('manifest_sha256',sa.String(64),nullable=False))
    op.create_index('ix_alpha_call_registrations_market','alpha_call_registrations',['market'])
    op.create_index('ix_alpha_call_registrations_registered_at','alpha_call_registrations',['registered_at'])


def downgrade():
    op.drop_table('alpha_call_registrations')
