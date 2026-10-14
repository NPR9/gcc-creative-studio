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

"""Seed unit prices from public Google Gemini / Vertex pricing pages.

Sources (approx. July 2026):
- https://ai.google.dev/gemini-api/docs/pricing
- https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing

Values are Standard paid-tier estimates for cost reporting only — not an
invoice. Token prices are stored per token (= listed $/1M ÷ 1_000_000).
"""

from __future__ import annotations

from decimal import Decimal

from src.usage.schema.genai_model_unit_price_model import GenAIUnitType

SOURCE_NOTE = (
    "Seeded from Google AI / Vertex public pricing (approx. Jul 2026). "
    "Estimates only; verify against your Cloud billing."
)


def _per_million(usd_per_million: float) -> Decimal:
    return Decimal(str(usd_per_million)) / Decimal("1000000")


def _usd(value: float) -> Decimal:
    return Decimal(str(value))


# (model, unit_type, unit_price_usd, notes)
SEED_UNIT_PRICES: list[tuple[str, str, Decimal, str]] = [
    # --- Text / multimodal Gemini ---
    (
        "gemini-2.5-flash",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.30),
        "Gemini 2.5 Flash input (text/image/video)",
    ),
    (
        "gemini-2.5-flash",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(2.50),
        "Gemini 2.5 Flash output (incl. thinking)",
    ),
    (
        "gemini-2.5-pro",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(1.25),
        "Gemini 2.5 Pro input (<=200k context)",
    ),
    (
        "gemini-2.5-pro",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(10.00),
        "Gemini 2.5 Pro output (<=200k context)",
    ),
    (
        "gemini-3.5-flash",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(1.50),
        "Gemini 3.5 Flash input",
    ),
    (
        "gemini-3.5-flash",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(9.00),
        "Gemini 3.5 Flash output",
    ),
    (
        "gemini-3.1-pro-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(2.00),
        "Gemini 3.1 Pro Preview input",
    ),
    (
        "gemini-3.1-pro-preview",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(12.00),
        "Gemini 3.1 Pro Preview output",
    ),
    # --- Gemini image models ---
    (
        "gemini-2.5-flash-image",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.30),
        "Gemini 2.5 Flash Image input",
    ),
    (
        "gemini-2.5-flash-image",
        GenAIUnitType.IMAGE.value,
        _usd(0.039),
        "Gemini 2.5 Flash Image ~per output image",
    ),
    (
        "gemini-3.1-flash-image",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Gemini 3.1 Flash Image input",
    ),
    (
        "gemini-3.1-flash-image",
        GenAIUnitType.IMAGE.value,
        _usd(0.067),
        "Gemini 3.1 Flash Image ~1K output image",
    ),
    (
        "gemini-3-pro-image",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(2.00),
        "Gemini 3 Pro Image input",
    ),
    (
        "gemini-3-pro-image",
        GenAIUnitType.IMAGE.value,
        _usd(0.134),
        "Gemini 3 Pro Image ~1K/2K output image",
    ),
    # --- Imagen ---
    (
        "imagen-4.0-fast-generate-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.02),
        "Imagen 4 Fast per image",
    ),
    (
        "imagen-4.0-fast-generate-preview-06-06",
        GenAIUnitType.IMAGE.value,
        _usd(0.02),
        "Imagen 4 Fast preview per image",
    ),
    (
        "imagen-4.0-generate-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.04),
        "Imagen 4 Standard per image",
    ),
    (
        "imagen-4.0-ultra-generate-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.06),
        "Imagen 4 Ultra per image",
    ),
    (
        "imagen-4.0-ultra-generate-preview-06-06",
        GenAIUnitType.IMAGE.value,
        _usd(0.06),
        "Imagen 4 Ultra preview per image",
    ),
    (
        "imagen-4.0-upscale-preview",
        GenAIUnitType.IMAGE.value,
        _usd(0.06),
        "Imagen 4 upscale per image",
    ),
    (
        "imagen-3.0-generate-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.04),
        "Imagen 3 per image",
    ),
    (
        "imagen-3.0-generate-002",
        GenAIUnitType.IMAGE.value,
        _usd(0.04),
        "Imagen 3 per image",
    ),
    (
        "imagen-3.0-fast-generate-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.02),
        "Imagen 3 Fast per image",
    ),
    (
        "virtual-try-on-001",
        GenAIUnitType.IMAGE.value,
        _usd(0.04),
        "VTO approximated at Imagen-standard per image",
    ),
    # --- Veo (with audio default rates where listed) ---
    (
        "veo-3.1-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.40),
        "Veo 3.1 Standard with audio (720p/1080p)",
    ),
    (
        "veo-3.1-generate-preview",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.40),
        "Veo 3.1 Preview ~Standard with audio",
    ),
    (
        "veo-3.1-fast-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.10),
        "Veo 3.1 Fast with audio (720p)",
    ),
    (
        "veo-3.1-lite-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.05),
        "Veo 3.1 Lite with audio (720p)",
    ),
    (
        "veo-3.0-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.40),
        "Veo 3 Standard with audio",
    ),
    (
        "veo-3.0-generate-preview",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.40),
        "Veo 3 Quality preview ~Standard",
    ),
    (
        "veo-3.0-fast-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.10),
        "Veo 3 Fast with audio (720p)",
    ),
    (
        "veo-3.0-fast-generate-preview",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.10),
        "Veo 3 Fast preview",
    ),
    (
        "veo-2.0-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.35),
        "Veo 2 per second",
    ),
    (
        "veo-2.0-fast-generate-001",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.35),
        "Veo 2 quality/fast alias ~Veo 2 rate",
    ),
    (
        "veo-2.0-generate-exp",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.35),
        "Veo 2 exp ~Veo 2 rate",
    ),
    # --- Audio / TTS / music ---
    (
        "gemini-2.5-flash-tts",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Gemini 2.5 Flash TTS input (approx.)",
    ),
    (
        "gemini-2.5-flash-tts",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(10.00),
        "Gemini 2.5 Flash Preview TTS audio output $/1M",
    ),
    (
        "gemini-2.5-flash-lite-preview-tts",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Gemini 2.5 Flash-Lite TTS input (approx.)",
    ),
    (
        "gemini-2.5-flash-lite-preview-tts",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(10.00),
        "Gemini 2.5 Flash-Lite TTS audio output (approx.)",
    ),
    (
        "gemini-2.5-pro-tts",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(1.25),
        "Gemini 2.5 Pro TTS input (approx.)",
    ),
    (
        "gemini-2.5-pro-tts",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(20.00),
        "Gemini 2.5 Pro Preview TTS audio output $/1M",
    ),
    (
        "lyria-002",
        GenAIUnitType.AUDIO_CLIP.value,
        _usd(0.06),
        "Lyria 2 ~$0.06 per 30s clip (closest public rate)",
    ),
]

