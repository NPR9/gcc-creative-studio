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
"""Tests for the Storyboard step, revisions and workflow presets."""

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response

from src.auth.auth_guard import get_current_user
from src.common.base_dto import GenerationModelEnum
from src.images.dto.create_imagen_dto import CreateImagenDto
from src.users.user_model import UserModel, UserRoleEnum
from src.workflows.presets.workflow_presets import load_presets
from src.workflows.schema.workflow_model import (
    GenerateStoryboardInputs,
    GenerateStoryboardSettings,
    RenderStoryboardDto,
    ReviseStoryboardDto,
    WorkflowModel,
)
from src.workflows.workflow_controller import router
from src.workflows.workflow_service import WorkflowService
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateStoryboardRequest,
)
from src.workflows_executor.storyboard.storyboard_prompts import (
    StoryboardPlan,
    StoryboardRevision,
    apply_revision,
    build_character_sheet_prompt,
    build_edit_prompt,
    build_frame_prompt,
    build_system_prompt,
    render_storyboard_text,
)
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

GENAI_INIT_PATH = (
    "src.workflows_executor.workflows_executor_service.GenAIModelSetup.init"
)
REST_PATH = "src.workflows_executor.workflows_executor_service.RestClient"


def _shot(number, characters=("astrid",), screenshot=False, **extra):
    return {
        "shot_number": number,
        "shot_type": "Medium",
        "camera_movement": "Static",
        "action": f"Action {number}",
        "on_screen_text": None,
        "characters": list(characters),
        "needs_real_screenshot": screenshot,
        "visual_prompt": f"Visual {number}",
        **extra,
    }


def _plan_dict(shots_per_scene=(2, 2)) -> dict:
    number = 0
    scenes = []
    for index, count in enumerate(shots_per_scene, start=1):
        shots = []
        for _ in range(count):
            number += 1
            shots.append(_shot(number, screenshot=number == 2))
        scenes.append(
            {
                "scene_number": index,
                "title": f"Scene {index}",
                "scene_type": "Establishing",
                "timing": f"{(index - 1) * 15}-{index * 15}s",
                "context": "Context",
                "voiceover": [f"Meet Astrid, line {index}."],
                "visual_style": "Warm daylight",
                "shots": shots,
            }
        )
    return {
        "title": "ISA",
        "objective": "Launch ISA",
        "target_audience": "Sales teams",
        "channel_and_format": "Internal 16:9, 90s",
        "total_duration_seconds": 90,
        "key_message": "More time for customers",
        "visual_bible": "Paris office, blue and yellow accents",
        "characters": [
            {
                "key": "astrid",
                "name": "Astrid",
                "role": "Sales rep",
                "look": "40s, blonde bun, glasses",
                "wardrobe": "Navy vest, white shirt",
            }
        ],
        "assumptions": ["No price given"],
        "open_questions": ["Final logo lockup?"],
        "scenes": scenes,
    }


def _plan(shots_per_scene=(2, 2)) -> StoryboardPlan:
    return StoryboardPlan.model_validate(_plan_dict(shots_per_scene))


def _request(**settings) -> GenerateStoryboardRequest:
    return GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="SCENE 01 - Meet Astrid ..."),
        config=GenerateStoryboardSettings(**{"plan_first": False, **settings}),
    )


class FakeImageApi:
    """Records image requests and hands out increasing ids."""

    def __init__(self, fail_when=None, start=100):
        self.bodies = []
        self.next_id = start
        self.fail_when = fail_when or (lambda body: False)

    async def post(self, url, json=None, headers=None):
        assert url.endswith("/api/images/generate-images")
        assert headers is not None
        self.bodies.append(json)
        if self.fail_when(json):
            return Response(500, text="quota")
        self.next_id += 1
        return Response(200, json={"id": self.next_id})


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(REST_PATH) as mock_rest_client_class,
        patch(GENAI_INIT_PATH) as mock_genai_init,
    ):
        mock_rest_client_class.return_value = AsyncMock()
        mock_genai_client = MagicMock()
        mock_genai_init.return_value = mock_genai_client

        service = WorkflowsExecutorService()
        service.mock_genai_client = mock_genai_client
        service._poll_job_status = AsyncMock(return_value=True)
        yield service


