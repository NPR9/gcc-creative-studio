# Copyright 2025 Google LLC
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
"""Tests for Workspace Repository."""

from unittest.mock import MagicMock

import pytest

from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMemberAssociation,
    WorkspaceRoleEnum,
    WorkspaceTypeEnum,
)


@pytest.fixture(name="workspace_repo")
def fixture_workspace_repo(db_session_mock):
    return WorkspaceRepository(db=db_session_mock)


class TestWorkspaceRepository:
    @pytest.mark.anyio
    async def test_get_workspace_type_found(self, workspace_repo, db_session_mock):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = "personal"
        db_session_mock.execute.return_value = mock_result

        result = await workspace_repo.get_workspace_type(1)

        assert result == "personal"

    @pytest.mark.anyio
    async def test_is_member_true(self, workspace_repo, db_session_mock):
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        db_session_mock.execute.return_value = mock_result

        assert await workspace_repo.is_member(1, 10) is True

    @pytest.mark.anyio
    async def test_get_system_team_workspace_success(
        self, workspace_repo, db_session_mock
    ):
        import datetime

        from src.workspaces.schema.workspace_model import Workspace

        now = datetime.datetime.now(datetime.UTC)
        mock_result = MagicMock()
        mock_asset = Workspace(
            id=1,
            name="Team",
            owner_id=1,
            type="team",
            created_at=now,
            updated_at=now,
        )
        mock_result.scalar_one_or_none.return_value = mock_asset
        db_session_mock.execute.return_value = mock_result

        response = await workspace_repo.get_system_team_workspace()
        assert response.id == 1
        assert response.name == "Team"

    def test_map_to_schema_normalizes_legacy_member_role(self, workspace_repo):
        import datetime

        now = datetime.datetime.now(datetime.UTC)
        user = MagicMock()
        user.email = "legacy@example.com"
        user.name = "Legacy User"

        workspace = Workspace(
            id=1,
            name="Legacy Team",
            owner_id=1,
            type="public",
            created_at=now,
            updated_at=now,
        )
        workspace.members = [
            WorkspaceMemberAssociation(
                workspace_id=1,
                user_id=2,
                role="owner",
                user=user,
            )
        ]

        mapped = workspace_repo._map_to_schema(workspace)

        assert mapped.type == WorkspaceTypeEnum.TEAM
        assert mapped.members[0].role == WorkspaceRoleEnum.ADMIN
        assert mapped.members[0].email == "legacy@example.com"
