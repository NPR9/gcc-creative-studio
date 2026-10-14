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

"""Helpers to align logged model IDs with seeded unit-price rows."""

from __future__ import annotations

from enum import Enum

# Explicit aliases where preview/lite IDs should reuse stable pricing rows.
MODEL_PRICE_ALIASES: dict[str, str] = {
    "gemini-2.5-flash-image-preview": "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview": "gemini-3.1-flash-image",
    "gemini-3-pro-image-preview": "gemini-3-pro-image",
    "gemini-3.1-flash-lite-image": "gemini-3.1-flash-image",
    "gemini-3-pro-preview": "gemini-3.1-pro-preview",
    "gemini-3-flash-preview": "gemini-3.5-flash",
    "gemini-omni-flash-preview": "veo-3.1-fast-generate-001",
    "gemini-omni-generate-preview": "veo-3.1-generate-001",
    "chirp_3": "gemini-2.5-flash-tts",
}


def normalize_model_name(model: str | Enum) -> str:
    """Return a canonical model string for usage logging and pricing lookup."""
    if isinstance(model, Enum):
        raw = str(model.value)
    else:
        raw = str(model).strip()

    if raw in MODEL_PRICE_ALIASES:
        return MODEL_PRICE_ALIASES[raw]

    if raw.endswith("-preview"):
        base = raw[: -len("-preview")]
        if base in MODEL_PRICE_ALIASES:
            return MODEL_PRICE_ALIASES[base]
        return base

    return raw


def resolve_price_row(
    model: str,
    price_map: dict[str, dict[str, object]],
) -> dict[str, object]:
    """Find the best matching unit-price row for a logged model ID."""
    candidates = [normalize_model_name(model), str(model).strip()]
    if str(model).strip() in MODEL_PRICE_ALIASES:
        candidates.append(MODEL_PRICE_ALIASES[str(model).strip()])

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        prices = price_map.get(candidate)
        if prices:
            return prices

    return {}
