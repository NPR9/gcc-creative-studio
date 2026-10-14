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

"""Estimate GenAI spend by joining usage events with unit prices."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from fastapi import HTTPException, status

from src.usage.dto.usage_cost_dto import (
    UnitPriceRow,
    UsageCostByUserResponse,
    UserUsageCostRow,
    WorkspaceUsageCostResponse,
)
from src.users.user_model import User
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceTypeEnum,
)
from src.usage.schema.genai_model_unit_price_model import (
    GenAIModelUnitPrice,
    GenAIUnitType,
)
from src.usage.schema.genai_usage_event_model import GenAIUsageEvent
from src.usage.usage_model_utils import resolve_price_row


class UsageCostService:
    """Query-time cost estimation (not invoice-grade billing)."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.db = db

    async def list_unit_prices(self) -> list[UnitPriceRow]:
        result = await self.db.execute(
            select(GenAIModelUnitPrice).order_by(
                GenAIModelUnitPrice.model, GenAIModelUnitPrice.unit_type
            )
        )
        rows = result.scalars().all()
        return [
            UnitPriceRow(
                id=row.id,
                model=row.model,
                unit_type=row.unit_type,
                unit_price_usd=Decimal(row.unit_price_usd),
                currency=row.currency,
                notes=row.notes,
            )
            for row in rows
        ]

    async def get_cost_by_user(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> UsageCostByUserResponse:
        price_map = await self._load_active_price_map()

        query = select(GenAIUsageEvent)
        if start_date:
            start_dt = datetime.combine(
                start_date, time.min, tzinfo=timezone.utc
            )
            query = query.where(GenAIUsageEvent.created_at >= start_dt)
        if end_date:
            end_dt = datetime.combine(
                end_date, time.max, tzinfo=timezone.utc
            )
            query = query.where(GenAIUsageEvent.created_at <= end_dt)

        result = await self.db.execute(query)
        events = result.scalars().all()

        aggregates: dict[str, dict] = defaultdict(
            lambda: {
                "event_count": 0,
                "total_prompt_tokens": 0,
                "total_candidates_tokens": 0,
                "total_thoughts_tokens": 0,
                "total_media_count": 0,
                "estimated_cost_usd": Decimal("0"),
            }
        )

        for event in events:
            cost = self._estimate_event_cost(event, price_map)
            bucket = aggregates[event.user_email]
            bucket["event_count"] += 1
            bucket["total_prompt_tokens"] += event.prompt_token_count or 0
            bucket["total_candidates_tokens"] += (
                event.candidates_token_count or 0
            )
            bucket["total_thoughts_tokens"] += (
                getattr(event, "thoughts_token_count", 0) or 0
            )
            bucket["total_media_count"] += event.media_count or 0
            bucket["estimated_cost_usd"] += cost

        users = [
            UserUsageCostRow(
                user_email=email,
                event_count=data["event_count"],
                total_prompt_tokens=data["total_prompt_tokens"],
                total_candidates_tokens=data["total_candidates_tokens"],
                total_thoughts_tokens=data["total_thoughts_tokens"],
                total_media_count=data["total_media_count"],
                estimated_cost_usd=data["estimated_cost_usd"].quantize(
                    Decimal("0.000001")
                ),
            )
            for email, data in sorted(
                aggregates.items(),
                key=lambda item: item[1]["estimated_cost_usd"],
                reverse=True,
            )
        ]
        total = sum(
            (row.estimated_cost_usd for row in users), Decimal("0")
        ).quantize(Decimal("0.000001"))

        return UsageCostByUserResponse(
            start_date=start_date,
            end_date=end_date,
            total_estimated_cost_usd=total,
            users=users,
        )


    async def get_cost_by_workspace(
        self,
        workspace_id: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> WorkspaceUsageCostResponse:
        """Estimate cost for users in a workspace.

        - PERSONAL workspace: only the workspace owner.
        - TEAM workspace: every workspace member.
        """
        result = await self.db.execute(
            select(Workspace).where(Workspace.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {workspace_id} not found",
            )

        member_emails = await self._resolve_workspace_emails(workspace)
        price_map = await self._load_active_price_map()

        query = select(GenAIUsageEvent).where(
            GenAIUsageEvent.user_email.in_(sorted(member_emails))
        )
        if start_date:
            start_dt = datetime.combine(
                start_date, time.min, tzinfo=timezone.utc
            )
            query = query.where(GenAIUsageEvent.created_at >= start_dt)
        if end_date:
            end_dt = datetime.combine(
                end_date, time.max, tzinfo=timezone.utc
            )
            query = query.where(GenAIUsageEvent.created_at <= end_dt)

        events = (await self.db.execute(query)).scalars().all()
        aggregates = self._empty_aggregates()
        for email in member_emails:
            aggregates[email]  # ensure zero rows for members with no usage

        for event in events:
            cost = self._estimate_event_cost(event, price_map)
            bucket = aggregates[event.user_email]
            bucket["event_count"] += 1
            bucket["total_prompt_tokens"] += event.prompt_token_count or 0
            bucket["total_candidates_tokens"] += (
                event.candidates_token_count or 0
            )
            bucket["total_thoughts_tokens"] += (
                getattr(event, "thoughts_token_count", 0) or 0
            )
            bucket["total_media_count"] += event.media_count or 0
            bucket["estimated_cost_usd"] += cost

        users = self._rows_from_aggregates(aggregates)
        total = sum(
            (row.estimated_cost_usd for row in users), Decimal("0")
        ).quantize(Decimal("0.000001"))

        return WorkspaceUsageCostResponse(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            workspace_scope=str(workspace.type),
            start_date=start_date,
            end_date=end_date,
            total_estimated_cost_usd=total,
            users=users,
        )

    async def _resolve_workspace_emails(self, workspace: Workspace) -> set[str]:
        """Personal workspace -> owner only; team -> all members."""
        if workspace.type == WorkspaceTypeEnum.PERSONAL.value:
            owner_result = await self.db.execute(
                select(User.email).where(User.id == workspace.owner_id)
            )
            owner_email = owner_result.scalar_one_or_none()
            return {owner_email} if owner_email else set()

        result = await self.db.execute(
            select(User.email)
            .join(
                WorkspaceMemberAssociation,
                WorkspaceMemberAssociation.user_id == User.id,
            )
            .where(WorkspaceMemberAssociation.workspace_id == workspace.id)
        )
        emails = {row[0] for row in result.all() if row[0]}
        # Always include owner even if membership row is missing.
        owner_result = await self.db.execute(
            select(User.email).where(User.id == workspace.owner_id)
        )
        owner_email = owner_result.scalar_one_or_none()
        if owner_email:
            emails.add(owner_email)
        return emails

    def _empty_aggregates(self) -> dict[str, dict]:
        return defaultdict(
            lambda: {
                "event_count": 0,
                "total_prompt_tokens": 0,
                "total_candidates_tokens": 0,
                "total_thoughts_tokens": 0,
                "total_media_count": 0,
                "estimated_cost_usd": Decimal("0"),
            }
        )

    def _rows_from_aggregates(
        self, aggregates: dict[str, dict]
    ) -> list[UserUsageCostRow]:
        return [
            UserUsageCostRow(
                user_email=email,
                event_count=data["event_count"],
                total_prompt_tokens=data["total_prompt_tokens"],
                total_candidates_tokens=data["total_candidates_tokens"],
                total_thoughts_tokens=data["total_thoughts_tokens"],
                total_media_count=data["total_media_count"],
                estimated_cost_usd=data["estimated_cost_usd"].quantize(
                    Decimal("0.000001")
                ),
            )
            for email, data in sorted(
                aggregates.items(),
                key=lambda item: item[1]["estimated_cost_usd"],
                reverse=True,
            )
        ]

    async def _load_active_price_map(
        self,
    ) -> dict[str, dict[str, Decimal]]:
        """model -> unit_type -> unit_price_usd for currently effective rows."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(GenAIModelUnitPrice).where(
                and_(
                    GenAIModelUnitPrice.effective_from <= now,
                    or_(
                        GenAIModelUnitPrice.effective_to.is_(None),
                        GenAIModelUnitPrice.effective_to >= now,
                    ),
                )
            )
        )
        price_map: dict[str, dict[str, Decimal]] = defaultdict(dict)
        for row in result.scalars().all():
            price_map[row.model][row.unit_type] = Decimal(row.unit_price_usd)
        return price_map

    def _estimate_event_cost(
        self,
        event: GenAIUsageEvent,
        price_map: dict[str, dict[str, Decimal]],
    ) -> Decimal:
        prices = resolve_price_row(str(event.model), price_map)
        if not prices:
            return Decimal("0")

        cost = Decimal("0")
        input_price = prices.get(GenAIUnitType.INPUT_TOKEN.value)
        output_price = prices.get(GenAIUnitType.OUTPUT_TOKEN.value)
        image_price = prices.get(GenAIUnitType.IMAGE.value)
        video_price = prices.get(GenAIUnitType.VIDEO_SECOND.value)
        audio_clip_price = prices.get(GenAIUnitType.AUDIO_CLIP.value)

        prompt_tokens = Decimal(event.prompt_token_count or 0)
        candidates_tokens = Decimal(event.candidates_token_count or 0)
        thoughts_tokens = Decimal(
            getattr(event, "thoughts_token_count", 0) or 0
        )
        media_count = Decimal(event.media_count or 0)
        duration = Decimal(str(event.duration_seconds or 0))

        # Token-priced text / TTS / multimodal text paths.
        # Google bills thinking/thoughts at the output-token rate.
        if input_price is not None:
            cost += prompt_tokens * input_price
        if output_price is not None:
            cost += (candidates_tokens + thoughts_tokens) * output_price

        # Image-priced models (Imagen / Gemini image output / VTO).
        # For Gemini image models we also keep input token cost above.
        if image_price is not None and media_count > 0:
            # Avoid double-counting when candidates tokens already priced
            # image output for models that only use output_token.
            if (
                GenAIUnitType.OUTPUT_TOKEN.value not in prices
                or candidates_tokens == 0
            ):
                cost += media_count * image_price

        if video_price is not None and duration > 0:
            video_units = media_count if media_count > 0 else Decimal("1")
            cost += video_units * duration * video_price

        if audio_clip_price is not None and media_count > 0:
            cost += media_count * audio_clip_price

        return cost
