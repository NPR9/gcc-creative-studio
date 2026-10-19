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
"""Executor for the Product-in-Scene and Asset Multiplication steps.

Both steps reuse the backend's existing image job API
(/api/images/generate-images) for generation, so model access, brand
guidelines, GCS storage and the gallery behave exactly as for Edit Image.
"""

import asyncio
import json
import logging

from fastapi import HTTPException
from google.genai import types

from src.common.base_dto import GenerationModelEnum
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.workflows_executor.creative import image_ops
from src.workflows_executor.creative.prompts import (
    ASSET_RECOMPOSE_PROMPT,
    FIDELITY_CHECK_PROMPT,
    PRODUCT_IN_SCENE_PROMPT,
    PRODUCT_IN_SCENE_RETRY_SUFFIX,
    orientation_for,
    text_area_for,
)
from src.workflows_executor.creative.size_library import (
    group_by_generation_ratio,
    load_size_library,
)
from src.workflows_executor.dto.workflows_executor_dto import (
    AssetMultiplicationRequest,
    ProductInSceneRequest,
)
from src.workflows_executor.workflows_executor_service import (
    WorkflowsExecutorService,
)

logger = logging.getLogger(__name__)


def _require_text(value, field_name: str, required: bool = True) -> str | None:
    """Inputs arrive resolved by Cloud Workflows, so refs are strings now."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise HTTPException(
                status_code=400, detail=f"'{field_name}' is required"
            )
        return None
    if not isinstance(value, str):
        raise HTTPException(
            status_code=400,
            detail=f"'{field_name}' must be text, got {type(value).__name__}",
        )
    return value.strip()


def parse_fidelity_report(raw: str | None) -> dict:
    """Parse the model's JSON verdict; anything unreadable counts as a fail."""
    fallback = {
        "passed": False,
        "product_visible": False,
        "original_label_text": "",
        "generated_label_text": "",
        "differences": ["Fidelity check returned an unreadable answer"],
    }
    if not raw:
        return fallback
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, TypeError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    differences = data.get("differences") or []
    if not isinstance(differences, list):
        differences = [str(differences)]
    product_visible = bool(data.get("product_visible", True))
    return {
        # A pass needs the product to be visible and no reported differences.
        "passed": bool(data.get("passed"))
        and product_visible
        and not differences,
        "product_visible": product_visible,
        "original_label_text": str(data.get("original_label_text", "")),
        "generated_label_text": str(data.get("generated_label_text", "")),
        "differences": [str(d) for d in differences],
    }


def allowed_ratios_for(model: str) -> list[str] | None:
    """Aspect ratios the backend accepts for this model (None if unknown)."""
    try:
        return [r.value for r in GenerationModelEnum(model).valid_aspect_ratios]
    except ValueError:
        return None


def render_resolution_for(model: str, quality: str) -> str:
    """Previews stay at 1K; finals render at 2K so a 1080x1920 output is
    never upscaled. Nano Banana 2 Lite only supports 1K."""
    # Plain string, not the enum member: older code versions lack Lite.
    if quality == "final" and "flash-lite-image" not in model:
        return "2K"
    return "1K"


