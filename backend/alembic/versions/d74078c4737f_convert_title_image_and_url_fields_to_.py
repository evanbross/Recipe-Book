"""convert title image and url fields to text

Revision ID: d74078c4737f
Revises: f47f22f9f6f6
Create Date: 2026-05-21 13:00:24.270745

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd74078c4737f'
down_revision: Union[str, None] = 'f47f22f9f6f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # recipes table
    op.alter_column('recipes', 'title',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.Text(),
               existing_nullable=False)
    op.alter_column('recipes', 'source_url',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'image_key',
               existing_type=sa.VARCHAR(length=512),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'image_url',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'thumbnail_key',
               existing_type=sa.VARCHAR(length=512),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'thumbnail_url',
               existing_type=sa.VARCHAR(length=2048),
               type_=sa.Text(),
               existing_nullable=True)

    # email_recipe_candidates table
    op.alter_column('email_recipe_candidates', 'title',
               existing_type=sa.VARCHAR(length=255),
               type_=sa.Text(),
               existing_nullable=False)


def downgrade() -> None:
    # email_recipe_candidates table
    op.alter_column('email_recipe_candidates', 'title',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=255),
               existing_nullable=False)

    # recipes table
    op.alter_column('recipes', 'thumbnail_url',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=True)
    op.alter_column('recipes', 'thumbnail_key',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=512),
               existing_nullable=True)
    op.alter_column('recipes', 'image_url',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=True)
    op.alter_column('recipes', 'image_key',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=512),
               existing_nullable=True)
    op.alter_column('recipes', 'source_url',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=2048),
               existing_nullable=True)
    op.alter_column('recipes', 'title',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=255),
               existing_nullable=False)