def _use_api(service, api: FakeImageApi) -> FakeImageApi:
    service.rest_client.post = api.post
    return api


def _mock_planner(service, plan: StoryboardPlan):
    response = MagicMock()
    response.parsed = plan
    response.text = plan.model_dump_json()
    service.mock_genai_client.aio.models.generate_content = AsyncMock(
        return_value=response
    )


def _is_sheet(body) -> bool:
    return "Character reference sheet" in body["prompt"]


def _frame_ids(shot_list: dict) -> list:
    return [
        shot["frame_media_id"]
        for scene in shot_list["scenes"]
        for shot in scene["shots"]
    ]


# --- Prompts ---


def test_system_prompt_rules():
    prompt = build_system_prompt(
        language="German",
        max_frames=30,
        board_type="shot_by_shot",
        options_per_beat=3,
        brand_context="Always show the blue METRO card.",
    )
    assert "VERBATIM" in prompt
    assert "at most 30 shots" in prompt
    assert "German" in prompt
    assert "Always show the blue METRO card." in prompt
    assert "shot by shot" in prompt


def test_moodboard_prompt_asks_for_options():
    prompt = build_system_prompt(
        language="English",
        max_frames=24,
        board_type="moodboard",
        options_per_beat=4,
        brand_context=None,
    )
    assert "4 DIFFERENT visual options" in prompt


def test_frame_prompt_uses_character_refs_and_screenshot_rule():
    plan = _plan()
    scene, shot = list(plan.all_shots())[1]
    prompt = build_frame_prompt(
        shot, scene, plan, "photo_previz", has_character_refs=True
    )
    assert "Photorealistic" in prompt
    assert "look exactly like the reference" in prompt
    assert "blank" in prompt
    assert plan.visual_bible in prompt
    assert "Do not render any text" in prompt


def test_character_sheet_and_edit_prompts():
    plan = _plan()
    sheet = build_character_sheet_prompt(plan.characters[0], "photo_previz")
    assert "turnaround" in sheet and "40s, blonde bun" in sheet
    shot = list(plan.all_shots())[0][1]
    shot.edit_instruction = "Make it night."
    assert "Make it night." in build_edit_prompt(shot)


def test_cap_and_renumber_spreads_budget():
    plan = _plan((3, 3, 3))
    plan.cap_and_renumber(5)
    assert plan.shot_count() == 5
    numbers = [shot.shot_number for _, shot in plan.all_shots()]
    assert numbers == [1, 2, 3, 4, 5]


def test_render_text_house_format():
    plan = _plan()
    text = render_storyboard_text(plan, {1: 11, 2: None, 3: 13, 4: 14})
    assert "SCENE 1: Scene 1 (0-15s)" in text
    assert "Meet Astrid, line 1." in text
    assert "[USE REAL SCREENSHOT]" in text
    assert "image FAILED" in text
    assert "CHARACTERS:" in text


# --- Generate ---


@pytest.mark.anyio
async def test_generate_makes_sheet_then_frames_with_refs(service):
    _mock_planner(service, _plan())
    api = _use_api(service, FakeImageApi())

    result = await service.generate_storyboard(_request(), "Bearer t")

    sheet_bodies = [b for b in api.bodies if _is_sheet(b)]
    frame_bodies = [b for b in api.bodies if not _is_sheet(b)]
    assert len(sheet_bodies) == 1
    assert len(frame_bodies) == 4
    sheet_id = result["character_sheets"][0]
    refs = frame_bodies[0]["source_media_items"]
    assert refs[0]["media_item_id"] == sheet_id
    assert refs[0]["role"] == "image_reference_asset"

    shot_list = result["shot_list"]
    assert shot_list["characters"][0]["character_sheet_id"] == sheet_id
    assert _frame_ids(shot_list) == result["storyboard_frames"]
    assert shot_list["settings"]["max_frames"] == 24
    assert "revision" not in shot_list["scenes"][0]["shots"][0]
    assert "SCENE 2" in result["storyboard_text"]


@pytest.mark.anyio
async def test_generate_without_character_sheets(service):
    _mock_planner(service, _plan())
    api = _use_api(service, FakeImageApi())

    result = await service.generate_storyboard(_request(character_sheets=False))

    assert not any(_is_sheet(b) for b in api.bodies)
    assert result["character_sheets"] == []
    assert "source_media_items" not in api.bodies[0]


