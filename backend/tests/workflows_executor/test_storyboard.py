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
"""Tests for the Storyboard workflow step and workflow presets."""

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
from src.workflows.workflow_controller import router
from src.workflows.workflow_service import WorkflowService
from src.workflows.presets.workflow_presets import load_presets
from src.workflows.schema.workflow_model import (
    GenerateStoryboardInputs,
    GenerateStoryboardSettings,
    WorkflowModel,
)
from src.workflows_executor.dto.workflows_executor_dto import (
    GenerateStoryboardRequest,
)
from src.workflows_executor.storyboard.storyboard_prompts import (
    StoryboardPlan,
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


def _plan(num_shots: int = 3) -> StoryboardPlan:
    return StoryboardPlan.model_validate(
        {
            "title": "Autumn HoReCa promo",
            "objective": "Drive restaurant owners to the store",
            "target_audience": "Independent restaurant owners",
            "channel_and_format": "Instagram Reels 9:16, 15s",
            "total_duration_seconds": 15,
            "key_message": "Fresh produce, wholesale prices",
            "visual_bible": "Chef, 40s, white jacket; bright warehouse aisle",
            "assumptions": ["No offer price given; placeholder used"],
            "open_questions": ["What is the promo price?"],
            "shots": [
                {
                    # Deliberately out of order to test renumbering.
                    "shot_number": num_shots - i,
                    "beat": "Hook",
                    "duration_seconds": 15 / num_shots,
                    "shot_type": "Close-up",
                    "camera_movement": "Static",
                    "action": f"Action {num_shots - i}",
                    "on_screen_text": "[PRICE]",
                    "voiceover": None,
                    "sound_notes": None,
                    "visual_prompt": f"Visual {num_shots - i}",
                }
                for i in range(num_shots)
            ],
        }
    )


def _request(**settings) -> GenerateStoryboardRequest:
    return GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="15s reel for chefs"),
        config=GenerateStoryboardSettings(**settings),
    )


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient",
        ) as mock_rest_client_class,
        patch(GENAI_INIT_PATH) as mock_genai_init,
    ):
        mock_rest_client = AsyncMock()
        mock_rest_client_class.return_value = mock_rest_client
        mock_genai_client = MagicMock()
        mock_genai_init.return_value = mock_genai_client

        service = WorkflowsExecutorService()
        service.mock_rest_client = mock_rest_client
        service.mock_genai_client = mock_genai_client
        service._poll_job_status = AsyncMock(return_value=True)
        yield service


def _mock_plan_response(service, plan: StoryboardPlan):
    response = MagicMock()
    response.parsed = plan
    response.text = plan.model_dump_json()
    service.mock_genai_client.aio.models.generate_content = AsyncMock(
        return_value=response
    )


# --- Prompt helpers ---


def test_system_prompt_includes_limits_and_brand_context():
    prompt = build_system_prompt(
        language="German",
        min_frames=3,
        max_frames=6,
        brand_context="Always show the blue METRO card.",
    )
    assert "between 3 and 6" in prompt
    assert "German" in prompt
    assert "Always show the blue METRO card." in prompt


def test_frame_prompt_carries_continuity_and_no_text_rule():
    plan = _plan()
    prompt = build_frame_prompt(plan.shots[0], plan, "sketch")
    assert plan.visual_bible in prompt
    assert "pencil" in prompt
    assert "Do not render any text" in prompt


def test_render_text_marks_failed_frames():
    plan = _plan(2)
    text = render_storyboard_text(plan, {2: 11, 1: None})
    assert "OPEN QUESTIONS" in text
    assert "image #11" in text
    assert "image FAILED" in text


# --- Executor ---


@pytest.mark.anyio
async def test_generate_storyboard_happy_path(service):
    _mock_plan_response(service, _plan(3))
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": 101}),
        Response(200, json={"id": 102}),
        Response(200, json={"id": 103}),
    ]

    result = await service.generate_storyboard(_request(), "Bearer t")

    assert result["storyboard_frames"] == [101, 102, 103]
    shots = result["shot_list"]["shots"]
    assert [s["shot_number"] for s in shots] == [1, 2, 3]
    assert [s["frame_media_id"] for s in shots] == [101, 102, 103]
    assert result["shot_list"]["frame_errors"] == []
    assert "STORYBOARD: Autumn HoReCa promo" in result["storyboard_text"]

    first_body = service.mock_rest_client.post.call_args_list[0].kwargs["json"]
    assert first_body["workspace_id"] == 7
    assert first_body["aspect_ratio"] == "16:9"
    assert first_body["use_brand_guidelines"] is True
    assert "source_media_items" not in first_body


