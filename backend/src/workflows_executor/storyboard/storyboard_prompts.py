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

The structure mirrors the studio's house storyboard format: a character
sheet first, then per scene a Type / Context / voiceover / shot list /
visual style block with its numbered frames.
"""

import json
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field

BoardType = Literal["shot_by_shot", "moodboard"]
Revision = Literal["keep", "edit", "redraw", "new"]

# =========================================
# Structured output schema (Gemini response_schema)
# =========================================


class StoryboardCharacter(BaseModel):
    """A recurring person. Gets a character sheet used as frame reference."""

    key: str = Field(description="Short id used by shots, e.g. 'astrid'.")
    name: str
    role: str = Field(description="e.g. Sales rep in Paris.")
    look: str = Field(
        description=(
            "Precise physical description: age, build, face, hair, "
            "glasses, skin tone, distinguishing features."
        ),
    )
    wardrobe: str = Field(description="Outfit worn throughout the film.")


class StoryboardShot(BaseModel):
    """One frame of the board."""

    shot_number: int = Field(description="Running number across the board.")
    shot_type: str = Field(description="Wide, Medium, Close-up, Macro, POV.")
    camera_movement: str = Field(description="Static, Push-in, Pan, Drone.")
    action: str = Field(description="One-line caption of what happens.")
    on_screen_text: str | None = Field(
        default=None,
        description="Super or title copy, if any.",
    )
    characters: list[str] = Field(
        default_factory=list,
        description="Keys of characters visible in this frame.",
    )
    needs_real_screenshot: bool = Field(
        default=False,
        description=(
            "True when the frame must show a real product interface; the "
            "central team will insert the real screenshot."
        ),
    )
    visual_prompt: str = Field(
        description=(
            "Self-contained description of this single frame: subject, "
            "setting, composition, lighting. No text or logos."
        ),
    )
    revision: Revision = Field(
        default="new",
        description="Revisions only: keep, edit, redraw or new.",
    )
    source_shot_number: int | None = Field(
        default=None,
        description="Revisions only: the earlier shot this one keeps or edits.",
    )
    edit_instruction: str | None = Field(
        default=None,
        description="Revisions only, for edit: only the change to make.",
    )


class StoryboardScene(BaseModel):
    """A scene in the house format."""

    scene_number: int
    title: str
    scene_type: str = Field(
        description="e.g. Establishing, Product introduction, Payoff.",
    )
    timing: str | None = Field(
        default=None,
        description="Time range from the brief, e.g. '0-15s'.",
    )
    context: str = Field(description="What the scene does in the story.")
    voiceover: list[str] = Field(
        default_factory=list,
        description="Voiceover lines for this scene, verbatim from the brief.",
    )
    visual_style: str
    shots: list[StoryboardShot]


class StoryboardPlan(BaseModel):
    """Full storyboard plan returned by the reasoning model."""

    title: str
    objective: str
    target_audience: str
    channel_and_format: str
    total_duration_seconds: float
    key_message: str
    visual_bible: str = Field(
        description=(
            "Continuity sheet for every frame: locations, products and "
            "packaging, colour palette, lighting mood. Concrete and visual."
        ),
    )
    characters: list[StoryboardCharacter] = Field(default_factory=list)
    assumptions: list[str] = Field(
        description="Every decision taken that the brief did not specify.",
    )
    open_questions: list[str] = Field(
        description="Questions to answer before production. May be empty.",
    )
    scenes: list[StoryboardScene]

    def all_shots(self) -> Iterator[tuple[StoryboardScene, StoryboardShot]]:
        for scene in self.scenes:
            for shot in scene.shots:
                yield scene, shot

    def shot_count(self) -> int:
        return sum(len(scene.shots) for scene in self.scenes)

    def cap_and_renumber(self, max_frames: int) -> None:
        """Enforce the frame budget and renumber shots 1..N in order."""
        remaining = max_frames
        kept_scenes = []
        for scene in self.scenes:
            if remaining <= 0:
                break
            scene.shots = scene.shots[:remaining]
            remaining -= len(scene.shots)
            if scene.shots:
                kept_scenes.append(scene)
        self.scenes = kept_scenes
        number = 0
        for scene_index, scene in enumerate(self.scenes, start=1):
            scene.scene_number = scene_index
            for shot in scene.shots:
                number += 1
                shot.shot_number = number


# =========================================
# Planning prompt
# =========================================

_PLANNER_PROMPT = """\
You are a senior creative director and storyboard artist in a brand's
in-house creative studio. Country marketing managers send you a video brief.
It may be a one-line idea or a full script with voiceover, scene breakdowns,
timings and messaging pillars. Turn it into a storyboard plan the central
creative team can work from.

