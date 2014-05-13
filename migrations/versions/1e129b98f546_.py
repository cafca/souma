"""Add TextPlanet model

Revision ID: 1e129b98f546
Revises: 4e44fd06a62b
Create Date: 2014-05-13 23:25:36.442683

"""

# revision identifiers, used by Alembic.
revision = '1e129b98f546'
down_revision = '4e44fd06a62b'

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table('text_planet',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['id'], ['planet.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    ### end Alembic commands ###


def downgrade():
    op.drop_table('text_planet')
    ### end Alembic commands ###
