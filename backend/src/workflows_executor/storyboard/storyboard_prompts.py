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

"""Prompts, output schema and render helpers for the Storyboard workflow step.

Kept separate from the executor service so prompts can be tuned (and
reviewed) without touching orchestration code.
"""

from pydantic import BaseModel, Field

# =========================================
# Structured output schema (Gemini response_schema)
# =========================================


class StoryboardShot(BaseModel):
    """One frame / beat of the storyboard."""

    shot_number: int = Field(description="1-based order of the shot.")
    beat: str = Field(
        description=(
            "Narrative role of the shot, e.g. Hook, Problem, Product, "
            "Benefit, Proof, Call to action."
        ),
    )
    duration_seconds: float = Field(description="Planned screen time.")
    shot_type: str = Field(
        description="Framing: Wide, Medium, Close-up, Macro, Over-shoulder.",
    )
    camera_movement: str = Field(
        description="Static, Slow push-in, Pan left, Handheld, Top-down.",
    )
    action: str = Field(
        description="What happens in the shot, in plain words.",
    )
    on_screen_text: str | None = Field(
        default=None,
        description="Super / title card copy, if any.",
    )
    voiceover: str | None = Field(
        default=None,
        description="Voiceover or dialogue line, if any.",
    )
    sound_notes: str | None = Field(
        default=None,
        description="Music / SFX direction, if any.",
    )
    visual_prompt: str = Field(
        description=(
            "Self-contained image-generation description of this single "
            "frame: subject, setting, composition, lighting. No text in image."
        ),
    )


class StoryboardPlan(BaseModel):
    """Full storyboard plan returned by the reasoning model."""

    title: str
    objective: str = Field(description="What the video must achieve.")
    target_audience: str
    channel_and_format: str = Field(
        description="Where it runs and how, e.g. Instagram Reels 9:16, 15s.",
    )
    total_duration_seconds: float
    key_message: str
    visual_bible: str = Field(
        description=(
            "Continuity sheet applied to every frame: recurring characters "
            "(age, look, wardrobe), locations, products and packaging, colour "
            "palette, lighting mood. Concrete and visual."
        ),
    )
    assumptions: list[str] = Field(
        description="Every decision taken that the brief did not specify.",
    )
    open_questions: list[str] = Field(
        description=(
            "Questions the requester must answer before production. "
            "Empty list if none."
        ),
    )
    shots: list[StoryboardShot]


# =========================================
# Reasoning prompt
# =========================================

STORYBOARD_SYSTEM_PROMPT = """\
You are a senior creative director and storyboard artist working inside a
brand's in-house creative studio. Country marketing managers come to you with
short, informal descriptions of a video they want. Your job is to turn that
description into a production-ready storyboard plan that the central creative
team can execute without a follow-up meeting.

Work in this order:
1. Extract the brief: objective, audience, channel, format, duration, key
   message, mandatory elements (products, offers, legal lines, logos, dates).
2. Fill gaps with sensible defaults for the channel, and record EVERY default
   you chose in `assumptions`. Never silently invent offers, prices, dates,
   legal claims or product names. If one of those is needed but missing,
   add it to `open_questions` and use a clear placeholder like [PRICE] in
   on-screen text.
3. Write a `visual_bible` first, then the shots. Every shot must be visually
   consistent with the bible: same people, same wardrobe, same products, same
   location look, same palette.
4. Structure the shots as a story with a clear hook in the first 2 seconds,
   one key message, and an explicit call to action at the end. Shot durations
   must add up to `total_duration_seconds`.
5. Write each `visual_prompt` as a single frame an illustrator could draw:
   who/what is in frame, where, composition and camera angle, lighting.
   Do not put any words, captions, logos or UI inside the visual_prompt;
   text belongs in `on_screen_text`.

Rules:
- Number of shots: between {min_frames} and {max_frames}, unless the brief
  explicitly asks for a different number.
- Write `action`, `on_screen_text`, `voiceover`, `assumptions` and
  `open_questions` in {language}. Write `visual_prompt` and `visual_bible`
  in English (they feed the image model).
- Avoid real, identifiable people, celebrities, and third-party brands or
  logos unless the brief supplies them as reference images.
- If reference images are attached, treat them as the source of truth for
  products, packaging, people and locations, and describe them precisely in
  the visual bible.
- Be concise. This is a working document, not a pitch.
{brand_context_block}"""


