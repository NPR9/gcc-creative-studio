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
"""Tests for the Product-in-Scene and Asset Multiplication executor steps."""

import io
import itertools
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import Response
from PIL import Image

from src.config.config_service import config_service
from src.workflows.schema.workflow_model import (
    AssetMultiplicationInputs,
    AssetMultiplicationSettings,
    ProductInSceneInputs,
    ProductInSceneSettings,
    ReferenceMediaOrAsset,
)
from src.workflows_executor.creative.creative_steps_service import (
    CreativeStepsService,
    parse_fidelity_report,
)
from src.workflows_executor.dto.workflows_executor_dto import (
    AssetMultiplicationRequest,
    ProductInSceneRequest,
)

PASS = json.dumps(
    {
        "passed": True,
        "product_visible": True,
        "original_label_text": "ARO Farina 00",
        "generated_label_text": "ARO Farina 00",
        "differences": [],
    }
)
FAIL = json.dumps(
    {
        "passed": False,
        "product_visible": True,
        "original_label_text": "ARO Farina 00",
        "generated_label_text": "ARO Farlna 0O",
        "differences": ["'Farina' rendered as 'Farlna'"],
    }
)


def _png(w=1344, h=1344):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (180, 120, 60)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(name="service")
def fixture_service():
    with (
        patch(
            "src.workflows_executor.workflows_executor_service.RestClient"
        ) as rest_cls,
        patch(
            "src.workflows_executor.workflows_executor_service.GenAIModelSetup.init"
        ) as genai_init,
    ):
        rest = AsyncMock()
        rest_cls.return_value = rest
        genai = MagicMock()
        genai_init.return_value = genai

        service = CreativeStepsService()
        service.backend_url = "http://backend"
        service._poll_job_status = AsyncMock(return_value=True)

        media_ids = itertools.count(100)
        asset_ids = itertools.count(500)
        service.posts = []

        async def post(url, json=None, files=None, data=None, headers=None):
            service.posts.append(
                {"url": url, "json": json, "files": files, "data": data}
            )
            if url.endswith("/api/images/generate-images"):
                return Response(200, json={"id": next(media_ids)})
            if url.endswith("/api/source_assets/upload"):
                return Response(200, json={"id": next(asset_ids)})
            return Response(404, text="unexpected")

        async def get(url, headers=None):
            if "/api/gallery/item/" in url:
                media_id = url.rsplit("/", 1)[1]
                return Response(
                    200,
                    json={
                        "gcsUris": [f"gs://bucket/{media_id}.png"],
                        "mimeType": "image/png",
                    },
                )
            if "/api/source_assets/" in url:
                asset_id = url.rsplit("/", 1)[1]
                return Response(
                    200,
                    json={
                        "gcsUri": f"gs://bucket/asset-{asset_id}.png",
                        "mimeType": "image/png",
                    },
                )
            return Response(404, text="unexpected")

        rest.post.side_effect = post
        rest.get.side_effect = get

        gcs = MagicMock()
        gcs.download_bytes_from_gcs.side_effect = lambda uri: _png()
        service._gcs = gcs
        service.genai = genai
        yield service


def _verdicts(service, *texts):
    service.genai.models.generate_content.side_effect = [
        MagicMock(text=t) for t in texts
    ]


def _image_posts(service):
    return [p for p in service.posts if p["url"].endswith("/generate-images")]


def _uploads(service):
    return [p for p in service.posts if p["url"].endswith("/upload")]


def _pis_request(**settings):
    return ProductInSceneRequest(
        workspace_id=7,
        inputs=ProductInSceneInputs(
            product_image=ReferenceMediaOrAsset(
                previewUrl="", sourceAssetId=42
            ),
            scene_prompt="On a rustic pizzeria counter",
        ),
        config=ProductInSceneSettings(**settings),
    )


# --- Fidelity report parsing -------------------------------------------------


def test_parse_pass():
    assert parse_fidelity_report(PASS)["passed"] is True


def test_parse_fenced_json():
    assert parse_fidelity_report(f"```json\n{PASS}\n```")["passed"] is True


@pytest.mark.parametrize("raw", [None, "", "not json", "[1, 2]"])
def test_parse_unreadable_is_a_fail(raw):
    report = parse_fidelity_report(raw)
    assert report["passed"] is False
    assert report["differences"]


def test_parse_pass_with_differences_is_a_fail():
    raw = json.dumps({"passed": True, "differences": ["logo colour changed"]})
    assert parse_fidelity_report(raw)["passed"] is False


def test_parse_product_not_visible_is_a_fail():
    raw = json.dumps(
        {"passed": True, "product_visible": False, "differences": []}
    )
    assert parse_fidelity_report(raw)["passed"] is False


# --- Product in Scene --------------------------------------------------------