@pytest.mark.anyio
async def test_generate_caps_frames(service):
    _mock_planner(service, _plan((4, 4)))
    api = _use_api(service, FakeImageApi())

    result = await service.generate_storyboard(
        _request(max_frames=3, character_sheets=False)
    )

    assert len(api.bodies) == 3
    assert len(result["storyboard_frames"]) == 3


@pytest.mark.anyio
async def test_generate_partial_failure(service):
    _mock_planner(service, _plan())
    _use_api(
        service,
        FakeImageApi(fail_when=lambda b: "Visual 2" in b["prompt"]),
    )

    result = await service.generate_storyboard(_request(character_sheets=False))

    assert len(result["storyboard_frames"]) == 3
    errors = result["shot_list"]["frame_errors"]
    assert len(errors) == 1 and errors[0].startswith("Frame 2")


@pytest.mark.anyio
async def test_generate_sheet_failure_still_renders_frames(service):
    _mock_planner(service, _plan())
    _use_api(service, FakeImageApi(fail_when=_is_sheet))

    result = await service.generate_storyboard(_request())

    assert result["character_sheets"] == []
    assert len(result["storyboard_frames"]) == 4
    assert "Character sheet Astrid" in result["shot_list"]["frame_errors"][0]


@pytest.mark.anyio
async def test_generate_all_frames_fail(service):
    _mock_planner(service, _plan())
    _use_api(service, FakeImageApi(fail_when=lambda b: True))

    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(_request())
    assert exc.value.status_code == 502


@pytest.mark.anyio
async def test_generate_empty_brief(service):
    request = GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="   "),
        config=GenerateStoryboardSettings(),
    )
    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(request)
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_planner_text_fallback_and_invalid(service):
    plan = _plan()
    response = MagicMock()
    response.parsed = None
    response.text = plan.model_dump_json()
    service.mock_genai_client.aio.models.generate_content = AsyncMock(
        return_value=response
    )
    _use_api(service, FakeImageApi())
    result = await service.generate_storyboard(_request())
    assert len(result["storyboard_frames"]) == 4

    response.text = "not json"
    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(_request())
    assert exc.value.status_code == 502


@pytest.mark.anyio
async def test_generate_passes_reference_images(service):
    _mock_planner(service, _plan())
    service._resolve_media_to_parts = AsyncMock(return_value=[])
    api = _use_api(service, FakeImageApi())
    request = GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="reel", reference_images=[55]),
        config=GenerateStoryboardSettings(
            character_sheets=False, plan_first=False
        ),
    )

    result = await service.generate_storyboard(request)

    assert api.bodies[0]["source_media_items"][0]["media_item_id"] == 55
    refs = result["shot_list"]["reference_media_items"]
    assert refs[0]["media_item_id"] == 55


# --- Revise ---


async def _first_board(service) -> dict:
    _mock_planner(service, _plan())
    _use_api(service, FakeImageApi(start=100))
    result = await service.generate_storyboard(_request())
    return result["shot_list"]


def _revision(*changes, characters=(), voiceover=()) -> StoryboardRevision:
    return StoryboardRevision.model_validate(
        {
            "changes": list(changes),
            "character_changes": list(characters),
            "voiceover_changes": list(voiceover),
        }
    )


def _revise_dto(
    shot_list: dict, notes="Frame 2: make it night"
) -> ReviseStoryboardDto:
    return ReviseStoryboardDto(
        workspace_id=7, shot_list=copy.deepcopy(shot_list), change_notes=notes
    )


def test_apply_revision_marks_only_changed_shots():
    plan = _plan()
    revised = apply_revision(
        plan,
        _revision(
            {"op": "edit", "shot_number": 2, "edit_instruction": "Night."},
            {"op": "redraw", "shot_number": 3, "shot": _shot(3, ())},
            {"op": "remove", "shot_number": 4},
            {"op": "add_after", "shot_number": 0, "shot": _shot(9, ())},
            voiceover=[{"scene_number": 2, "voiceover": ["New line."]}],
        ),
    )
    shots = [shot for _, shot in revised.all_shots()]
    assert [s.revision for s in shots] == ["new", "keep", "edit", "redraw"]
    assert [s.source_shot_number for s in shots] == [None, 1, 2, 3]
    assert shots[2].edit_instruction == "Night."
    assert revised.scenes[1].voiceover == ["New line."]
    assert revised.scenes[0].voiceover == ["Meet Astrid, line 1."]