def build_system_prompt(
    *,
    language: str,
    min_frames: int,
    max_frames: int,
    brand_context: str | None,
) -> str:
    brand_context_block = ""
    if brand_context and brand_context.strip():
        brand_context_block = (
            "\nBrand context supplied by the studio (follow it):\n"
            f"{brand_context.strip()}\n"
        )
    return STORYBOARD_SYSTEM_PROMPT.format(
        language=language,
        min_frames=min_frames,
        max_frames=max_frames,
        brand_context_block=brand_context_block,
    )


def build_user_prompt(
    brief: str, aspect_ratio: str, has_references: bool
) -> str:
    refs = (
        "Reference images are attached after this message."
        if has_references
        else "No reference images were provided."
    )
    return (
        f'Video request from the country team:\n"""\n{brief.strip()}\n"""\n\n'
        f"Frame aspect ratio for the storyboard: {aspect_ratio}.\n{refs}\n"
        "Return the storyboard plan."
    )


# =========================================
# Frame (image) prompt
# =========================================

FRAME_STYLE_PREFIXES: dict[str, str] = {
    "sketch": (
        "Storyboard frame, loose pencil and grey marker sketch on white paper, "
        "clean confident linework, simple tonal shading, no colour."
    ),
    "rough_color": (
        "Storyboard frame, loose hand-drawn illustration with flat marker "
        "colours, clear silhouettes, readable composition, previz quality."
    ),
    "photo_previz": (
        "Photographic previsualisation frame, natural lighting, realistic but "
        "unpolished, like a reference still from a location scout."
    ),
}

DEFAULT_FRAME_STYLE = "rough_color"


def build_frame_prompt(
    shot: StoryboardShot,
    plan: StoryboardPlan,
    style: str,
) -> str:
    prefix = FRAME_STYLE_PREFIXES.get(
        style, FRAME_STYLE_PREFIXES[DEFAULT_FRAME_STYLE]
    )
    return (
        f"{prefix}\n"
        f"Frame {shot.shot_number} of {len(plan.shots)}. "
        f"{shot.shot_type}, camera: {shot.camera_movement}.\n"
        f"Scene: {shot.visual_prompt}\n"
        f"Continuity, keep identical across all frames: {plan.visual_bible}\n"
        "Do not render any text, letters, captions, subtitles, logos, "
        "watermarks, panel borders or frame numbers in the image."
    )


# =========================================
# Human-readable board (text output)
# =========================================


def render_storyboard_text(
    plan: StoryboardPlan,
    frame_ids: dict[int, int | None],
) -> str:
    """Plain-text board for the execution panel and for pasting into Jira."""
    lines: list[str] = [
        f"STORYBOARD: {plan.title}",
        f"Objective: {plan.objective}",
        f"Audience: {plan.target_audience}",
        f"Channel / format: {plan.channel_and_format}",
        f"Duration: {plan.total_duration_seconds:g}s",
        f"Key message: {plan.key_message}",
        "",
    ]
    if plan.open_questions:
        lines.append("OPEN QUESTIONS (answer before production):")
        lines.extend(f"  - {q}" for q in plan.open_questions)
        lines.append("")
    if plan.assumptions:
        lines.append("ASSUMPTIONS MADE (correct if wrong):")
        lines.extend(f"  - {a}" for a in plan.assumptions)
        lines.append("")

    for shot in plan.shots:
        frame = frame_ids.get(shot.shot_number)
        frame_label = f"image #{frame}" if frame else "image FAILED"
        lines.append(
            f"[{shot.shot_number}] {shot.beat} | {shot.duration_seconds:g}s | "
            f"{shot.shot_type}, {shot.camera_movement} | {frame_label}"
        )
        lines.append(f"    Action: {shot.action}")
        if shot.on_screen_text:
            lines.append(f"    On screen: {shot.on_screen_text}")
        if shot.voiceover:
            lines.append(f"    VO: {shot.voiceover}")
        if shot.sound_notes:
            lines.append(f"    Sound: {shot.sound_notes}")
    return "\n".join(lines)
