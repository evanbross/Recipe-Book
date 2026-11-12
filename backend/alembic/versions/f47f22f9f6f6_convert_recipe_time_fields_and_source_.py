"""convert recipe time fields and source_type to text

Revision ID: f47f22f9f6f6
Revises: 003
Create Date: 2026-05-21 12:54:30.970376

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f47f22f9f6f6'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # recipes table
    op.alter_column('recipes', 'servings',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'prep_time',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'cook_time',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('recipes', 'source_type',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=False)

    # email_recipe_candidates table
    op.alter_column('email_recipe_candidates', 'servings',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('email_recipe_candidates', 'prep_time',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)
    op.alter_column('email_recipe_candidates', 'cook_time',
               existing_type=sa.VARCHAR(length=50),
               type_=sa.Text(),
               existing_nullable=True)


def downgrade() -> None:
    # email_recipe_candidates table
    op.alter_column('email_recipe_candidates', 'cook_time',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('email_recipe_candidates', 'prep_time',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('email_recipe_candidates', 'servings',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)

    # recipes table
    op.alter_column('recipes', 'source_type',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=False)
    op.alter_column('recipes', 'cook_time',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('recipes', 'prep_time',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
    op.alter_column('recipes', 'servings',
               existing_type=sa.Text(),
               type_=sa.VARCHAR(length=50),
               existing_nullable=True)
