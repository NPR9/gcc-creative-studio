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

"""remove legacy Default Group Workspace from groups era

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-30 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_DEFAULT_GROUP_WORKSPACE = "Default Group Workspace"


def _delete_workspace_and_dependencies(conn, workspace_id: int) -> None:
    conn.execute(
        sa.text(
            """
            UPDATE media_items
            SET source_media_item_id = NULL
            WHERE source_media_item_id IN (
                SELECT id FROM media_items WHERE workspace_id = :workspace_id
            )
            """
        ),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text(
            "DELETE FROM media_items WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text(
            "DELETE FROM source_assets WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text(
            "DELETE FROM brand_guidelines WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text("DELETE FROM tags WHERE workspace_id = :workspace_id"),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text(
            "DELETE FROM workspace_members WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )
    conn.execute(
        sa.text("DELETE FROM workspaces WHERE id = :workspace_id"),
        {"workspace_id": workspace_id},
    )


def upgrade() -> None:
    conn = op.get_bind()
    legacy_workspace = conn.execute(
        sa.text("SELECT id FROM workspaces WHERE name = :name"),
        {"name": LEGACY_DEFAULT_GROUP_WORKSPACE},
    ).fetchone()

    if legacy_workspace:
        _delete_workspace_and_dependencies(conn, legacy_workspace[0])


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported for legacy default group workspace removal"
    )