Script fidelity (most important):
- If the brief contains voiceover lines, copy them VERBATIM into the
  `voiceover` of the scene they belong to. Never rewrite, shorten or
  "improve" the client's script. Keep the brief's scene order, scene titles
  and timings when it has them.
- If the brief has bracketed or described visual directions, turn those
  into shots; do not replace them with your own ideas.
- Only when the brief is a short idea with no script, write a concise
  voiceover yourself and say so in `assumptions`.

Plan in this order:
1. Extract objective, audience, channel and format, duration, key message,
   mandatory elements. Record every default you choose in `assumptions`.
   Never invent prices, dates, offers, legal claims or product names: add
   them to `open_questions` and use placeholders like [PRICE].
2. Characters: list every person who appears in more than one shot, with a
   precise `look` and `wardrobe`. These become character sheets, so be
   specific (age, hair, glasses, outfit colours). Reference them by `key` in
   each shot's `characters`. If a recurring person is not described in the
   brief, design one that fits the audience and note it in `assumptions`.
3. Write the `visual_bible` (locations, products, palette, light).
4. Scenes, in the house format: title, `scene_type`, timing, context,
   voiceover, `visual_style`, then the shots.
{board_rules}
Frame budget: at most {max_frames} shots in total. If the script needs more,
keep one strong shot per key beat and list the merged beats in
`assumptions`. Spend the budget evenly; do not use it all on early scenes.

Rules for every shot:
- `visual_prompt` describes ONE photographable frame: who, where, framing,
  camera angle, light. It must work on its own without the other shots.
- Never put words, captions, logos, brand names, signage text or UI text in
  `visual_prompt`. Brand logos are placed later by the central team. Text
  belongs in `on_screen_text`.
- No real celebrities, no identifiable public figures, no third-party brands
  (airlines, car makers, sponsors, competitors). Real cities and landmarks
  are fine.
- When a shot must show a real product interface (an app, a website, a
  dashboard of a named product), set `needs_real_screenshot` true and
  describe the device with its screen softly lit and blank.
- Write captions, voiceover, assumptions and questions in {language}; write
  `visual_prompt`, `look`, `wardrobe` and `visual_bible` in English.
- Leave `revision`, `source_shot_number` and `edit_instruction` at defaults.
{brand_context_block}"""

_SHOT_BY_SHOT_RULES = """\
Board type: shot by shot. Each scene gets 2 to 8 shots that tell the scene
in order, like a film. Vary framing (wide, medium, close-up) and keep
continuity of people, wardrobe and location inside a scene.
"""

_MOODBOARD_RULES = """\
Board type: mood board. Make one scene per voiceover line or beat of the
script, in order, with that line as the scene's voiceover. Each scene's
shots are {options} DIFFERENT visual options for the same line (different
places, angles, moods), so the team can pick a look. They are alternatives,
not a sequence.
"""


def build_system_prompt(
    *,
    language: str,
    max_frames: int,
    board_type: BoardType,
    options_per_beat: int,
    brand_context: str | None,
) -> str:
    board_rules = (
        _MOODBOARD_RULES.format(options=options_per_beat)
        if board_type == "moodboard"
        else _SHOT_BY_SHOT_RULES
    )
    return _PLANNER_PROMPT.format(
        language=language,
        max_frames=max_frames,
        board_rules=board_rules,
        brand_context_block=_brand_block(brand_context),
    )


def _brand_block(brand_context: str | None) -> str:
    if brand_context and brand_context.strip():
        return (
            "\nBrand context supplied by the studio (follow it):\n"
            f"{brand_context.strip()}\n"
        )
    return ""


def build_user_prompt(
    brief: str, aspect_ratio: str, has_references: bool
) -> str:
    refs = (
        "Reference images are attached after this message. Treat them as "
        "the source of truth for products, people and places."
        if has_references
        else "No reference images were provided."
    )
    return (
        f'Video brief from the country team:\n"""\n{brief.strip()}\n"""\n\n'
        f"Frame aspect ratio: {aspect_ratio}.\n{refs}\n"
        "Return the storyboard plan."
    )


# =========================================
# Revisions: the model returns only the changes; code applies them
# =========================================


class ShotChange(BaseModel):
    """One requested change to the board."""

    op: Literal["edit", "redraw", "remove", "add_after"] = Field(
        description=(
            "edit: small visual change to an existing frame; redraw: same "
            "beat, new picture; remove: drop the shot; add_after: insert a "
            "new shot after shot_number (0 = at the very start)."
        ),
    )
    shot_number: int = Field(description="Current number of the shot.")
    edit_instruction: str | None = Field(
        default=None,
        description="edit only: the change, e.g. 'Make it night'.",
    )
    shot: StoryboardShot | None = Field(
        default=None,
        description="redraw and add_after: the full new shot.",
    )


class VoiceoverChange(BaseModel):
    scene_number: int
    voiceover: list[str]


class StoryboardRevision(BaseModel):
    """Only what the notes ask to change."""

    changes: list[ShotChange] = Field(default_factory=list)
    character_changes: list[StoryboardCharacter] = Field(
        default_factory=list,
        description="Characters whose look or wardrobe the notes change.",
    )
    voiceover_changes: list[VoiceoverChange] = Field(default_factory=list)
    new_assumptions: list[str] = Field(default_factory=list)
    new_open_questions: list[str] = Field(default_factory=list)


REVISION_SYSTEM_PROMPT = """\
You revise an existing storyboard. You get the current plan as JSON and the
requester's change notes (some notes name frames as "Frame 3: ...").
Return ONLY the changes the notes ask for, as a list of operations:
- edit: a small visual change to an existing frame (lighting, an object
  added or removed, expression, time of day, colour, camera distance).
  Write `edit_instruction` with ONLY the change.