@pytest.mark.anyio
async def test_product_in_scene_passes_first_time(service):
    _verdicts(service, PASS)
    result = await service.product_in_scene(_pis_request(), "Bearer t")

    assert result["fidelity_passed"] is True
    assert result["needs_review"] is False
    assert result["attempts"] == 1
    posts = _image_posts(service)
    assert len(posts) == 1
    body = posts[0]["json"]
    assert body["source_asset_ids"] == [42]
    assert body["generation_model"] == "gemini-3-pro-image-preview"
    assert "rustic pizzeria counter" in body["prompt"]
    assert "Do not translate, rewrite" in body["prompt"]
    assert result["generated_image"] == 100


@pytest.mark.anyio
async def test_product_in_scene_retries_with_the_differences(service):
    _verdicts(service, FAIL, PASS)
    result = await service.product_in_scene(_pis_request(max_attempts=2))

    assert result["attempts"] == 2
    assert result["fidelity_passed"] is True
    assert result["generated_image"] == 101
    second_prompt = _image_posts(service)[1]["json"]["prompt"]
    assert "'Farina' rendered as 'Farlna'" in second_prompt
    report = json.loads(result["fidelity_report"])
    assert [a["passed"] for a in report] == [False, True]


@pytest.mark.anyio
async def test_product_in_scene_flags_for_review_after_max_attempts(service):
    _verdicts(service, FAIL, FAIL, FAIL)
    result = await service.product_in_scene(_pis_request(max_attempts=3))

    assert result["attempts"] == 3
    assert result["fidelity_passed"] is False
    assert result["needs_review"] is True


@pytest.mark.anyio
async def test_product_in_scene_check_error_counts_as_fail(service):
    service.genai.models.generate_content.side_effect = RuntimeError("quota")
    result = await service.product_in_scene(_pis_request(max_attempts=1))
    assert result["needs_review"] is True


@pytest.mark.anyio
async def test_product_in_scene_compares_original_and_generated(service):
    _verdicts(service, PASS)
    await service.product_in_scene(_pis_request())
    contents = service.genai.models.generate_content.call_args.kwargs[
        "contents"
    ]
    uris = [c.file_data.file_uri for c in contents if c.file_data]
    assert uris == ["gs://bucket/asset-42.png", "gs://bucket/100.png"]


@pytest.mark.anyio
async def test_product_in_scene_requires_scene(service):
    request = _pis_request()
    request.inputs.scene_prompt = "   "
    with pytest.raises(HTTPException) as exc:
        await service.product_in_scene(request)
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_product_in_scene_requires_image(service):
    request = _pis_request()
    request.inputs.product_image = []
    with pytest.raises(HTTPException) as exc:
        await service.product_in_scene(request)
    assert exc.value.status_code == 400


# --- Asset Multiplication ----------------------------------------------------


def _am_request(inputs=None, **settings):
    base_inputs = {
        "master_image": 55,
        "headline": "Prodotti essenziali, sempre convenienti",
        "cta_text": "Scopri di più",
    }
    base_inputs.update(inputs or {})
    return AssetMultiplicationRequest(
        workspace_id=7,
        inputs=AssetMultiplicationInputs(**base_inputs),
        config=AssetMultiplicationSettings(**settings),
    )


@pytest.mark.anyio
async def test_meta_preview_renders_once_per_ratio_with_lite_model(service):
    result = await service.asset_multiplication(_am_request(), "Bearer t")

    renders = _image_posts(service)
    assert sorted(p["json"]["aspect_ratio"] for p in renders) == [
        "16:9",
        "1:1",
        "9:16",
    ]
    assert {p["json"]["generation_model"] for p in renders} == {
        config_service.ASSET_MULTIPLICATION_PREVIEW_MODEL
    }
    assert all(
        p["json"]["source_media_items"][0]["media_item_id"] == 55
        for p in renders
    )
    assert all("Do not add any text" in p["json"]["prompt"] for p in renders)

    manifest = json.loads(result["manifest"])
    assert [s["size_id"] for s in manifest["sizes"]] == [
        "square_1200",
        "landscape_1200x628",
        "vertical_1080x1920",
    ]
    assert not any(s["cta_applied"] for s in manifest["sizes"])  # Meta: no CTA
    assert len(result["images"]) == 3
    assert all("sourceAssetId" in img for img in result["images"])
    assert result["quality"] == "preview"


@pytest.mark.anyio
async def test_uploads_are_exact_pixel_pngs(service):
    await service.asset_multiplication(_am_request())
    sizes = []
    for upload in _uploads(service):
        name, data, mime = upload["files"]["file"]
        assert mime == "image/png"
        assert upload["data"]["workspaceId"] == "7"
        sizes.append((name, Image.open(io.BytesIO(data)).size))
    assert sorted(sizes) == sorted(
        [
            ("meta_square_1200.png", (1200, 1200)),
            ("meta_landscape_1200x628.png", (1200, 628)),
            ("meta_vertical_1080x1920.png", (1080, 1920)),
        ]
    )


