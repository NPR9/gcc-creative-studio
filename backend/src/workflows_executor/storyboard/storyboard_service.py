# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Storyboard orchestration: plan, character sheets, frames, revisions.

Uses the executor's HTTP client, GenAI client and helpers so generated
images go through the same image API, gallery and brand guidelines as the
rest of the Studio.

Two timing models:
- generate (called by Cloud Workflows, up to 30 min): waits for every image.
- revise (called from the browser through Firebase Hosting, which cuts
  requests at 60s): starts the image jobs and returns at once; the page
  polls the gallery for the pending frames.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import HTTPException
from google.genai import types
from pydantic import BaseModel

from src.common.schema.media_item_model import AssetRoleEnum
from src.workflows.schema.workflow_model import (
    GenerateStoryboardSettings,
    RenderStoryboardDto,
    ReviseStoryboardDto,
)
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateStoryboardRequest,
)
from src.workflows_executor.storyboard.storyboard_prompts import (
    StoryboardCharacter,
    StoryboardPlan,
    StoryboardRevision,
    StoryboardScene,
    StoryboardShot,
    apply_revision,
    build_character_sheet_prompt,
    build_edit_prompt,
    build_frame_prompt,
    build_revision_prompts,
    build_system_prompt,
    build_user_prompt,
    render_storyboard_text,
)

if TYPE_CHECKING:
    from src.workflows_executor.workflows_executor_service import (
        WorkflowsExecutorService,
    )

logger = logging.getLogger(__name__)

# Parallel image requests per run. A 24-frame board finishes in ~4 rounds.
STORYBOARD_FRAME_CONCURRENCY = 6
# Character sheets are made for at most this many people per board.
MAX_CHARACTER_SHEETS = 3
# The image API accepts at most 14 source images per request.
MAX_SOURCE_IMAGES = 14

_REVISION_FIELDS = {"revision", "source_shot_number", "edit_instruction"}
_PLAN_EXCLUDE = {
    "scenes": {"__all__": {"shots": {"__all__": _REVISION_FIELDS}}}
}

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class _RenderContext:
    """Everything a single image request needs, shared across a run."""

    settings: GenerateStoryboardSettings
    workspace_id: int
    authorization: str | None
    wait: bool = True
    reference_media_items: list[dict] = field(default_factory=list)
    reference_asset_ids: list[int] = field(default_factory=list)
    semaphore: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(STORYBOARD_FRAME_CONCURRENCY)
    )


@dataclass
class _Rendered:
    """Result of rendering one board: ids, errors and still-pending jobs."""

    frame_ids: dict[int, int | None] = field(default_factory=dict)
    sheet_ids: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)


