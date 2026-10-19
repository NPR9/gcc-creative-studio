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
"""Prompts for the creative workflow steps.

Kept in one place so they can be tuned (or tested in AI Studio) without
touching execution code.
"""

PRODUCT_IN_SCENE_PROMPT = """\
Place the exact product from the reference image into this scene: {scene}

Hard rules for the product:
- Reproduce the packaging exactly: same shape, colours, logo, brand name,
  product name, claims, weights and every other piece of printed text.
- Do not translate, rewrite, re-letter, blur or invent any label text.
- Do not add other branded products, competitor products, prices or text.
- Keep the product sharp, correctly scaled and naturally lit by the scene.

Make the scene photorealistic and credible for a professional wholesale
customer (restaurant, hotel, café or retail business)."""

PRODUCT_IN_SCENE_RETRY_SUFFIX = """

A previous attempt changed the packaging. These differences must not happen
again: {differences}. Keep the product exactly as in the reference image;
change only the surroundings."""

FIDELITY_CHECK_PROMPT = """\
You are checking packaging fidelity for a retail brand.
Image 1 is the original product packshot. Image 2 is a generated scene that
should contain the same product unchanged.

1. Read all text printed on the product packaging in image 1.
2. Read all text printed on the product packaging in image 2.
3. Compare brand name, product name, claims, quantities, logo and dominant
   pack colours.

Ignore text that is not on the product itself. Small differences in
perspective, lighting or partial occlusion by the scene are acceptable if
every visible word is still correct.

Answer with JSON only:
{
  "passed": true or false,
  "product_visible": true or false,
  "original_label_text": "...",
  "generated_label_text": "...",
  "differences": ["each concrete difference, empty if none"]
}"""

ASSET_RECOMPOSE_PROMPT = """\
Recompose this exact advertising visual for a {ratio} {orientation} canvas.

- Keep the same products, people, colours, lighting and style.
- Extend or rebalance the background naturally; never crop or distort the
  main product.
- Keep the {text_area} calm and uncluttered: text will be added there later.
- Do not add any text, letters, numbers, logos, watermarks or price tags."""


def orientation_for(ratio: str) -> str:
    w, h = (float(x) for x in ratio.split(":"))
    if w > h:
        return "landscape"
    if h > w:
        return "portrait"
    return "square"


def text_area_for(ratio: str) -> str:
    w, h = (float(x) for x in ratio.split(":"))
    if w / h >= 3:
        return "left third of the canvas"
    return "bottom third of the canvas"