def test_apply_revision_character_change_redraws_their_shots():
    plan = _plan()
    changed = dict(_plan_dict()["characters"][0], look="30s, short hair")
    revised = apply_revision(plan, _revision(characters=[changed]))
    assert all(s.revision == "redraw" for _, s in revised.all_shots())
    assert revised.characters[0].look == "30s, short hair"


def test_apply_revision_ignores_unknown_shots():
    plan = _plan()
    revised = apply_revision(
        plan, _revision({"op": "remove", "shot_number": 99})
    )
    assert revised.shot_count() == 4
    assert all(s.revision == "keep" for _, s in revised.all_shots())


@pytest.mark.anyio
async def test_revise_starts_only_changed_jobs_and_returns_fast(service):
    board = await _first_board(service)
    old_ids = _frame_ids(board)
    service._poll_job_status.reset_mock()

    _mock_planner(
        service,
        _revision(
            {"op": "edit", "shot_number": 2, "edit_instruction": "Night."},
            {"op": "redraw", "shot_number": 3, "shot": _shot(3)},
        ),
    )
    api = _use_api(service, FakeImageApi(start=500))
    result = await service.revise_storyboard(_revise_dto(board), "Bearer t")

    service._poll_job_status.assert_not_called()  # browser polls instead
    new_ids = _frame_ids(result["shot_list"])
    assert new_ids[0] == old_ids[0] and new_ids[3] == old_ids[3]
    assert len(api.bodies) == 2  # sheet reused, only 2 frames touched
    edit_body = next(b for b in api.bodies if "Edit this" in b["prompt"])
    assert edit_body["source_media_items"][0]["media_item_id"] == old_ids[1]
    assert edit_body["source_media_items"][0]["role"] == "input"
    redraw_body = next(b for b in api.bodies if "Visual 3" in b["prompt"])
    sheet_id = board["characters"][0]["character_sheet_id"]
    assert redraw_body["source_media_items"][0]["media_item_id"] == sheet_id

    pending = {p["shot_number"]: p for p in result["pending"]}
    assert set(pending) == {2, 3}
    assert pending[2]["previous_media_id"] == old_ids[1]
    assert pending[2]["media_id"] == new_ids[1]


@pytest.mark.anyio
async def test_revise_failed_edit_keeps_previous_frame(service):
    board = await _first_board(service)
    old_ids = _frame_ids(board)

    _mock_planner(
        service,
        _revision({"op": "edit", "shot_number": 2, "edit_instruction": "x"}),
    )
    _use_api(
        service,
        FakeImageApi(fail_when=lambda b: "Edit this" in b["prompt"]),
    )
    result = await service.revise_storyboard(_revise_dto(board))

    assert result["storyboard_frames"] == old_ids
    assert result["pending"] == []
    assert "kept the previous image" in result["shot_list"]["frame_errors"][0]


@pytest.mark.anyio
async def test_revise_new_look_regenerates_sheet_without_using_it(service):
    board = await _first_board(service)
    old_sheet = board["characters"][0]["character_sheet_id"]
    changed = dict(_plan_dict()["characters"][0], look="30s")

    _mock_planner(service, _revision(characters=[changed]))
    api = _use_api(service, FakeImageApi(start=900))
    result = await service.revise_storyboard(_revise_dto(board, "Younger"))

    assert sum(_is_sheet(b) for b in api.bodies) == 1
    frame_bodies = [b for b in api.bodies if not _is_sheet(b)]
    assert len(frame_bodies) == 4
    # The new sheet is still rendering, so frames do not reference it.
    assert all("source_media_items" not in b for b in frame_bodies)
    kinds = [p["kind"] for p in result["pending"]]
    assert kinds.count("character_sheet") == 1
    assert result["character_sheets"][0] != old_sheet


