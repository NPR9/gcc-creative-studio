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
"""Tests for the Asset Multiplication size library."""

import json

import pytest

from src.workflows_executor.creative.size_library import (
    group_by_generation_ratio,
    load_size_library,
    nearest_generation_ratio,
)


def test_bundled_library_loads_paid_social_sizes():
    library = load_size_library()
    ids = {s.id for s in library.sizes}
    assert ids == {
        "square_1200",
        "landscape_1200x628",
        "vertical_1080x1920",
        "portrait_960x1200",
    }
    assert set(library.channel_presets) == {"meta", "demandgen", "pmax"}


def test_presets_select_their_channel_sizes():
    library = load_size_library()
    meta = [s.id for s in library.select("meta", None)]
    assert "portrait_960x1200" not in meta  # Meta does not use 960x1200
    assert len(library.select("pmax", None)) == 4


def test_cta_rule_follows_spec():
    library = load_size_library()
    assert library.preset("pmax").cta is True
    assert library.preset("meta").cta is False
    assert library.preset("demandgen").cta is False


def test_explicit_size_override_wins_over_preset():
    library = load_size_library()
    sizes = library.select("meta", " portrait_960x1200 , square_1200 ")
    assert [s.id for s in sizes] == ["portrait_960x1200", "square_1200"]


def test_unknown_size_and_preset_raise():
    library = load_size_library()
    with pytest.raises(ValueError, match="Unknown size"):
        library.select("meta", "nope")
    with pytest.raises(ValueError, match="Unknown channel preset"):
        library.select("tiktok", None)


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1200, 1200, "1:1"),
        (1200, 628, "16:9"),
        (1080, 1920, "9:16"),
        (960, 1200, "4:5"),
        (728, 90, "8:1"),
        (160, 600, "1:4"),
        (300, 250, "5:4"),
    ],
)
def test_nearest_generation_ratio(width, height, expected):
    assert nearest_generation_ratio(width, height) == expected


def test_paid_social_needs_four_renders_for_four_sizes():
    library = load_size_library()
    groups = group_by_generation_ratio(library.select("pmax", None))
    assert set(groups) == {"1:1", "16:9", "9:16", "4:5"}


def test_sizes_sharing_a_ratio_share_one_render(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(
        json.dumps(
            {
                "sizes": [
                    {
                        "id": "a",
                        "width": 1200,
                        "height": 1200,
                        "channels": ["x"],
                    },
                    {
                        "id": "b",
                        "width": 1080,
                        "height": 1080,
                        "channels": ["x"],
                    },
                ],
                "channel_presets": {"x": {"label": "X", "cta": False}},
            }
        )
    )
    groups = group_by_generation_ratio(
        load_size_library(path).select("x", None)
    )
    assert list(groups) == ["1:1"]
    assert [s.id for s in groups["1:1"]] == ["a", "b"]


def test_library_validation(tmp_path):
    path = tmp_path / "lib.json"
    base = {"channel_presets": {}}
    path.write_text(
        json.dumps({**base, "sizes": [{"id": "a", "width": 0, "height": 5}]})
    )
    with pytest.raises(ValueError, match="positive"):
        load_size_library(path)
    path.write_text(
        json.dumps(
            {
                **base,
                "sizes": [
                    {"id": "a", "width": 5, "height": 5},
                    {"id": "a", "width": 6, "height": 6},
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="unique"):
        load_size_library(path)
    path.write_text(
        json.dumps(
            {
                **base,
                "sizes": [
                    {
                        "id": "a",
                        "width": 5,
                        "height": 5,
                        "generation_ratio": "7:3",
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="unsupported"):
        load_size_library(path)


def test_ratio_limited_to_model_support():
    pro = [
        "1:1",
        "3:4",
        "4:3",
        "2:3",
        "3:2",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
    ]
    assert nearest_generation_ratio(728, 90, pro) == "21:9"
    assert nearest_generation_ratio(160, 600, pro) == "9:16"
    with pytest.raises(ValueError):
        nearest_generation_ratio(10, 10, [])
