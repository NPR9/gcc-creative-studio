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

from src.common.email_service import EmailService
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.workspaces.dto.invite_user_dto import InviteUserDto
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    WorkspaceMember,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceTypeEnum,
)


class WorkspaceService:
    """Handles the business logic for workspace management."""

    def __init__(
        self,
        workspace_repo: WorkspaceRepository = Depends(),
        user_repo: UserRepository = Depends(),
        email_service: EmailService = Depends(),
    ):
        self.workspace_repo = workspace_repo
        self.user_repo = user_repo
        self.email_service = email_service

    async def create_workspace(
        self,
        user: UserModel,
        create_dto: CreateWorkspaceDto,
    ) -> WorkspaceModel:
        """Creates a new workspace with the creator as admin member."""
        if create_dto.type == WorkspaceTypeEnum.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Admin workspaces are provisioned during bootstrap and "
                    "cannot be created via the API."
                ),
            )

        if create_dto.type == WorkspaceTypeEnum.TEAM:
            is_system_admin = UserRoleEnum.ADMIN in user.roles
            if not is_system_admin:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only system admins can create team workspaces.",
                )

        owner_role = WorkspaceRoleEnum.ADMIN
        owner_as_member = WorkspaceMember(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=owner_role,
        )

        new_workspace = WorkspaceModel(
            name=create_dto.name,
            owner_id=user.id,
            type=create_dto.type,
        )
        return await self.workspace_repo.create(
            new_workspace,
            initial_members=[owner_as_member],
        )

    async def ensure_personal_workspace(self, user: UserModel) -> WorkspaceModel:
        """Ensures a user has a personal workspace named after their email."""
        personal_ws_name = user.email.strip().lower()
        existing = await self.workspace_repo.find_by_name(personal_ws_name)
        if existing:
            if not await self.workspace_repo.is_member(existing.id, user.id):
                member = WorkspaceMember(
                    user_id=user.id,
                    email=user.email,
                    name=user.name,
                    role=WorkspaceRoleEnum.ADMIN,
                )
                updated = await self.workspace_repo.add_member_to_workspace(
                    existing.id, member, user.id
                )
                return updated or existing
            return existing

        personal_dto = CreateWorkspaceDto(
            name=personal_ws_name,
            type=WorkspaceTypeEnum.PERSONAL,
        )
        return await self.create_workspace(user, personal_dto)

    async def ensure_admin_workspace(
        self, owner: UserModel, name: str
    ) -> WorkspaceModel:
        """Ensures the single shared admin workspace exists.

        All platform admins are members of this workspace. It is created once
        during bootstrap with ``owner`` as the recorded owner and first member.
        """
        existing = await self.workspace_repo.get_admin_workspace()
        if existing:
            return existing

        owner_member = WorkspaceMember(
            user_id=owner.id,
            email=owner.email,
            name=owner.name,
            role=WorkspaceRoleEnum.ADMIN,
        )
        admin_workspace = WorkspaceModel(
            name=name,
            owner_id=owner.id,
            type=WorkspaceTypeEnum.ADMIN,
        )
        return await self.workspace_repo.create(
            admin_workspace,
            initial_members=[owner_member],
        )

    async def add_user_to_admin_workspace(self, user: UserModel) -> None:
        """Adds an admin user to the shared admin workspace if not already a member."""
        admin_workspace = await self.workspace_repo.get_admin_workspace()
        if not admin_workspace or admin_workspace.id is None:
            return
        if await self.workspace_repo.is_member(admin_workspace.id, user.id):
            return
        member = WorkspaceMember(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=WorkspaceRoleEnum.ADMIN,
        )
        await self.workspace_repo.add_member_to_workspace(
            admin_workspace.id, member, user.id
        )

    async def invite_user_to_workspace(
        self,
        workspace_id: int,
        invite_dto: InviteUserDto,
        current_user: UserModel,
    ) -> WorkspaceModel | None:
        """Invites a user to a workspace by adding them to the members list."""
        workspace = await self.workspace_repo.get_by_id(workspace_id)
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )

        is_system_admin = UserRoleEnum.ADMIN in current_user.roles
        is_workspace_admin = any(
            m.user_id == current_user.id and m.role == WorkspaceRoleEnum.ADMIN
            for m in workspace.members
        )
        is_owner = current_user.id == workspace.owner_id

        if not (is_system_admin or is_workspace_admin or is_owner):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only workspace admins or system admins can invite users.",
            )

        invited_email = invite_dto.email.strip().lower()
        invited_user = await self.user_repo.get_by_email(invited_email)
        if not invited_user:
            return None

        # A user may belong to at most one shared (team) workspace. Assigning
        # them to a new team workspace reassigns them out of any previous one.
        if workspace.type == WorkspaceTypeEnum.TEAM:
            await self.remove_from_other_team_workspaces(
                invited_user.id, workspace_id
            )

        new_member = WorkspaceMember(
            user_id=invited_user.id,
            email=invited_user.email,
            name=invited_user.name,
            role=invite_dto.role,
        )
        updated_workspace = await self.workspace_repo.add_member_to_workspace(
            workspace_id,
            new_member,
            invited_user.id,
        )

        if not updated_workspace:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to add user to workspace.",
            )

        self.email_service.send_workspace_invitation_email(
            recipient_email=invited_user.email,
            inviter_name=current_user.name,
            workspace_name=updated_workspace.name,
            workspace_id=workspace_id,
        )
        return updated_workspace

    async def list_workspaces_for_user(
        self, user: UserModel
    ) -> list[WorkspaceModel]:
        """Returns the workspaces the user is a member of.

        The shared admin workspace is intentionally excluded: admins belong to
        it for permissions only, and it must not appear as a selectable
        workspace in the UI.
        """
        workspaces = await self.workspace_repo.find_by_member_id(user.id)
        return [
            ws for ws in workspaces if ws.type != WorkspaceTypeEnum.ADMIN
        ]

    async def get_assigned_shared_workspace(
        self, user: UserModel
    ) -> WorkspaceModel | None:
        """Returns the single shared (team) workspace the user is assigned to.

        Users are assigned to at most one shared workspace. Returns None when
        the user has not been assigned to any shared workspace yet.
        """
        team_workspaces = await self.workspace_repo.find_team_by_member_id(
            user.id
        )
        return team_workspaces[0] if team_workspaces else None

    async def get_assigned_display_workspace(
        self, user: UserModel
    ) -> WorkspaceModel | None:
        """Returns the workspace to show as the user's assignment in the switcher.

        Admins are members of the shared admin workspace (not a team
        workspace), so for them we surface the admin workspace as their
        assignment. Regular users continue to see their team workspace. This is
        display-only and does not change gallery/asset behavior.
        """
        if UserRoleEnum.ADMIN in user.roles:
            return await self.workspace_repo.get_admin_workspace()
        return await self.get_assigned_shared_workspace(user)

    async def remove_from_other_team_workspaces(
        self, user_id: int, keep_workspace_id: int
    ) -> None:
        """Ensures a user belongs to at most one shared (team) workspace.

        Removes the user from every team workspace except ``keep_workspace_id``.
        """
        existing_team_workspaces = (
            await self.workspace_repo.find_team_by_member_id(user_id)
        )
        for team_ws in existing_team_workspaces:
            if team_ws.id is not None and team_ws.id != keep_workspace_id:
                await self.workspace_repo.remove_member_from_workspace(
                    team_ws.id, user_id
                )

    async def list_switcher_workspaces_for_user(
        self, user: UserModel
    ) -> list[WorkspaceModel]:
        """Returns workspaces for the switcher dropdown (member workspaces only).

        The shared admin workspace is excluded so it is never shown as a
        switchable workspace; admin membership exists purely for permissions.
        """
        workspaces = await self.workspace_repo.find_by_member_id(user.id)
        return [
            ws for ws in workspaces if ws.type != WorkspaceTypeEnum.ADMIN
        ]

    async def list_all_workspaces_admin(self) -> list[WorkspaceModel]:
        """Returns team and admin workspaces for system admin management."""
        return await self.workspace_repo.find_all_team_and_admin(
            limit=1000, offset=0
        )

    async def cleanup_invalid_personal_workspaces(self) -> int:
        """Removes personal workspaces whose name is not the owner's email."""
        invalid_workspaces = (
            await self.workspace_repo.find_invalid_personal_workspaces()
        )
        deleted_count = 0
        for workspace in invalid_workspaces:
            if workspace.id is None:
                continue
            deleted = await self.workspace_repo.delete_personal_workspace(
                workspace.id
            )
            if deleted:
                deleted_count += 1
        return deleted_count

    async def check_workspace_name_exists(self, name: str) -> bool:
        """Check if workspace name already exists globally."""
        existing = await self.workspace_repo.find_by_name(name)
        return existing is not None
