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

"""add missing genai unit prices for preview/lite models

Revision ID: e4f5a6b7c911
Revises: a8f3c2e91b04
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c911"
down_revision: Union[str, None] = "a8f3c2e91b04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from src.usage.pricing_seed_data import EXTRA_UNIT_PRICES, SOURCE_NOTE

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
            for model, unit_type, unit_price, notes in EXTRA_UNIT_PRICES
        ],
    )


def downgrade() -> None:
    from src.usage.pricing_seed_data import EXTRA_UNIT_PRICES

    models = sorted({row[0] for row in EXTRA_UNIT_PRICES})
    for model in models:
        op.execute(
            sa.text(
                "DELETE FROM genai_model_unit_prices WHERE model = :model"
            ).bindparams(model=model)
        )
