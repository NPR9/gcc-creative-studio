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

"""SQLAlchemy model for GenAI model unit prices."""

import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class GenAIUnitType(str, Enum):
    """Billable unit kinds used for cost estimation."""

    INPUT_TOKEN = "input_token"
    OUTPUT_TOKEN = "output_token"
    IMAGE = "image"
    VIDEO_SECOND = "video_second"
    AUDIO_CLIP = "audio_clip"


class GenAIModelUnitPrice(Base):
    """Unit price for a model, effective over a date range."""

    __tablename__ = "genai_model_unit_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    unit_type: Mapped[str] = mapped_column(String, nullable=False)
    # Price for a single unit (one token, one image, one video-second, …).
    unit_price_usd: Mapped[Decimal] = mapped_column(
        Numeric(precision=18, scale=12), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String, nullable=False, server_default="USD"
    )
    effective_from: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    effective_to: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
        nullable=False,
    )
