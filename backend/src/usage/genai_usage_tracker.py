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

"""Best-effort GenAI usage recording helpers."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import isolated_db_session
from src.usage.request_context import (
    get_current_loop,
    get_current_user_email,
    get_current_user_id,
)
from src.usage.schema.genai_usage_event_model import GenAIUsageEvent
from src.usage.usage_model_utils import normalize_model_name

logger = logging.getLogger(__name__)


def extract_token_usage(response: Any) -> tuple[int, int, int, int]:
    """Extract prompt/candidates/thoughts/total token counts from a response.

    Gemini exposes thinking separately as ``thoughts_token_count``. Per Google
    pricing, thinking is billed at the output-token rate and is *not* included
    in ``candidates_token_count`` (it is part of ``total_token_count``).
    """
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0, 0, 0
    return (
        int(getattr(usage, "prompt_token_count", None) or 0),
        int(getattr(usage, "candidates_token_count", None) or 0),
        int(getattr(usage, "thoughts_token_count", None) or 0),
        int(getattr(usage, "total_token_count", None) or 0),
    )


async def _resolve_user_id(
    session: AsyncSession,
    user_id: int | None,
    user_email: str | None,
) -> int | None:
    if user_id is not None:
        return user_id
    if not user_email or user_email == "unknown":
        return None
    # Late import avoids circular imports via src.groups package init.
    from src.users.user_model import User

    result = await session.execute(
        select(User.id).where(User.email == user_email)
    )
    return result.scalar_one_or_none()


async def _resolve_group_names(
    session: AsyncSession, user_id: int | None
) -> list[str]:
    if user_id is None:
        return []
    try:
        from src.groups.schema.group_model import Group, GroupMember
    except ModuleNotFoundError:
        return []

    result = await session.execute(
        select(Group.name)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == user_id)
        .order_by(Group.name)
    )
    return [row[0] for row in result.all()]


async def record_genai_usage(
    *,
    model: str,
    feature: str | None = None,
    prompt_token_count: int = 0,
    candidates_token_count: int = 0,
    thoughts_token_count: int = 0,
    total_token_count: int = 0,
    media_count: int = 0,
    duration_seconds: float | None = None,
    user_email: str | None = None,
    user_id: int | None = None,
) -> None:
    """Insert one usage event. Never raises to callers."""
    try:
        email = user_email or get_current_user_email() or "unknown"
        async with isolated_db_session() as session:
            resolved_user_id = await _resolve_user_id(
                session,
                user_id if user_id is not None else get_current_user_id(),
                email,
            )
            group_names = await _resolve_group_names(
                session, resolved_user_id
            )

            event = GenAIUsageEvent(
                user_email=email,
                group_names=group_names,
                model=normalize_model_name(model),
                feature=feature,
                prompt_token_count=prompt_token_count,
                candidates_token_count=candidates_token_count,
                thoughts_token_count=thoughts_token_count,
                total_token_count=total_token_count,
                media_count=media_count,
                duration_seconds=duration_seconds,
            )
            session.add(event)
            await session.commit()
    except Exception:
        logger.exception("Failed to record GenAI usage event")


def schedule_record_genai_usage(**kwargs: Any) -> None:
    """Fire-and-forget wrapper safe from async code and to_thread workers."""
    ctx = contextvars.copy_context()

    async def _record() -> None:
        await record_genai_usage(**kwargs)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_record())
        return
    except RuntimeError:
        pass

    loop = get_current_loop()
    if loop is not None and loop.is_running():

        def _start_on_loop() -> None:
            ctx.run(asyncio.create_task, _record())

        loop.call_soon_threadsafe(_start_on_loop)
        return

    logger.warning(
        "No running event loop; skipping GenAI usage record for model=%s",
        kwargs.get("model"),
    )


def record_usage_from_response(
    response: Any,
    *,
    model: str,
    feature: str | None = None,
    media_count: int = 0,
    duration_seconds: float | None = None,
    user_email: str | None = None,
    user_id: int | None = None,
) -> None:
    """Schedule a usage row using token metadata from a GenAI response."""
    prompt_tokens, candidates_tokens, thoughts_tokens, total_tokens = (
        extract_token_usage(response)
    )
    schedule_record_genai_usage(
        model=model,
        feature=feature,
        prompt_token_count=prompt_tokens,
        candidates_token_count=candidates_tokens,
        thoughts_token_count=thoughts_tokens,
        total_token_count=total_tokens,
        media_count=media_count,
        duration_seconds=duration_seconds,
        user_email=user_email,
        user_id=user_id,
    )