class CreativeStepsService(WorkflowsExecutorService):
    """Runs the Product-in-Scene and Asset Multiplication workflow steps."""

    def __init__(self):
        super().__init__()
        self._gcs: GcsService | None = None

    @property
    def gcs(self) -> GcsService:
        if self._gcs is None:
            self._gcs = GcsService()
        return self._gcs

    @staticmethod
    def _headers(authorization: str | None) -> dict:
        return {"Authorization": authorization} if authorization else {}

    async def _submit_image_job(
        self,
        *,
        workspace_id: int,
        prompt: str,
        model: str,
        aspect_ratio: str,
        media_items: list,
        asset_ids: list,
        brand_guidelines: bool,
        resolution: str = "1K",
        authorization: str | None = None,
    ) -> int:
        body = {
            "prompt": prompt,
            "workspace_id": workspace_id,
            "generation_model": model,
            "aspect_ratio": aspect_ratio,
            "use_brand_guidelines": brand_guidelines,
            "number_of_media": 1,
            "source_media_items": media_items,
            "source_asset_ids": asset_ids,
            "resolution": resolution,
        }
        response = await self.rest_client.post(
            self.backend_url + "/api/images/generate-images",
            json=body,
            headers=self._headers(authorization),
        )
        if response.status_code != 200:
            logger.error("Backend error: %s", response.text)
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Backend error: {response.text}",
            )
        media_id = response.json().get("id")
        if not media_id:
            raise HTTPException(status_code=500, detail="Couldn't create image")
        await self._poll_job_status(media_id, authorization)
        return media_id

    async def _media_item_uri(
        self, media_id: int, index: int = 0, authorization: str | None = None
    ) -> tuple[str, str]:
        response = await self.rest_client.get(
            f"{self.backend_url}/api/gallery/item/{media_id}",
            headers=self._headers(authorization),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Could not load media item {media_id}: {response.text}",
            )
        data = response.json()
        uris = data.get("gcsUris") or data.get("gcs_uris") or []
        if not 0 <= index < len(uris):
            raise HTTPException(
                status_code=500, detail=f"Media item {media_id} has no file"
            )
        mime = data.get("mimeType") or data.get("mime_type") or "image/png"
        return uris[index], mime

    async def _asset_uri(
        self, asset_id: int, authorization: str | None = None
    ) -> tuple[str, str]:
        response = await self.rest_client.get(
            f"{self.backend_url}/api/source_assets/{asset_id}",
            headers=self._headers(authorization),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=(
                    f"Could not load source asset {asset_id}: {response.text}"
                ),
            )
        data = response.json()
        uri = data.get("gcsUri") or data.get("gcs_uri")
        if not uri:
            raise HTTPException(
                status_code=500, detail=f"Source asset {asset_id} has no file"
            )
        mime = data.get("mimeType") or data.get("mime_type") or "image/png"
        return uri, mime

    async def _first_input_uri(
        self, inputs, authorization: str | None = None
    ) -> tuple[str, str]:
        media_items, asset_ids = self._normalize_asset_inputs(inputs)
        if media_items:
            item = media_items[0]
            return await self._media_item_uri(
                item["media_item_id"], item["media_index"], authorization
            )
        if asset_ids:
            return await self._asset_uri(asset_ids[0], authorization)
        raise HTTPException(status_code=400, detail="No input image provided")

    async def _download(self, gcs_uri: str) -> bytes:
        data = await asyncio.to_thread(
            self.gcs.download_bytes_from_gcs, gcs_uri
        )
        if not data:
            raise HTTPException(
                status_code=500, detail=f"Could not download {gcs_uri}"
            )
        return data

    async def _upload_png(
        self,
        *,
        workspace_id: int,
        data: bytes,
        filename: str,
        title: str,
        authorization: str | None = None,
    ) -> int:
        response = await self.rest_client.post(
            self.backend_url + "/api/source_assets/upload",
            files={"file": (filename, data, "image/png")},
            data={"workspaceId": str(workspace_id), "title": title},
            headers=self._headers(authorization),
        )
        if response.status_code not in (200, 201):
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Upload of {filename} failed: {response.text}",
            )
        asset_id = response.json().get("id")
        if not asset_id:
            raise HTTPException(
                status_code=500, detail=f"Upload of {filename} failed"
            )
        return asset_id

    async def _check_fidelity(
        self,
        original: tuple[str, str],
        generated: tuple[str, str],
        model: str,
    ) -> dict:
        contents = [
            types.Part.from_uri(file_uri=original[0], mime_type=original[1]),
            types.Part.from_uri(file_uri=generated[0], mime_type=generated[1]),
            types.Part.from_text(text=FIDELITY_CHECK_PROMPT),
        ]
        try:
            response = await asyncio.to_thread(
                self.genai_client.models.generate_content,
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            raw = response.text
        # The check must never crash the run: any failure is a "fail" verdict.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Fidelity check failed: %s", e)
            raw = None
        return parse_fidelity_report(raw)

    # ------------------------------------------------------------------
    # Product in Scene
    # ------------------------------------------------------------------
    async def product_in_scene(
        self, request: ProductInSceneRequest, authorization: str | None = None
    ):
        logger.info("Product in scene execution")
        cfg = request.config
        scene = _require_text(request.inputs.scene_prompt, "scene_prompt")
        media_items, asset_ids = self._normalize_asset_inputs(
            request.inputs.product_image
        )
        if not media_items and not asset_ids:
            raise HTTPException(
                status_code=400, detail="A product image is required"
            )
        original = await self._first_input_uri(
            request.inputs.product_image, authorization
        )

        base_prompt = PRODUCT_IN_SCENE_PROMPT.format(scene=scene)
        prompt = base_prompt
        attempts = []
        for attempt in range(1, cfg.max_attempts + 1):
            media_id = await self._submit_image_job(
                workspace_id=request.workspace_id,
                prompt=prompt,
                model=cfg.model,
                aspect_ratio=cfg.aspect_ratio,
                media_items=media_items,
                asset_ids=asset_ids,
                brand_guidelines=cfg.brand_guidelines,
                resolution=cfg.resolution,
                authorization=authorization,
            )
            generated = await self._media_item_uri(media_id, 0, authorization)
            report = await self._check_fidelity(
                original, generated, cfg.fidelity_model
            )
            attempts.append(
                {"attempt": attempt, "media_id": media_id, **report}
            )
            logger.info(
                "Product in scene attempt %s: passed=%s",
                attempt,
                report["passed"],
            )
            if report["passed"]:
                break
            differences = (
                "; ".join(report["differences"]) or "label text changed"
            )
            prompt = base_prompt + PRODUCT_IN_SCENE_RETRY_SUFFIX.format(
                differences=differences
            )

        final = attempts[-1]
        return {
            "generated_image": final["media_id"],
            "fidelity_passed": final["passed"],
            "needs_review": not final["passed"],
            "attempts": len(attempts),
            "fidelity_report": json.dumps(attempts, ensure_ascii=False),
        }

    # ------------------------------------------------------------------
    # Asset Multiplication
    # ------------------------------------------------------------------
    async def asset_multiplication(
        self,
        request: AssetMultiplicationRequest,
        authorization: str | None = None,
    ):
        logger.info("Asset multiplication execution")
        cfg = request.config
        library = load_size_library(
            config_service.ASSET_MULTIPLICATION_SIZE_LIBRARY_PATH or None
        )
        try:
            preset = library.preset(cfg.channel_preset)
            sizes = library.select(cfg.channel_preset, cfg.sizes)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not sizes:
            raise HTTPException(
                status_code=400,
                detail=f"No sizes selected for preset '{cfg.channel_preset}'",
            )

        headline = _require_text(
            request.inputs.headline, "headline", required=False
        )
        cta_text = _require_text(
            request.inputs.cta_text, "cta_text", required=False
        )
        use_cta = preset.cta if cfg.cta == "auto" else cfg.cta == "on"
        warnings = []
        if use_cta and not cta_text:
            warnings.append(
                "CTA required for this channel but no cta_text given"
            )

        media_items, asset_ids = self._normalize_asset_inputs(
            request.inputs.master_image
        )
        if not media_items and not asset_ids:
            raise HTTPException(
                status_code=400, detail="A master image is required"
            )

        model = (
            config_service.ASSET_MULTIPLICATION_PREVIEW_MODEL
            if cfg.quality == "preview"
            else cfg.final_model
        )
        resolution = render_resolution_for(model, cfg.quality)
        groups = group_by_generation_ratio(sizes, allowed_ratios_for(model))

        async def render(ratio: str) -> tuple[str, int]:
            prompt = ASSET_RECOMPOSE_PROMPT.format(
                ratio=ratio,
                orientation=orientation_for(ratio),
                text_area=text_area_for(ratio),
            )
            media_id = await self._submit_image_job(
                workspace_id=request.workspace_id,
                prompt=prompt,
                model=model,
                aspect_ratio=ratio,
                media_items=media_items,
                asset_ids=asset_ids,
                brand_guidelines=cfg.brand_guidelines,
                resolution=resolution,
                authorization=authorization,
            )
            return ratio, media_id

        renders = dict(await asyncio.gather(*(render(r) for r in groups)))

        logo = None
        if request.inputs.logo_image:
            logo_uri, _ = await self._first_input_uri(
                request.inputs.logo_image, authorization
            )
            logo = image_ops.open_image(await self._download(logo_uri))

        overlay = image_ops.OverlayText(
            headline=headline, cta=cta_text if use_cta else None
        )
        font_path = config_service.ASSET_MULTIPLICATION_FONT_PATH or None

        async def finish(ratio: str, media_id: int) -> list[dict]:
            uri, _ = await self._media_item_uri(media_id, 0, authorization)
            base = image_ops.open_image(await self._download(uri))
            results = []
            for size in groups[ratio]:
                sized = image_ops.crop_and_resize(base, size.width, size.height)
                final = image_ops.apply_overlay(
                    sized, size, overlay, logo, font_path
                )
                filename = f"{cfg.channel_preset}_{size.id}.png"
                asset_id = await self._upload_png(
                    workspace_id=request.workspace_id,
                    data=image_ops.to_png_bytes(final),
                    filename=filename,
                    title=f"{preset.label} {size.name}",
                    authorization=authorization,
                )
                results.append(
                    {
                        "size_id": size.id,
                        "width": size.width,
                        "height": size.height,
                        "generated_at": ratio,
                        "render_media_id": media_id,
                        "asset_id": asset_id,
                        "cta_applied": bool(overlay.cta),
                    }
                )
            return results

        finished = await asyncio.gather(
            *(finish(ratio, media_id) for ratio, media_id in renders.items())
        )
        manifest = [entry for group in finished for entry in group]
        order = {size.id: i for i, size in enumerate(sizes)}
        manifest.sort(key=lambda e: order[e["size_id"]])

        return {
            "images": [
                {"previewUrl": "", "sourceAssetId": e["asset_id"]}
                for e in manifest
            ],
            "renders": list(renders.values()),
            "quality": cfg.quality,
            "model": model,
            "resolution": resolution,
            "manifest": json.dumps(
                {
                    "channel": cfg.channel_preset,
                    "sizes": manifest,
                    "warnings": warnings,
                },
                ensure_ascii=False,
            ),
        }
