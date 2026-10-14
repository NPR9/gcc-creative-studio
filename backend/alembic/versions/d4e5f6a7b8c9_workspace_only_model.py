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

"""workspace-only model: remove groups, rename scope to type

Revision ID: d4e5f6a7b8c9
Revises: m1a2b3c4d5e6
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "m1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Rename scope -> type on workspaces
    op.alter_column("workspaces", "scope", new_column_name="type")

    # Migrate workspace type values
    conn.execute(
        sa.text(
            """
            UPDATE workspaces SET type = 'personal' WHERE type = 'private'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE workspaces SET type = 'team' WHERE type IN ('global', 'public')
            """
        )
    )

    # Migrate workspace member roles
    conn.execute(
        sa.text(
            """
            UPDATE workspace_members SET role = 'admin'
            WHERE role IN ('owner', 'admin')
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE workspace_members SET role = 'user'
            WHERE role IN ('viewer', 'editor', 'member', 'user')
            """
        )
    )

    # Add source_media_item_id for team workspace copies
    op.add_column(
        "media_items",
        sa.Column("source_media_item_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "media_items_source_media_item_id_fkey",
        "media_items",
        "media_items",
        ["source_media_item_id"],
        ["id"],
    )

    # Drop group move provenance columns
    op.drop_index("ix_media_items_moved_to_group_id", table_name="media_items")
    op.drop_constraint(
        "fk_media_items_moved_to_group_id_groups",
        "media_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_media_items_original_workspace_id_workspaces",
        "media_items",
        type_="foreignkey",
    )
    op.drop_column("media_items", "moved_to_group_id")
    op.drop_column("media_items", "original_workspace_id")

    # Drop group tables
    op.drop_index("ix_group_usage_daily_group_id", table_name="group_usage_daily")
    op.drop_index("ix_group_usage_daily_date", table_name="group_usage_daily")
    op.drop_table("group_usage_daily")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("ix_groups_shared_workspace_id", table_name="groups")
    op.drop_table("groups")


def downgrade() -> None:
    raise NotImplementedError("Downgrade not supported for workspace-only migration")
