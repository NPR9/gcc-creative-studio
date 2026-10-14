# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""create genai usage tracking and unit price tables

Revision ID: a8f3c2e91b04
Revises: f6a7b8c9d0e1
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a8f3c2e91b04"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "genai_usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_email", sa.String(), nullable=False),
        sa.Column(
            "group_names",
            postgresql.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=True),
        sa.Column(
            "prompt_token_count",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "candidates_token_count",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "thoughts_token_count",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_token_count",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "media_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_genai_usage_events_user_email",
        "genai_usage_events",
        ["user_email"],
        unique=False,
    )
    op.create_index(
        "ix_genai_usage_events_created_at",
        "genai_usage_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_genai_usage_events_user_email_created_at",
        "genai_usage_events",
        ["user_email", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_genai_usage_events_model_created_at",
        "genai_usage_events",
        ["model", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_genai_usage_events_group_names",
        "genai_usage_events",
        ["group_names"],
        unique=False,
        postgresql_using="gin",
    )

    op.create_table(
        "genai_model_unit_prices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("unit_type", sa.String(), nullable=False),
        sa.Column(
            "unit_price_usd",
            sa.Numeric(precision=18, scale=12),
            nullable=False,
        ),
        sa.Column(
            "currency", sa.String(), server_default="USD", nullable=False
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_genai_model_unit_prices_model",
        "genai_model_unit_prices",
        ["model"],
        unique=False,
    )
    op.create_index(
        "ix_genai_model_unit_prices_model_unit_type",
        "genai_model_unit_prices",
        ["model", "unit_type"],
        unique=False,
    )

    from src.usage.pricing_seed_data import SEED_UNIT_PRICES, SOURCE_NOTE

    prices_table = sa.table(
        "genai_model_unit_prices",
        sa.column("model", sa.String),
        sa.column("unit_type", sa.String),
        sa.column("unit_price_usd", sa.Numeric),
        sa.column("currency", sa.String),
        sa.column("notes", sa.Text),
    )
    op.bulk_insert(
        prices_table,
        [
            {
                "model": model,
                "unit_type": unit_type,
                "unit_price_usd": unit_price,
                "currency": "USD",
                "notes": f"{notes}. {SOURCE_NOTE}",
            }
            for model, unit_type, unit_price, notes in SEED_UNIT_PRICES
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_genai_model_unit_prices_model_unit_type",
        table_name="genai_model_unit_prices",
    )
    op.drop_index(
        "ix_genai_model_unit_prices_model",
        table_name="genai_model_unit_prices",
    )
    op.drop_table("genai_model_unit_prices")
    op.drop_index(
        "ix_genai_usage_events_group_names", table_name="genai_usage_events"
    )
    op.drop_index(
        "ix_genai_usage_events_model_created_at",
        table_name="genai_usage_events",
    )
    op.drop_index(
        "ix_genai_usage_events_user_email_created_at",
        table_name="genai_usage_events",
    )
    op.drop_index(
        "ix_genai_usage_events_created_at", table_name="genai_usage_events"
    )
    op.drop_index(
        "ix_genai_usage_events_user_email", table_name="genai_usage_events"
    )
    op.drop_table("genai_usage_events")
