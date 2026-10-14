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

"""DTOs for GenAI usage cost reporting."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class UserUsageCostRow(BaseModel):
    """Estimated spend for one user over a date range."""

    user_email: str
    event_count: int = 0
    total_prompt_tokens: int = 0
    total_candidates_tokens: int = 0
    total_thoughts_tokens: int = 0
    total_media_count: int = 0
    estimated_cost_usd: Decimal = Field(default=Decimal("0"))

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class UsageCostByUserResponse(BaseModel):
    """Aggregate estimated cost per user."""

    start_date: date | None = None
    end_date: date | None = None
    total_estimated_cost_usd: Decimal = Field(default=Decimal("0"))
    users: list[UserUsageCostRow] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class WorkspaceUsageCostResponse(BaseModel):
    """Estimated cost for users scoped to one workspace."""

    workspace_id: int
    workspace_name: str
    workspace_scope: str
    start_date: date | None = None
    end_date: date | None = None
    total_estimated_cost_usd: Decimal = Field(default=Decimal("0"))
    users: list[UserUsageCostRow] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )


class UnitPriceRow(BaseModel):
    """One unit-price configuration row."""

    id: int
    model: str
    unit_type: str
    unit_price_usd: Decimal
    currency: str
    notes: str | None = None

    model_config = ConfigDict(
        populate_by_name=True,
        alias_generator=to_camel,
    )
