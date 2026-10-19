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
"""One-command live smoke test for the Product-in-Scene and Asset
Multiplication steps.

Calls the executor endpoints directly against a running backend, with real
models, so it checks model access, GCS, uploads and output shape in one go.
Run it once in a dev project after deploying; it costs about 6 image
generations.

    uv run python scripts/smoke_creative_steps.py \\
        --backend-url https://<backend-host> \\
        --token "$(gcloud auth print-identity-token)" \\
        --workspace-id 1 \\
        --product-asset-id <source asset id of a packshot> \\
        --master-asset-id <source asset id of a campaign visual>
"""

import argparse
import json
import sys
import time

import httpx


def call(client: httpx.Client, url: str, body: dict) -> dict:
    started = time.monotonic()
    response = client.post(url, json=body)
    elapsed = time.monotonic() - started
    print(f"  HTTP {response.status_code} in {elapsed:.0f}s")
    if response.status_code != 200:
        print(response.text)
        sys.exit(1)
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--token", required=True, help="Bearer token")
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--product-asset-id", type=int, required=True)
    parser.add_argument("--master-asset-id", type=int, required=True)
    args = parser.parse_args()

    base = args.backend_url.rstrip("/") + "/api/workflows-executor"
    headers = {"Authorization": f"Bearer {args.token}"}
    failures = []

    with httpx.Client(headers=headers, timeout=1800) as client:
        print("1/2 Product in Scene")
        result = call(
            client,
            f"{base}/product_in_scene",
            {
                "workspace_id": args.workspace_id,
                "inputs": {
                    "product_image": {
                        "previewUrl": "",
                        "sourceAssetId": args.product_asset_id,
                    },
                    "scene_prompt": "On a wooden counter in a busy Italian "
                    "pizzeria kitchen, warm evening light",
                },
                "config": {"max_attempts": 2},
            },
        )
        print(
            f"  image={result['generated_image']} "
            f"passed={result['fidelity_passed']} attempts={result['attempts']}"
        )
        for attempt in json.loads(result["fidelity_report"]):
            print(f"  attempt {attempt['attempt']}: {attempt['differences']}")
        if not isinstance(result.get("generated_image"), int):
            failures.append("product_in_scene returned no image")

        print("2/2 Asset Multiplication (pmax, preview)")
        result = call(
            client,
            f"{base}/asset_multiplication",
            {
                "workspace_id": args.workspace_id,
                "inputs": {
                    "master_image": {
                        "previewUrl": "",
                        "sourceAssetId": args.master_asset_id,
                    },
                    "headline": "Prodotti essenziali, sempre convenienti",
                    "cta_text": "Scopri di più",
                },
                "config": {"channel_preset": "pmax", "quality": "preview"},
            },
        )
        manifest = json.loads(result["manifest"])
        for size in manifest["sizes"]:
            print(
                f"  {size['size_id']}: {size['width']}x{size['height']} "
                f"from {size['generated_at']} -> asset {size['asset_id']}"
            )
        if len(manifest["sizes"]) != 4:
            failures.append("asset_multiplication did not return 4 sizes")
        if manifest["warnings"]:
            failures.append(f"warnings: {manifest['warnings']}")

    if failures:
        print("FAILED:", "; ".join(failures))
        sys.exit(1)
    print("OK. Open the asset ids above in the Studio to check them by eye.")


if __name__ == "__main__":
    main()