# Additional rows for preview/lite/omni IDs used by the app but absent from the
# first seed pass. Kept separate so existing databases can apply a follow-up
# migration without re-running the initial seed.
EXTRA_UNIT_PRICES: list[tuple[str, str, Decimal, str]] = [
    (
        "gemini-2.5-flash-image-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.30),
        "Gemini 2.5 Flash Image preview input",
    ),
    (
        "gemini-2.5-flash-image-preview",
        GenAIUnitType.IMAGE.value,
        _usd(0.039),
        "Gemini 2.5 Flash Image preview output",
    ),
    (
        "gemini-3.1-flash-image-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Gemini 3.1 Flash Image preview input",
    ),
    (
        "gemini-3.1-flash-image-preview",
        GenAIUnitType.IMAGE.value,
        _usd(0.067),
        "Gemini 3.1 Flash Image preview output",
    ),
    (
        "gemini-3-pro-image-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(2.00),
        "Gemini 3 Pro Image preview input",
    ),
    (
        "gemini-3-pro-image-preview",
        GenAIUnitType.IMAGE.value,
        _usd(0.134),
        "Gemini 3 Pro Image preview output",
    ),
    (
        "gemini-3.1-flash-lite-image",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Gemini 3.1 Flash Lite Image input (approx.)",
    ),
    (
        "gemini-3.1-flash-lite-image",
        GenAIUnitType.IMAGE.value,
        _usd(0.067),
        "Gemini 3.1 Flash Lite Image output (approx.)",
    ),
    (
        "gemini-3-pro-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(2.00),
        "Gemini 3 Pro Preview input (approx.)",
    ),
    (
        "gemini-3-pro-preview",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(12.00),
        "Gemini 3 Pro Preview output (approx.)",
    ),
    (
        "gemini-3-flash-preview",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(1.50),
        "Gemini 3 Flash Preview input (approx.)",
    ),
    (
        "gemini-3-flash-preview",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(9.00),
        "Gemini 3 Flash Preview output (approx.)",
    ),
    (
        "gemini-omni-flash-preview",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.10),
        "Gemini Omni Flash video (approx. Veo 3.1 Fast rate)",
    ),
    (
        "gemini-omni-generate-preview",
        GenAIUnitType.VIDEO_SECOND.value,
        _usd(0.40),
        "Gemini Omni video (approx. Veo 3.1 Standard rate)",
    ),
    (
        "chirp_3",
        GenAIUnitType.INPUT_TOKEN.value,
        _per_million(0.50),
        "Chirp 3 TTS input (approx.)",
    ),
    (
        "chirp_3",
        GenAIUnitType.OUTPUT_TOKEN.value,
        _per_million(10.00),
        "Chirp 3 TTS output (approx.)",
    ),
]