@pytest.mark.anyio
async def test_pmax_final_uses_final_model_and_cta(service):
    result = await service.asset_multiplication(
        _am_request(
            channel_preset="pmax",
            quality="final",
            final_model="gemini-3-pro-image-preview",
        )
    )
    assert {p["json"]["generation_model"] for p in _image_posts(service)} == {
        "gemini-3-pro-image-preview"
    }
    manifest = json.loads(result["manifest"])
    assert len(manifest["sizes"]) == 4
    assert all(s["cta_applied"] for s in manifest["sizes"])
    assert manifest["warnings"] == []


@pytest.mark.anyio
async def test_cta_required_but_missing_is_warned_not_failed(service):
    result = await service.asset_multiplication(
        _am_request(inputs={"cta_text": ""}, channel_preset="pmax")
    )
    manifest = json.loads(result["manifest"])
    assert manifest["warnings"]
    assert not any(s["cta_applied"] for s in manifest["sizes"])


@pytest.mark.anyio
async def test_cta_override_off(service):
    result = await service.asset_multiplication(
        _am_request(channel_preset="pmax", cta="off")
    )
    assert not any(
        s["cta_applied"] for s in json.loads(result["manifest"])["sizes"]
    )


@pytest.mark.anyio
async def test_size_override_renders_only_selected(service):
    result = await service.asset_multiplication(
        _am_request(sizes="portrait_960x1200")
    )
    assert [p["json"]["aspect_ratio"] for p in _image_posts(service)] == ["4:5"]
    assert len(result["images"]) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "settings", [{"channel_preset": "tiktok"}, {"sizes": "billboard_99"}]
)
async def test_bad_preset_or_size_is_400(service, settings):
    with pytest.raises(HTTPException) as exc:
        await service.asset_multiplication(_am_request(**settings))
    assert exc.value.status_code == 400
    assert not _image_posts(service)


@pytest.mark.anyio
async def test_logo_is_downloaded_and_used(service):
    await service.asset_multiplication(
        _am_request(
            inputs={
                "logo_image": ReferenceMediaOrAsset(
                    previewUrl="", sourceAssetId=9
                )
            }
        )
    )
    downloaded = [
        c.args[0] for c in service._gcs.download_bytes_from_gcs.call_args_list
    ]
    assert "gs://bucket/asset-9.png" in downloaded


@pytest.mark.anyio
async def test_missing_master_image_is_400(service):
    with pytest.raises(HTTPException) as exc:
        await service.asset_multiplication(
            _am_request(inputs={"master_image": []})
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_backend_error_propagates(service):
    async def failing_post(url, **kwargs):
        return Response(500, text="model unavailable")

    service.rest_client.post.side_effect = failing_post
    with pytest.raises(HTTPException) as exc:
        await service.asset_multiplication(_am_request())
    assert exc.value.status_code == 500


@pytest.mark.anyio
async def test_preview_renders_at_1k_and_final_at_2k(service):
    await service.asset_multiplication(_am_request(sizes="square_1200"))
    assert _image_posts(service)[0]["json"]["resolution"] == "1K"
    service.posts.clear()
    result = await service.asset_multiplication(
        _am_request(sizes="square_1200", quality="final")
    )
    assert _image_posts(service)[0]["json"]["resolution"] == "2K"
    assert result["resolution"] == "2K"


@pytest.mark.anyio
async def test_pro_final_falls_back_to_supported_ratio(service, tmp_path):
    # Nano Banana Pro has no 8:1; a leaderboard must render at 21:9 instead.
    library = tmp_path / "lib.json"
    library.write_text(
        json.dumps(
            {
                "sizes": [
                    {
                        "id": "leader",
                        "width": 728,
                        "height": 90,
                        "channels": ["x"],
                    }
                ],
                "channel_presets": {"x": {"label": "X", "cta": False}},
            }
        )
    )
    with patch(
        "src.workflows_executor.creative.creative_steps_service.config_service"
    ) as cfg:
        cfg.ASSET_MULTIPLICATION_SIZE_LIBRARY_PATH = str(library)
        cfg.ASSET_MULTIPLICATION_PREVIEW_MODEL = (
            config_service.ASSET_MULTIPLICATION_PREVIEW_MODEL
        )
        cfg.ASSET_MULTIPLICATION_FONT_PATH = ""
        await service.asset_multiplication(
            _am_request(
                channel_preset="x",
                quality="final",
                final_model="gemini-3-pro-image-preview",
            )
        )
        assert _image_posts(service)[0]["json"]["aspect_ratio"] == "21:9"
        service.posts.clear()
        await service.asset_multiplication(_am_request(channel_preset="x"))
        assert _image_posts(service)[0]["json"]["aspect_ratio"] == "8:1"
    sizes = [
        Image.open(io.BytesIO(u["files"]["file"][1])).size
        for u in _uploads(service)
    ]
    assert sizes == [(728, 90)]
