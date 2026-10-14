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

"""SQLAlchemy model for per-call GenAI usage events."""

import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class GenAIUsageEvent(Base):
    """One row per GenAI API call for later cost estimation."""

    __tablename__ = "genai_usage_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    group_names: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        server_default="{}",
    )
    model: Mapped[str] = mapped_column(String, nullable=False)
    feature: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_token_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    candidates_token_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    thoughts_token_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    total_token_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    media_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        insert_default=func.now(),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
