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
"""Size library for the Asset Multiplication workflow.

The library is a JSON file so marketing can add or change sizes without a
code change. Each size is rendered from the nearest aspect ratio the image
models support natively, then cropped and resized to exact pixels.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from src.common.base_dto import AspectRatioEnum

DEFAULT_LIBRARY_PATH = Path(__file__).with_name("size_library.json")


@dataclass(frozen=True)
class SafeZone:
    top: float = 0.06
    right: float = 0.06
    bottom: float = 0.06
    left: float = 0.06


@dataclass(frozen=True)
class SizeSpec:
    id: str
    name: str
    width: int
    height: int
    channels: tuple[str, ...]
    safe_zone: SafeZone = field(default_factory=SafeZone)
    generation_ratio: str | None = None

    @property
    def ratio(self) -> float:
        return self.width / self.height


@dataclass(frozen=True)
class ChannelPreset:
    id: str
    label: str
    cta: bool


@dataclass(frozen=True)
class SizeLibrary:
    """All sizes and channel presets, loaded from size_library.json."""

    sizes: tuple[SizeSpec, ...]
    channel_presets: dict[str, ChannelPreset]

    def get(self, size_id: str) -> SizeSpec:
        for size in self.sizes:
            if size.id == size_id:
                return size
        known = ", ".join(s.id for s in self.sizes)
        raise ValueError(f"Unknown size '{size_id}'. Known sizes: {known}")

    def preset(self, preset_id: str) -> ChannelPreset:
        if preset_id not in self.channel_presets:
            known = ", ".join(self.channel_presets)
            raise ValueError(
                f"Unknown channel preset '{preset_id}'. Known presets: {known}"
            )
        return self.channel_presets[preset_id]

    def select(self, preset_id: str, size_ids: str | None) -> list[SizeSpec]:
        """Sizes for a run: the explicit override list, else the preset."""
        self.preset(preset_id)  # validates the preset
        if size_ids:
            ids = [s.strip() for s in size_ids.split(",") if s.strip()]
            return [self.get(size_id) for size_id in ids]
        return [s for s in self.sizes if preset_id in s.channels]


def supported_generation_ratios() -> dict[str, float]:
    """Aspect ratios the image models render natively, as value -> float."""
    ratios = {}
    for member in AspectRatioEnum:
        if ":" not in member.value:
            continue
        w, h = member.value.split(":")
        ratios[member.value] = float(w) / float(h)
    return ratios


def nearest_generation_ratio(
    width: int, height: int, allowed: Iterable[str] | None = None
) -> str:
    """Closest native ratio, optionally limited to what a model supports."""
    target = width / height
    ratios = supported_generation_ratios()
    if allowed is not None:
        allowed_set = set(allowed)
        ratios = {k: v for k, v in ratios.items() if k in allowed_set}
        if not ratios:
            raise ValueError("The model supports none of the known ratios")
    return min(ratios, key=lambda r: abs(ratios[r] - target))


def generation_ratio_for(
    size: SizeSpec, allowed: Iterable[str] | None = None
) -> str:
    """The library's ratio for this size if the model supports it, else
    the nearest ratio the model does support."""
    if size.generation_ratio and (
        allowed is None or size.generation_ratio in set(allowed)
    ):
        return size.generation_ratio
    return nearest_generation_ratio(size.width, size.height, allowed)


def group_by_generation_ratio(
    sizes: list[SizeSpec], allowed: Iterable[str] | None = None
) -> dict[str, list[SizeSpec]]:
    """One render per native ratio; every size in a group is cut from it."""
    allowed = list(allowed) if allowed is not None else None
    groups: dict[str, list[SizeSpec]] = {}
    for size in sizes:
        groups.setdefault(generation_ratio_for(size, allowed), []).append(size)
    return groups


def load_size_library(path: Path | str | None = None) -> SizeLibrary:
    raw = json.loads(Path(path or DEFAULT_LIBRARY_PATH).read_text("utf-8"))
    sizes = []
    for item in raw["sizes"]:
        if item["width"] <= 0 or item["height"] <= 0:
            size_id = item["id"]
            raise ValueError(f"Size '{size_id}' must have positive pixels")
        ratio = item.get("generation_ratio")
        if ratio and ratio not in supported_generation_ratios():
            bad_id = item["id"]
            raise ValueError(
                f"Size '{bad_id}' has unsupported "
                f"generation_ratio '{ratio}'"
            )
        sizes.append(
            SizeSpec(
                id=item["id"],
                name=item.get("name", item["id"]),
                width=int(item["width"]),
                height=int(item["height"]),
                channels=tuple(item.get("channels", [])),
                safe_zone=SafeZone(**item.get("safe_zone", {})),
                generation_ratio=ratio,
            )
        )
    ids = [s.id for s in sizes]
    if len(ids) != len(set(ids)):
        raise ValueError("Size ids in the size library must be unique")
    presets = {
        key: ChannelPreset(
            id=key, label=val.get("label", key), cta=bool(val.get("cta"))
        )
        for key, val in raw.get("channel_presets", {}).items()
    }
    return SizeLibrary(sizes=tuple(sizes), channel_presets=presets)