- redraw: same beat, substantially different picture. Give the full new
  `shot` (keep its shot_number).
- remove: drop the shot.
- add_after: a new shot inserted after `shot_number` (0 = at the start).
  Give the full new `shot`.
A note about a whole scene applies to every shot in that scene.
If the notes change a character's look or wardrobe, put the updated
character in `character_changes`; its shots are redrawn automatically.
Change the voiceover only when the notes ask; then give the scene's full
new voiceover lines. Never touch what the notes do not mention.
Same rules as before: no words, logos or brands in visual prompts; captions
in {language}, visual prompts in English.
{brand_context_block}"""


def build_revision_prompts(
    *,
    current_plan: dict,
    change_notes: str,
    language: str,
    brand_context: str | None,
) -> tuple[str, str]:
    system = REVISION_SYSTEM_PROMPT.format(
        language=language,
        brand_context_block=_brand_block(brand_context),
    )
    user = (
        "Current storyboard plan:\n"
        f"{json.dumps(current_plan, ensure_ascii=False)}\n\n"
        f'Change notes from the requester:\n"""\n{change_notes.strip()}\n"""\n'
        "Return only the changes."
    )
    return system, user


def apply_revision(
    plan: StoryboardPlan, revision: StoryboardRevision
) -> StoryboardPlan:
    """Applies the changes deterministically and marks each shot's revision.

    Untouched shots become `keep`, so the model cannot silently rewrite
    parts of the board the requester did not mention.
    """
    result = plan.model_copy(deep=True)
    by_number = {shot.shot_number: shot for _, shot in result.all_shots()}
    changed_keys = {c.key for c in revision.character_changes}

    for _, shot in result.all_shots():
        shot.revision = "keep"
        shot.source_shot_number = shot.shot_number
        shot.edit_instruction = None
        if changed_keys.intersection(shot.characters):
            shot.revision = "redraw"

    removed: set[int] = set()
    inserts: dict[int, list[StoryboardShot]] = {}
    for change in revision.changes:
        target = by_number.get(change.shot_number)
        if change.op == "add_after" and change.shot:
            new_shot = change.shot.model_copy()
            new_shot.revision = "new"
            new_shot.source_shot_number = None
            inserts.setdefault(change.shot_number, []).append(new_shot)
        elif target is None:
            continue
        elif change.op == "remove":
            removed.add(change.shot_number)
        elif change.op == "edit" and target.revision != "redraw":
            target.revision = "edit"
            target.edit_instruction = change.edit_instruction
        elif change.op in ("redraw", "edit"):
            if change.shot:
                for name in StoryboardShot.model_fields:
                    if name not in ("shot_number", "revision"):
                        setattr(target, name, getattr(change.shot, name))
            target.revision = "redraw"
            target.source_shot_number = change.shot_number

    for scene in result.scenes:
        rebuilt: list[StoryboardShot] = []
        if scene is result.scenes[0]:
            rebuilt.extend(inserts.get(0, []))
        for shot in scene.shots:
            original = shot.source_shot_number
            if original not in removed:
                rebuilt.append(shot)
            rebuilt.extend(inserts.get(original, []))
        scene.shots = rebuilt
    result.scenes = [scene for scene in result.scenes if scene.shots]

    characters = {c.key: c for c in result.characters}
    for character in revision.character_changes:
        characters[character.key] = character
    result.characters = list(characters.values())
    for vo in revision.voiceover_changes:
        for scene in result.scenes:
            if scene.scene_number == vo.scene_number:
                scene.voiceover = vo.voiceover
    result.assumptions = result.assumptions + revision.new_assumptions
    result.open_questions = result.open_questions + revision.new_open_questions
    return result


# =========================================
# Image prompts
# =========================================

FRAME_STYLE_PREFIXES: dict[str, str] = {
    "photo_previz": (
        "Photorealistic cinematic film still, shot on a cinema camera, "
        "natural and motivated lighting, realistic people and materials, "
        "storyboard reference quality."
    ),
    "rough_color": (
        "Storyboard frame, loose hand-drawn illustration with flat marker "
        "colours, clear silhouettes, readable composition, previz quality."
    ),
    "sketch": (
        "Storyboard frame, loose pencil and grey marker sketch on white paper, "
        "clean confident linework, simple tonal shading, no colour."
    ),
}

DEFAULT_FRAME_STYLE = "photo_previz"

_NO_TEXT_RULE = (
    "Do not render any text, letters, captions, subtitles, logos, brand "
    "marks, signage text, user-interface text, watermarks, panel borders or "
    "frame numbers."
)


def build_character_sheet_prompt(
    character: StoryboardCharacter, style: str
) -> str:
    prefix = FRAME_STYLE_PREFIXES.get(
        style, FRAME_STYLE_PREFIXES[DEFAULT_FRAME_STYLE]
    )
    return (
        f"{prefix}\n"
        f"Character reference sheet for a film: {character.name}, "
        f"{character.role}. Look: {character.look}. "
        f"Wardrobe: {character.wardrobe}.\n"
        "Layout on a plain light grey studio background: full-body "
        "turnaround in front, three-quarter, side and back views, plus a "
        "row of head-and-shoulder close-ups showing neutral, smiling, "
        "focused and concerned expressions. The same face, hair and outfit "
        "in every view.\n"
        f"{_NO_TEXT_RULE}"
    )


def build_frame_prompt(
    shot: StoryboardShot,
    scene: StoryboardScene,
    plan: StoryboardPlan,
    style: str,
    has_character_refs: bool,
) -> str:
    prefix = FRAME_STYLE_PREFIXES.get(
        style, FRAME_STYLE_PREFIXES[DEFAULT_FRAME_STYLE]
    )
    parts = [
        prefix,
        f"Scene: {scene.title}. {shot.shot_type}, camera: "
        f"{shot.camera_movement}.",
        f"Frame: {shot.visual_prompt}",
        f"Scene look: {scene.visual_style}",
        f"Continuity for the whole film: {plan.visual_bible}",
    ]
    if has_character_refs:
        parts.append(
            "The attached character reference sheets show the people in this "
            "frame. They must look exactly like the reference: same face, "
            "hair, glasses and wardrobe."
        )
    if shot.needs_real_screenshot:
        parts.append(
            "Any device screen in the frame is softly lit and blank; the real "
            "product interface is inserted later."
        )
    parts.append(_NO_TEXT_RULE)
    return "\n".join(parts)


def build_edit_prompt(shot: StoryboardShot) -> str:
    instruction = shot.edit_instruction or shot.visual_prompt
    return (
        f"Edit this storyboard frame: {instruction}\n"
        "Keep everything else exactly the same: composition, people, "
        "wardrobe, lighting and style.\n"
        f"{_NO_TEXT_RULE}"
    )


# =========================================
# Human-readable board (text output)
# =========================================


def render_storyboard_text(
    plan: StoryboardPlan,
    frame_ids: dict[int, int | None],
) -> str:
    """Plain-text board in the house format, for the panel and for Jira."""
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
    if plan.characters:
        lines.append("CHARACTERS:")
        lines.extend(
            f"  - {c.name} ({c.role}): {c.look}; {c.wardrobe}"
            for c in plan.characters
        )
        lines.append("")

    for scene in plan.scenes:
        timing = f" ({scene.timing})" if scene.timing else ""
        lines.append(f"SCENE {scene.scene_number}: {scene.title}{timing}")
        lines.append(f"  Type: {scene.scene_type}")
        lines.append(f"  Context: {scene.context}")
        if scene.voiceover:
            lines.append("  VO:")
            lines.extend(f"    {line}" for line in scene.voiceover)
        lines.append(f"  Visual style: {scene.visual_style}")
        lines.append("  Shots:")
        for shot in scene.shots:
            frame = frame_ids.get(shot.shot_number)
            label = f"image #{frame}" if frame else "image FAILED"
            flag = (
                " [USE REAL SCREENSHOT]" if shot.needs_real_screenshot else ""
            )
            lines.append(
                f"    {shot.shot_number}. {shot.shot_type}, "
                f"{shot.camera_movement}: {shot.action}{flag} ({label})"
            )
            if shot.on_screen_text:
                lines.append(f"       On screen: {shot.on_screen_text}")
        lines.append("")
    return "\n".join(lines).rstrip()