class StoryboardService:
    """Builds and revises storyboards on top of the workflows executor."""

    def __init__(self, executor: "WorkflowsExecutorService"):
        self.executor = executor

    # ---------------------------------------------------------------
    # Public entry points
    # ---------------------------------------------------------------

    async def generate(
        self,
        request: GenerateStoryboardRequest,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        """Brief -> plan -> character sheets -> one image per shot."""
        settings = request.config
        brief = request.inputs.brief
        if not isinstance(brief, str) or not brief.strip():
            raise HTTPException(
                status_code=400,
                detail="Storyboard brief is empty. Describe the video.",
            )

        media_items, asset_ids = [], []
        reference_parts = []
        if request.inputs.reference_images:
            media_items, asset_ids = self.executor.normalize_asset_inputs(
                request.inputs.reference_images,
                default_role=AssetRoleEnum.IMAGE_REFERENCE_ASSET,
            )
            reference_parts = await self.executor.resolve_media_to_parts(
                request.inputs.reference_images,
                authorization,
            )

        plan = await self._call_model(
            schema=StoryboardPlan,
            model=settings.reasoning_model,
            system=build_system_prompt(
                language=settings.language,
                max_frames=settings.max_frames,
                board_type=settings.board_type,
                options_per_beat=settings.options_per_beat,
                brand_context=settings.brand_context,
            ),
            contents=[
                types.Part.from_text(
                    text=build_user_prompt(
                        brief,
                        settings.aspect_ratio,
                        has_references=bool(reference_parts),
                    ),
                ),
                *reference_parts,
            ],
        )
        _require_shots(plan)
        plan.cap_and_renumber(settings.max_frames)

        ctx = _RenderContext(
            settings=settings,
            workspace_id=request.workspace_id,
            authorization=authorization,
            reference_media_items=media_items,
            reference_asset_ids=asset_ids,
        )
        if settings.plan_first:
            # Stop at the plan; the requester approves it in the panel and
            # the frames are drawn through render().
            return self._outputs(plan, ctx, _Rendered(), awaiting_approval=True)
        rendered = _Rendered()
        await self._render_character_sheets(plan, ctx, rendered, previous={})
        await self._render_frames(
            plan,
            ctx,
            rendered,
            reference_sheets=dict(rendered.sheet_ids),
            previous_frames={},
        )
        return self._outputs(plan, ctx, rendered)

    async def revise(
        self,
        dto: ReviseStoryboardDto,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        """Applies change notes; only changed frames get new image jobs.

        Returns immediately after starting the jobs. `pending` lists the
        frames and sheets still rendering, with the image they replace.
        """
        settings = dto.settings
        previous = dto.shot_list
        try:
            current_plan = StoryboardPlan.model_validate(previous)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="shot_list is not a storyboard from this workflow.",
            ) from e

        previous_frames = {
            shot.get("shot_number"): shot.get("frame_media_id")
            for scene in previous.get("scenes", [])
            for shot in scene.get("shots", [])
        }
        previous_sheets = {
            c.get("key"): {
                "id": c.get("character_sheet_id"),
                "signature": _character_signature_dict(c),
            }
            for c in previous.get("characters", [])
        }

        system, user = build_revision_prompts(
            current_plan=current_plan.model_dump(exclude=_PLAN_EXCLUDE),
            change_notes=dto.change_notes,
            language=settings.language,
            brand_context=settings.brand_context,
        )
        revision = await self._call_model(
            schema=StoryboardRevision,
            model=settings.reasoning_model,
            system=system,
            contents=[types.Part.from_text(text=user)],
        )
        plan = apply_revision(current_plan, revision)
        _require_shots(plan)
        plan.cap_and_renumber(settings.max_frames)

        ctx = _RenderContext(
            settings=settings,
            workspace_id=dto.workspace_id,
            authorization=authorization,
            wait=False,
            reference_media_items=list(
                previous.get("reference_media_items") or []
            ),
            reference_asset_ids=list(previous.get("reference_asset_ids") or []),
        )
        if dto.plan_only:
            # Plan still awaiting approval: update the text, draw nothing.
            return self._outputs(plan, ctx, _Rendered(), awaiting_approval=True)
        rendered = _Rendered()
        await self._render_character_sheets(
            plan, ctx, rendered, previous=previous_sheets
        )
        # Only sheets that already exist can be used as references; new
        # sheets are still rendering and are used from the next revision.
        ready_sheets = {
            key: sheet_id
            for key, sheet_id in rendered.sheet_ids.items()
            if previous_sheets.get(key, {}).get("id") == sheet_id
        }
        await self._render_frames(
            plan,
            ctx,
            rendered,
            reference_sheets=ready_sheets,
            previous_frames=previous_frames,
        )
        return self._outputs(plan, ctx, rendered)

    async def render(
        self,
        dto: RenderStoryboardDto,
        authorization: str | None = None,
    ) -> dict[str, Any]:
        """Draws an approved plan in two short phases.

        "sheets" starts the character sheets; "frames" (called once those
        are ready) starts every frame that has no image yet. Both return at
        once with `pending`, so each browser call stays far below 60s.
        """
        previous = dto.shot_list
        try:
            plan = StoryboardPlan.model_validate(previous)
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="shot_list is not a storyboard from this workflow.",
            ) from e

        ctx = _RenderContext(
            settings=dto.settings,
            workspace_id=dto.workspace_id,
            authorization=authorization,
            wait=False,
            reference_media_items=list(
                previous.get("reference_media_items") or []
            ),
            reference_asset_ids=list(previous.get("reference_asset_ids") or []),
        )
        previous_frames = {
            shot.get("shot_number"): shot.get("frame_media_id")
            for scene in previous.get("scenes", [])
            for shot in scene.get("shots", [])
        }
        rendered = _Rendered()

        if dto.phase == "sheets":
            previous_sheets = {
                c.get("key"): {
                    "id": c.get("character_sheet_id"),
                    "signature": _character_signature_dict(c),
                }
                for c in previous.get("characters", [])
            }
            await self._render_character_sheets(
                plan, ctx, rendered, previous=previous_sheets
            )
            rendered.frame_ids = {
                number: media_id
                for number, media_id in previous_frames.items()
                if media_id
            }
            return self._outputs(plan, ctx, rendered, awaiting_approval=True)

        rendered.sheet_ids = {
            c.get("key"): c.get("character_sheet_id")
            for c in previous.get("characters", [])
            if c.get("character_sheet_id")
        }
        for _, shot in plan.all_shots():
            if previous_frames.get(shot.shot_number):
                shot.revision = "keep"
                shot.source_shot_number = shot.shot_number
        await self._render_frames(
            plan,
            ctx,
            rendered,
            reference_sheets=dict(rendered.sheet_ids),
            previous_frames=previous_frames,
        )
        return self._outputs(plan, ctx, rendered)

    # ---------------------------------------------------------------
    # Model calls
    # ---------------------------------------------------------------

    async def _call_model(
        self,
        *,
        schema: type[SchemaT],
        model: str,
        system: str,
        contents: list,
    ) -> SchemaT:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.6,
            response_mime_type="application/json",
            response_schema=schema,
        )
        client = self.executor.genai_client
        response = await client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        result = getattr(response, "parsed", None)
        if isinstance(result, schema):
            return result
        try:
            return schema.model_validate_json(response.text or "")
        except Exception as e:
            logger.error("Storyboard model output parse failed: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Planner returned an invalid storyboard plan.",
            ) from e

    # ---------------------------------------------------------------
    # Rendering
    # ---------------------------------------------------------------

    async def _request_image(
        self,
        ctx: _RenderContext,
        prompt: str,
        source_media_items: list[dict],
        source_asset_ids: list[int],
        label: str,
    ) -> int:
        """Starts one image job; waits for it when ctx.wait is set."""
        body: dict[str, Any] = {
            "prompt": prompt,
            "workspace_id": ctx.workspace_id,
            "generation_model": ctx.settings.image_model,
            "aspect_ratio": ctx.settings.aspect_ratio,
            "use_brand_guidelines": ctx.settings.brand_guidelines,
            "number_of_media": 1,
            "resolution": "1K",
        }
        media = source_media_items[:MAX_SOURCE_IMAGES]
        assets = source_asset_ids[: max(0, MAX_SOURCE_IMAGES - len(media))]
        if media:
            body["source_media_items"] = media
        if assets:
            body["source_asset_ids"] = assets

        headers = (
            {"Authorization": ctx.authorization} if ctx.authorization else {}
        )
        async with ctx.semaphore:
            response = await self.executor.rest_client.post(
                self.executor.backend_url + "/api/images/generate-images",
                json=body,
                headers=headers,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"{label}: {response.text}",
                )
            image_id = response.json().get("id")
            if not image_id:
                raise HTTPException(
                    status_code=500, detail=f"{label}: no image id returned"
                )
            if ctx.wait:
                await self.executor.poll_job_status(image_id, ctx.authorization)
            return image_id

    async def _render_character_sheets(
        self,
        plan: StoryboardPlan,
        ctx: _RenderContext,
        rendered: _Rendered,
        previous: dict[str, dict],
    ) -> None:
        """One reference sheet per recurring character.

        A sheet is reused when the character's look and wardrobe are
        unchanged since the previous version of the board.
        """
        if not ctx.settings.character_sheets:
            return
        characters = plan.characters[:MAX_CHARACTER_SHEETS]

        async def one(character: StoryboardCharacter) -> int:
            before = previous.get(character.key)
            if (
                before
                and before.get("id")
                and before.get("signature") == _character_signature(character)
            ):
                return before["id"]
            sheet_id = await self._request_image(
                ctx,
                build_character_sheet_prompt(
                    character, ctx.settings.frame_style
                ),
                list(ctx.reference_media_items),
                list(ctx.reference_asset_ids),
                f"Character sheet {character.name}",
            )
            if not ctx.wait:
                rendered.pending.append(
                    {
                        "kind": "character_sheet",
                        "key": character.key,
                        "media_id": sheet_id,
                        "previous_media_id": (before or {}).get("id"),
                    }
                )
            return sheet_id

        results = await asyncio.gather(
            *[one(c) for c in characters], return_exceptions=True
        )
        for character, result in zip(characters, results):
            if isinstance(result, BaseException):
                rendered.errors.append(
                    f"Character sheet {character.name}: {_detail(result)}"
                )
            else:
                rendered.sheet_ids[character.key] = result

    async def _render_frames(
        self,
        plan: StoryboardPlan,
        ctx: _RenderContext,
        rendered: _Rendered,
        reference_sheets: dict[str, int],
        previous_frames: dict[int, int | None],
    ) -> None:
        """Renders every shot; keeps or edits earlier frames on revisions."""

        async def one(scene: StoryboardScene, shot: StoryboardShot) -> int:
            source = (
                previous_frames.get(shot.source_shot_number)
                if shot.source_shot_number is not None
                else None
            )
            if shot.revision == "keep" and source:
                return source
            if shot.revision == "edit" and source:
                try:
                    return await self._request_image(
                        ctx,
                        build_edit_prompt(shot),
                        [_media_link(source, AssetRoleEnum.INPUT)],
                        [],
                        f"Frame {shot.shot_number} edit",
                    )
                except HTTPException as e:
                    # Keep the earlier frame rather than leave a hole.
                    raise _KeptPrevious(source, _detail(e)) from e
            character_refs = [
                _media_link(
                    reference_sheets[key], AssetRoleEnum.IMAGE_REFERENCE_ASSET
                )
                for key in shot.characters
                if key in reference_sheets
            ]
            return await self._request_image(
                ctx,
                build_frame_prompt(
                    shot,
                    scene,
                    plan,
                    ctx.settings.frame_style,
                    has_character_refs=bool(character_refs),
                ),
                character_refs + list(ctx.reference_media_items),
                list(ctx.reference_asset_ids),
                f"Frame {shot.shot_number}",
            )

        pairs = list(plan.all_shots())
        results = await asyncio.gather(
            *[one(scene, shot) for scene, shot in pairs],
            return_exceptions=True,
        )
        for (_, shot), result in zip(pairs, results):
            number = shot.shot_number
            source = previous_frames.get(shot.source_shot_number)
            if isinstance(result, _KeptPrevious):
                rendered.frame_ids[number] = result.media_id
                rendered.errors.append(
                    f"Frame {number}: edit failed, kept the previous image "
                    f"({result.reason})"
                )
            elif isinstance(result, BaseException):
                logger.error(
                    "Storyboard frame %s failed: %s", number, _detail(result)
                )
                rendered.frame_ids[number] = None
                rendered.errors.append(f"Frame {number}: {_detail(result)}")
            else:
                rendered.frame_ids[number] = result
                if not ctx.wait and result != source:
                    rendered.pending.append(
                        {
                            "kind": "frame",
                            "shot_number": number,
                            "media_id": result,
                            "previous_media_id": source,
                        }
                    )

        if not any(rendered.frame_ids.values()):
            raise HTTPException(
                status_code=502,
                detail="All storyboard frames failed: "
                + "; ".join(rendered.errors),
            )

    # ---------------------------------------------------------------
    # Outputs
    # ---------------------------------------------------------------

    def _outputs(
        self,
        plan: StoryboardPlan,
        ctx: _RenderContext,
        rendered: _Rendered,
        awaiting_approval: bool = False,
    ) -> dict[str, Any]:
        shot_list = plan.model_dump(exclude=_PLAN_EXCLUDE)
        for scene in shot_list["scenes"]:
            for shot in scene["shots"]:
                shot["frame_media_id"] = rendered.frame_ids.get(
                    shot["shot_number"]
                )
        for character in shot_list["characters"]:
            character["character_sheet_id"] = rendered.sheet_ids.get(
                character["key"]
            )
        shot_list["frame_errors"] = rendered.errors
        # Carried so a later revision can reuse the same references and
        # settings without the requester re-entering them.
        shot_list["reference_media_items"] = ctx.reference_media_items
        shot_list["reference_asset_ids"] = ctx.reference_asset_ids
        shot_list["settings"] = ctx.settings.model_dump()
        shot_list["awaiting_approval"] = awaiting_approval

        frames = [
            rendered.frame_ids[shot.shot_number]
            for _, shot in plan.all_shots()
            if rendered.frame_ids.get(shot.shot_number)
        ]
        sheets = [
            rendered.sheet_ids[c.key]
            for c in plan.characters
            if c.key in rendered.sheet_ids
        ]
        outputs = {
            "storyboard_frames": frames,
            "character_sheets": sheets,
            "storyboard_text": render_storyboard_text(
                plan, rendered.frame_ids, drawn=not awaiting_approval
            ),
            "shot_list": shot_list,
        }
        if not ctx.wait:
            outputs["pending"] = rendered.pending
        return outputs


# =========================================
# Helpers
# =========================================


class _KeptPrevious(Exception):
    """An edit failed; the previous frame is kept in its place."""

    def __init__(self, media_id: int, reason: str):
        super().__init__(reason)
        self.media_id = media_id
        self.reason = reason


def _require_shots(plan: StoryboardPlan) -> None:
    if plan.shot_count() == 0:
        raise HTTPException(
            status_code=502,
            detail="Planner returned a storyboard with no shots.",
        )


def _media_link(media_id: int, role: AssetRoleEnum) -> dict:
    return {"media_item_id": media_id, "media_index": 0, "role": role.value}


def _character_signature(character: StoryboardCharacter) -> str:
    return f"{character.look}|{character.wardrobe}"


def _character_signature_dict(character: dict) -> str:
    look = character.get("look", "")
    wardrobe = character.get("wardrobe", "")
    return f"{look}|{wardrobe}"


def _detail(error: BaseException) -> str:
    return str(getattr(error, "detail", None) or error)
