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
"""The shipped presets must parse and compile to Cloud Workflows YAML."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from src.workflows.presets.workflow_presets import load_presets
from src.workflows.schema.workflow_model import (
    AssetMultiplicationStep,
    NodeTypes,
    ProductInSceneStep,
    WorkflowModel,
)
from src.workflows.workflow_service import WorkflowService


@pytest.fixture(name="workflow_service")
def fixture_workflow_service():
    return WorkflowService(
        workflow_repository=AsyncMock(),
        workflow_run_repository=AsyncMock(),
        source_asset_service=MagicMock(),
    )


def _load(preset_id: str) -> WorkflowModel:
    preset = load_presets()[preset_id]
    return WorkflowModel(id="preset", user_id=1, **preset.workflow.model_dump())


def test_all_presets_load_side_by_side():
    presets = load_presets()
    assert {
        "storyboard_generator",
        "product_in_scene",
        "asset_multiplication",
    } <= set(presets)


@pytest.mark.parametrize(
    ("preset_id", "step_cls", "step_type", "args"),
    [
        (
            "product_in_scene",
            ProductInSceneStep,
            NodeTypes.PRODUCT_IN_SCENE,
            {"Product_packshot", "Scene_description"},
        ),
        (
            "asset_multiplication",
            AssetMultiplicationStep,
            NodeTypes.ASSET_MULTIPLICATION,
            {"Master_visual", "Headline", "CTA_text"},
        ),
    ],
)
def test_preset_compiles(
    workflow_service, preset_id, step_cls, step_type, args
):
    model = _load(preset_id)
    step = next(s for s in model.steps if s.type == step_type)
    assert isinstance(step, step_cls)

    parsed = yaml.safe_load(workflow_service._generate_workflow_yaml(model))
    steps = parsed["main"]["steps"]
    assert len(steps) == 1
    call = steps[0][step_type.value]["args"]
    assert call["url"].endswith(f"/{step_type.value}")
    assert call["timeout"] == 1800  # several renders in one call
    referenced = {
        v[len("${args.") : -1]
        for v in call["body"]["inputs"].values()
        if isinstance(v, str) and v.startswith("${args.")
    }
    assert referenced == args


def test_asset_multiplication_blank_sizes_become_none():
    model = _load("asset_multiplication")
    step = next(
        s for s in model.steps if s.type == NodeTypes.ASSET_MULTIPLICATION
    )
    assert step.settings.sizes is None
    assert step.settings.quality == "preview"
