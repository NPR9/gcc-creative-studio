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
"""Tests for Workspace Controller."""


from unittest.mock import AsyncMock

import pytest
from fastapi import status

from main import app
from src.workspaces.schema.workspace_model import WorkspaceModel
from src.workspaces.workspace_service import WorkspaceService


@pytest.fixture(name="mock_workspace_service")
def fixture_mock_workspace_service():
    """Provides a mocked WorkspaceService."""
    return AsyncMock()


@pytest.fixture(name="override_workspace_service", autouse=True)
def fixture_override_workspace_service(mock_workspace_service):
    """Overrides the WorkspaceService dependency in the app."""
    app.dependency_overrides[WorkspaceService] = lambda: mock_workspace_service
    yield
    if WorkspaceService in app.dependency_overrides:
        del app.dependency_overrides[WorkspaceService]


class TestCreateWorkspace:
    """Tests for POST /api/workspaces."""

    def test_create_workspace_success(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        mock_workspace = WorkspaceModel(
            id=1,
            name="My Workspace",
            owner_id=mock_user.id,
        )
        mock_workspace_service.create_workspace.return_value = mock_workspace
        mock_workspace_service.check_workspace_name_exists.return_value = False

        response = api_client.post(
            "/api/workspaces", json={"name": "My Workspace"}
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "My Workspace"
        assert data["id"] == 1

    def test_create_workspace_duplicate_name_fails(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        """Test that creating a workspace with an existing name returns 409 CONFLICT."""
        mock_workspace_service.check_workspace_name_exists.return_value = True

        response = api_client.post(
            "/api/workspaces", json={"name": "Existing Workspace"}
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        data = response.json()
        assert "Workspace name taken" in data["detail"]
        # Verify create_workspace was NOT called
        mock_workspace_service.create_workspace.assert_not_called()


class TestListMyWorkspaces:
    """Tests for GET /api/workspaces."""

    def test_list_my_workspaces_success(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        workspace = WorkspaceModel(id=1, name="Work 1", owner_id=mock_user.id)
        mock_workspace_service.list_workspaces_for_user.return_value = [
            workspace
        ]

        response = api_client.get("/api/workspaces")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Work 1"

    def test_list_workspace_switcher_workspaces_success(
        self,
        api_client,
        mock_workspace_service,
        mock_user,
    ):
        workspace = WorkspaceModel(
            id=2,
            name="Private Switcher",
            owner_id=mock_user.id,
        )
        mock_workspace_service.list_switcher_workspaces_for_user.return_value = [
            workspace
        ]

        response = api_client.get("/api/workspaces/switcher")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Private Switcher"


class TestInviteUser:
    """Tests for POST /api/workspaces/{id}/invites."""

    def test_invite_user_success(
        self, api_client, mock_workspace_service, mock_user
    ):
        workspace = WorkspaceModel(id=1, name="Work 1", owner_id=mock_user.id)
        mock_workspace_service.invite_user_to_workspace.return_value = workspace

        response = api_client.post(
            "/api/workspaces/1/invites",
            json={
                "email": "guest@example.com",
                "role": "viewer",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == 1

    def test_invite_user_not_found(self, api_client, mock_workspace_service):
        mock_workspace_service.invite_user_to_workspace.return_value = None

        response = api_client.post(
            "/api/workspaces/1/invites",
            json={
                "email": "unknown@example.com",
                "role": "viewer",
            },
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert (
            "Workspace or user to invite not found" in response.json()["detail"]
        )