@pytest.mark.anyio
async def test_revise_rejects_foreign_shot_list(service):
    with pytest.raises(HTTPException) as exc:
        await service.revise_storyboard(
            ReviseStoryboardDto(
                workspace_id=7, shot_list={"foo": 1}, change_notes="x"
            )
        )
    assert exc.value.status_code == 400


# --- Plan first: approve, then draw ---


async def _approved_plan(service) -> dict:
    """A plan-first run: text plan only, nothing drawn."""
    _mock_planner(service, _plan())
    api = _use_api(service, FakeImageApi())
    result = await service.generate_storyboard(_request(plan_first=True))
    assert api.bodies == []
    return result


def _render_dto(shot_list: dict, phase: str) -> RenderStoryboardDto:
    return RenderStoryboardDto(
        workspace_id=7, shot_list=copy.deepcopy(shot_list), phase=phase
    )


@pytest.mark.anyio
async def test_plan_first_returns_plan_without_images(service):
    result = await _approved_plan(service)

    shot_list = result["shot_list"]
    assert shot_list["awaiting_approval"] is True
    assert result["storyboard_frames"] == []
    assert _frame_ids(shot_list) == [None, None, None, None]
    assert "awaiting approval" in result["storyboard_text"]
    assert "not drawn yet" in result["storyboard_text"]
    assert "image FAILED" not in result["storyboard_text"]


@pytest.mark.anyio
async def test_plan_only_revise_changes_text_and_draws_nothing(service):
    plan_board = (await _approved_plan(service))["shot_list"]
    _mock_planner(service, _revision({"op": "remove", "shot_number": 4}))
    api = _use_api(service, FakeImageApi())

    dto = _revise_dto(plan_board, "Cut the last shot")
    dto.plan_only = True
    result = await service.revise_storyboard(dto)

    assert api.bodies == []
    assert result["shot_list"]["awaiting_approval"] is True
    assert len(_frame_ids(result["shot_list"])) == 3


@pytest.mark.anyio
async def test_render_sheets_then_frames(service):
    plan_board = (await _approved_plan(service))["shot_list"]
    service._poll_job_status.reset_mock()

    sheets_api = _use_api(service, FakeImageApi(start=300))
    after_sheets = await service.render_storyboard(
        _render_dto(plan_board, "sheets"), "Bearer t"
    )
    assert len(sheets_api.bodies) == 1 and _is_sheet(sheets_api.bodies[0])
    assert after_sheets["pending"][0]["kind"] == "character_sheet"
    assert after_sheets["shot_list"]["awaiting_approval"] is True
    sheet_id = after_sheets["character_sheets"][0]

    frames_api = _use_api(service, FakeImageApi(start=400))
    drawn = await service.render_storyboard(
        _render_dto(after_sheets["shot_list"], "frames"), "Bearer t"
    )
    service._poll_job_status.assert_not_called()
    assert len(frames_api.bodies) == 4
    assert all(
        b["source_media_items"][0]["media_item_id"] == sheet_id
        for b in frames_api.bodies
    )
    assert drawn["shot_list"]["awaiting_approval"] is False
    assert len(drawn["pending"]) == 4
    assert drawn["storyboard_frames"] == _frame_ids(drawn["shot_list"])


@pytest.mark.anyio
async def test_render_frames_skips_frames_already_drawn(service):
    board = await _first_board(service)
    api = _use_api(service, FakeImageApi(start=700))
    result = await service.render_storyboard(_render_dto(board, "frames"))
    assert api.bodies == []
    assert result["storyboard_frames"] == _frame_ids(board)


@pytest.mark.anyio
async def test_render_rejects_foreign_shot_list(service):
    with pytest.raises(HTTPException) as exc:
        await service.render_storyboard(
            RenderStoryboardDto(
                workspace_id=7, shot_list={"x": 1}, phase="frames"
            )
        )
    assert exc.value.status_code == 400


def test_render_endpoint_passes_auth_header():
    executor = MagicMock()
    executor.render_storyboard = AsyncMock(return_value={"pending": []})
    client = _client(AsyncMock(), executor)

    response = client.post(
        "/api/workflows/storyboard/render",
        json={"workspace_id": 7, "shot_list": _plan_dict(), "phase": "sheets"},
        headers={"Authorization": "Bearer abc"},
    )

    assert response.status_code == 200
    dto, auth = executor.render_storyboard.call_args.args
    assert auth == "Bearer abc" and dto.phase == "sheets"


