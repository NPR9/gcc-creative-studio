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

"""backfill personal workspaces for users without membership

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    orphan_users = conn.execute(
        sa.text(
            """
            SELECT u.id, u.email
            FROM users u
            WHERE u.deleted_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM workspace_members wm WHERE wm.user_id = u.id
              )
            """
        )
    ).fetchall()

    for user_id, email in orphan_users:
        ws_name = email.strip().lower()
        existing = conn.execute(
            sa.text("SELECT id FROM workspaces WHERE name = :name"),
            {"name": ws_name},
        ).fetchone()

        if existing:
            ws_id = existing[0]
        else:
            ws_id = conn.execute(
                sa.text(
                    """
                    INSERT INTO workspaces (name, owner_id, type)
                    VALUES (:name, :owner_id, 'personal')
                    RETURNING id
                    """
                ),
                {"name": ws_name, "owner_id": user_id},
            ).fetchone()[0]

        conn.execute(
            sa.text(
                """
                INSERT INTO workspace_members (workspace_id, user_id, role)
                VALUES (:ws_id, :user_id, 'admin')
                ON CONFLICT DO NOTHING
                """
            ),
            {"ws_id": ws_id, "user_id": user_id},
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO workspace_members (workspace_id, user_id, role)
            SELECT w.id, w.owner_id, 'admin'
            FROM workspaces w
            WHERE w.type = 'team'
              AND NOT EXISTS (
                SELECT 1 FROM workspace_members wm
                WHERE wm.workspace_id = w.id AND wm.user_id = w.owner_id
              )
            """
        )
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported for personal workspace backfill"
    )