@pytest.mark.anyio
async def test_generate_storyboard_caps_frames(service):
    _mock_plan_response(service, _plan(5))
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": i}) for i in range(1, 4)
    ]

    result = await service.generate_storyboard(_request(max_frames=3))

    assert len(result["shot_list"]["shots"]) == 3
    assert service.mock_rest_client.post.call_count == 3


@pytest.mark.anyio
async def test_generate_storyboard_partial_failure(service):
    _mock_plan_response(service, _plan(3))
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": 101}),
        Response(500, text="quota"),
        Response(200, json={"id": 103}),
    ]

    result = await service.generate_storyboard(_request())

    assert result["storyboard_frames"] == [101, 103]
    assert result["shot_list"]["shots"][1]["frame_media_id"] is None
    assert len(result["shot_list"]["frame_errors"]) == 1


@pytest.mark.anyio
async def test_generate_storyboard_all_frames_fail(service):
    _mock_plan_response(service, _plan(3))
    service.mock_rest_client.post.return_value = Response(500, text="down")

    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(_request())
    assert exc.value.status_code == 502


@pytest.mark.anyio
async def test_generate_storyboard_empty_brief(service):
    request = GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="   "),
        config=GenerateStoryboardSettings(),
    )
    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(request)
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_generate_storyboard_falls_back_to_text_parse(service):
    plan = _plan(3)
    response = MagicMock()
    response.parsed = None
    response.text = plan.model_dump_json()
    service.mock_genai_client.aio.models.generate_content = AsyncMock(
        return_value=response
    )
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": i}) for i in range(1, 4)
    ]

    result = await service.generate_storyboard(_request())
    assert len(result["storyboard_frames"]) == 3


@pytest.mark.anyio
async def test_generate_storyboard_invalid_plan(service):
    response = MagicMock()
    response.parsed = None
    response.text = "not json"
    service.mock_genai_client.aio.models.generate_content = AsyncMock(
        return_value=response
    )
    with pytest.raises(HTTPException) as exc:
        await service.generate_storyboard(_request())
    assert exc.value.status_code == 502


@pytest.mark.anyio
async def test_generate_storyboard_passes_reference_images(service):
    _mock_plan_response(service, _plan(3))
    service._resolve_media_to_parts = AsyncMock(return_value=[])
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": i}) for i in range(1, 4)
    ]
    request = GenerateStoryboardRequest(
        workspace_id=7,
        inputs=GenerateStoryboardInputs(brief="reel", reference_images=[55]),
        config=GenerateStoryboardSettings(),
    )

    await service.generate_storyboard(request)

    body = service.mock_rest_client.post.call_args_list[0].kwargs["json"]
    assert body["source_media_items"][0]["media_item_id"] == 55


# --- Presets + YAML ---


def test_presets_load_and_validate():
    presets = load_presets()
    assert "storyboard_generator" in presets
    steps = presets["storyboard_generator"].workflow.steps
    assert steps[1].type.value == "generate_storyboard"


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
        "${args.Describe_your_video}"
    )


def test_install_preset_endpoint():
    user = UserModel(
        id=1,
        email="t@example.com",
        name="T",
        roles=[UserRoleEnum.USER, UserRoleEnum.WORKFLOWS],
    )
    mock_service = AsyncMock()
    mock_service.create_workflow = AsyncMock(
        return_value={"id": "wf-new", "name": "Storyboard Generator"}
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[WorkflowService] = lambda: mock_service
    client = TestClient(app)

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


@pytest.mark.anyio
async def test_frame_request_matches_image_api_contract(service):
    """Guards against drift: the image endpoint forbids unknown fields and
    only accepts known model names, so a mismatch fails every frame."""
    _mock_plan_response(service, _plan(3))
    service.mock_rest_client.post.side_effect = [
        Response(200, json={"id": i}) for i in range(1, 4)
    ]

    await service.generate_storyboard(_request())

    body = service.mock_rest_client.post.call_args_list[0].kwargs["json"]
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
