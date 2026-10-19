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

"""Workflow presets: ready-made workflow definitions shipped with the app.

Each preset is a JSON file in this folder. Users "install" a preset, which
creates a normal, editable workflow owned by them. Adding a new preset is a
JSON file, not code.
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from src.workflows.schema.workflow_model import WorkflowCreateDto

PRESETS_DIR = Path(__file__).parent


class WorkflowPreset(BaseModel):
    id: str
    name: str
    description: str
    category: str = "General"
    workflow: WorkflowCreateDto


@lru_cache(maxsize=1)
def load_presets() -> dict[str, WorkflowPreset]:
    """Loads and validates every *.json preset once per process.

    Validation runs against the same schema as user-created workflows, so a
    broken preset fails loudly at startup/test time instead of at install.
    """
    presets: dict[str, WorkflowPreset] = {}
    for path in sorted(PRESETS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        preset = WorkflowPreset(
            id=raw["id"],
            name=raw["name"],
            description=raw["description"],
            category=raw.get("category", "General"),
            workflow=WorkflowCreateDto(
                name=raw["name"],
                description=raw["description"],
                steps=raw["steps"],
            ),
        )
        if preset.id in presets:
            raise ValueError(f"Duplicate workflow preset id: {preset.id}")
        presets[preset.id] = preset
    return presets