# --- Contract with the image API (drift guards) ---


@pytest.mark.anyio
async def test_all_image_requests_match_image_api_contract(service):
    board = await _first_board(service)
    _mock_planner(
        service,
        _revision(
            {"op": "edit", "shot_number": 2, "edit_instruction": "Night."},
            {"op": "redraw", "shot_number": 3, "shot": _shot(3)},
        ),
    )
    revised = _use_api(service, FakeImageApi(start=500))
    await service.revise_storyboard(_revise_dto(board))
    _mock_planner(service, _plan())
    first = _use_api(service, FakeImageApi())
    await service.generate_storyboard(_request())

    for body in first.bodies + revised.bodies:
        assert set(body) <= set(CreateImagenDto.model_fields)
        CreateImagenDto.model_validate(body)


def test_default_models_are_known_to_backend():
    known = {m.value for m in GenerationModelEnum}
    defaults = GenerateStoryboardSettings()
    assert defaults.image_model in known
    assert defaults.reasoning_model in known
    preset_settings = (
        load_presets()["storyboard_generator"].workflow.steps[1].settings
    )
    assert preset_settings.image_model in known
    assert preset_settings.reasoning_model in known


# --- Presets, YAML and API ---


def test_presets_load_and_validate():
    presets = load_presets()
    assert "storyboard_generator" in presets
    steps = presets["storyboard_generator"].workflow.steps
    assert steps[1].type.value == "generate_storyboard"
    assert steps[1].settings.frame_style == "photo_previz"
    assert steps[1].settings.plan_first is True


def test_storyboard_step_gets_long_timeout_in_yaml():
    preset = load_presets()["storyboard_generator"]
    model = WorkflowModel(
        id="wf-1",
        user_id=1,
        name=preset.name,
        description=preset.description,
        steps=preset.workflow.steps,
    )
    service = WorkflowService(
        workflow_repository=MagicMock(),
        workflow_run_repository=MagicMock(),
        source_asset_service=MagicMock(),
    )
    parsed = yaml.safe_load(service._generate_workflow_yaml(model))
    step = parsed["main"]["steps"][0]["storyboard"]
    assert step["args"]["timeout"] == 1800
    assert step["args"]["url"].endswith("/generate_storyboard")
    assert step["args"]["body"]["inputs"]["brief"] == (
        "${args.Script_or_video_idea}"
    )


def _client(mock_service, mock_executor=None) -> TestClient:
    user = UserModel(
        id=1,
        email="t@example.com",
        name="T",
        roles=[UserRoleEnum.USER, UserRoleEnum.WORKFLOWS],
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[WorkflowService] = lambda: mock_service
    if mock_executor is not None:
        app.dependency_overrides[WorkflowsExecutorService] = (
            lambda: mock_executor
        )
    return TestClient(app)


def test_install_preset_endpoint():
    mock_service = AsyncMock()
    mock_service.create_workflow = AsyncMock(
        return_value={"id": "wf-new", "name": "Storyboard Generator"}
    )
    client = _client(mock_service)

    listed = client.get("/api/workflows/presets")
    assert listed.status_code == 200
    assert any(p["id"] == "storyboard_generator" for p in listed.json())

    installed = client.post(
        "/api/workflows/presets/storyboard_generator/install"
    )
    assert installed.status_code == 201
    mock_service.create_workflow.assert_awaited_once()

    missing = client.post("/api/workflows/presets/nope/install")
    assert missing.status_code == 404


def test_revise_endpoint_passes_auth_header():
    executor = MagicMock()
    executor.revise_storyboard = AsyncMock(
        return_value={"storyboard_frames": []}
    )
    client = _client(AsyncMock(), executor)

    response = client.post(
        "/api/workflows/storyboard/revise",
        json={
            "workspace_id": 7,
            "shot_list": _plan_dict(),
            "change_notes": "Frame 2: night",
        },
        headers={"Authorization": "Bearer abc"},
    )

    assert response.status_code == 200
    dto, auth = executor.revise_storyboard.call_args.args
    assert auth == "Bearer abc"
    assert dto.change_notes == "Frame 2: night"
