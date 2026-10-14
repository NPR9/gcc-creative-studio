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


from fastapi import Depends, HTTPException, status

from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    WorkspaceModel,
    WorkspaceTypeEnum,
)


class WorkspaceAuth:
    """A dependency class that centralizes workspace authorization logic."""

    def __init__(self, workspace_repo: WorkspaceRepository = Depends()):
        self.workspace_repo = workspace_repo

    async def authorize(
        self,
        workspace_id: int,
        user: UserModel,
    ) -> WorkspaceModel:
        """Checks if a user has rights to a workspace.

        System admins can access any workspace. Other users must be members.
        """
        workspace_type = await self.workspace_repo.get_workspace_type(workspace_id)

        if workspace_type is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace with ID '{workspace_id}' not found.",
            )

        is_admin = UserRoleEnum.ADMIN in user.roles

        if not is_admin:
            is_member = await self.workspace_repo.is_member(
                workspace_id, user.id
            )
            if not is_member:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You do not have permission to access this workspace.",
                )

        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace with ID '{workspace_id}' not found.",
            )
        return workspace

    async def authorize_personal_workspace(
        self,
        workspace_id: int,
        user: UserModel,
    ) -> WorkspaceModel:
        """Authorizes a generation/upload into the caller's personal workspace.

        Content creation (generation and uploads) is always pinned to the
        caller's own personal workspace, including for system admins. Shared
        (team) workspaces are collect-only and receive assets via sharing.
        """
        workspace = await self.authorize(workspace_id, user)

        is_personal = workspace.type == WorkspaceTypeEnum.PERSONAL
        is_owner = workspace.owner_id == user.id
        if not (is_personal and is_owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Content can only be created in your personal workspace."
                ),
            )
        return workspace
