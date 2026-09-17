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

import logging
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status

from src.admin.repository.admin_repository import AdminRepository
from src.admin.dto.admin_response_dto import (
    AdminOverviewStats,
    AdminMediaOverTime,
    AdminWorkspaceStats,
    AdminActiveRole,
    AdminGenerationHealth,
    AdminMonthlyActiveUsers,
    AddUserByEmailResponse,
    UserProvisioningStatus,
)
from src.users.user_model import UserModel
from src.users.user_service import UserService
from src.workspaces.workspace_service import WorkspaceService
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.workspaces.schema.workspace_model import (
    WorkspaceMember,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceTypeEnum,
)


class AdminService:
    def __init__(
        self,
        admin_repo: AdminRepository = Depends(),
        user_service: UserService = Depends(),
        workspace_service: WorkspaceService = Depends(),
    ):
        self.admin_repo = admin_repo
        self.user_service = user_service
        self.workspace_service = workspace_service
        self.logger = logging.getLogger(__name__)

    async def get_overview_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> AdminOverviewStats:
        return await self.admin_repo.get_overview_stats(start_date, end_date)

    async def get_media_over_time(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminMediaOverTime]:
        return await self.admin_repo.get_media_over_time(start_date, end_date)

    async def get_workspace_stats(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminWorkspaceStats]:
        return await self.admin_repo.get_workspace_stats(start_date, end_date)

    async def get_active_roles(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminActiveRole]:
        return await self.admin_repo.get_active_roles(start_date, end_date)

    async def get_generation_health(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminGenerationHealth]:
        return await self.admin_repo.get_generation_health(start_date, end_date)

    async def get_active_users_monthly(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[AdminMonthlyActiveUsers]:
        result_dict = await self.admin_repo.get_active_users_monthly_counts(
            start_date, end_date
        )

        if start_date and end_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(day=1)
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_dt = datetime.today()
            start_dt = (end_dt - timedelta(days=180)).replace(day=1)

        months = []
        curr_dt = start_dt
        while curr_dt <= end_dt:
            months.append(curr_dt.strftime("%Y-%m"))
            if curr_dt.month == 12:
                curr_dt = curr_dt.replace(year=curr_dt.year + 1, month=1)
            else:
                curr_dt = curr_dt.replace(month=curr_dt.month + 1)

        months = sorted(list(set(months)))

        return [
            AdminMonthlyActiveUsers(month=m, count=result_dict.get(m, 0))
            for m in months
        ]

    async def cleanup_stuck_jobs(self) -> int:
        return await self.admin_repo.cleanup_stuck_jobs()

    async def get_all_workspaces(self) -> list[WorkspaceModel]:
        """Gets all workspaces with members (admin view)."""
        return await self.workspace_service.list_all_workspaces_admin()

    async def create_team_workspace_admin(
        self,
        name: str,
        admin_user: UserModel,
    ) -> WorkspaceModel:
        """Creates a new team workspace."""
        if await self.workspace_service.check_workspace_name_exists(name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Workspace name already exists.",
            )
        team_dto = CreateWorkspaceDto(name=name, type=WorkspaceTypeEnum.TEAM)
        return await self.workspace_service.create_workspace(admin_user, team_dto)

    async def add_user_to_workspace(
        self,
        workspace_id: int,
        user_id: int,
        role: str,
        admin_user: UserModel,
    ) -> WorkspaceModel:
        """Adds an existing user to a workspace."""
        workspace = await self.workspace_service.workspace_repo.get_by_id(
            workspace_id
        )
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found.")

        user = await self.user_service.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

        member_role = (
            WorkspaceRoleEnum.ADMIN
            if role == WorkspaceRoleEnum.ADMIN.value
            else WorkspaceRoleEnum.USER
        )
        member = WorkspaceMember(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=member_role,
        )
        # A user may belong to at most one shared (team) workspace.
        if workspace.type == WorkspaceTypeEnum.TEAM:
            await self.workspace_service.remove_from_other_team_workspaces(
                user.id, workspace_id
            )
        updated = await self.workspace_service.workspace_repo.add_member_to_workspace(
            workspace_id, member, user.id
        )
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to add member.")
        return updated

    async def add_admin_user_by_email(
        self,
        email: str,
        admin_user: UserModel,
    ) -> AddUserByEmailResponse:
        """Creates/gets a user by email and grants platform admin access."""
        user, provisioning_status = (
            await self.user_service.create_or_restore_user_by_email_for_admin(email)
        )
        user = await self.user_service.ensure_user_is_platform_admin(user.id)
        await self.workspace_service.add_user_to_admin_workspace(user)
        personal_workspace = await self.workspace_service.ensure_personal_workspace(
            user
        )

        return AddUserByEmailResponse(
            provisioning_status=UserProvisioningStatus(provisioning_status),
            created_new_user=provisioning_status == "created",
            user_id=user.id,
            email=user.email,
            workspace=personal_workspace,
        )

    async def add_user_to_workspace_by_email(
        self,
        workspace_id: int,
        email: str,
        admin_user: UserModel,
    ) -> AddUserByEmailResponse:
        """Creates/gets a user by email and assigns them to a team workspace."""
        user, provisioning_status = (
            await self.user_service.create_or_restore_user_by_email_for_admin(email)
        )

        workspace = await self.workspace_service.workspace_repo.get_by_id(
            workspace_id
        )
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found.")

        if not await self.workspace_service.workspace_repo.is_member(
            workspace_id, user.id
        ):
            member = WorkspaceMember(
                user_id=user.id,
                email=user.email,
                name=user.name,
                role=WorkspaceRoleEnum.USER,
            )
            # A user may belong to at most one shared (team) workspace.
            if workspace.type == WorkspaceTypeEnum.TEAM:
                await self.workspace_service.remove_from_other_team_workspaces(
                    user.id, workspace_id
                )
            await self.workspace_service.workspace_repo.add_member_to_workspace(
                workspace_id, member, user.id
            )

        await self.workspace_service.ensure_personal_workspace(user)

        updated_workspace = await self.workspace_service.workspace_repo.get_by_id(
            workspace_id
        )
        return AddUserByEmailResponse(
            provisioning_status=UserProvisioningStatus(provisioning_status),
            created_new_user=provisioning_status == "created",
            user_id=user.id,
            email=user.email,
            workspace=updated_workspace,
        )

    async def cleanup_invalid_personal_workspaces(self) -> int:
        """Removes personal workspaces whose name is not the owner's email."""
        deleted_count = await self.workspace_service.cleanup_invalid_personal_workspaces()
        if deleted_count:
            self.logger.info(
                "Removed %d invalid personal workspace(s).", deleted_count
            )
        return deleted_count

    async def update_workspace_member_role(
        self,
        workspace_id: int,
        user_id: int,
        role: str,
    ) -> WorkspaceModel:
        """Updates a workspace member's role."""
        member_role = (
            WorkspaceRoleEnum.ADMIN.value
            if role == WorkspaceRoleEnum.ADMIN.value
            else WorkspaceRoleEnum.USER.value
        )
        updated = await self.workspace_service.workspace_repo.update_member_role(
            workspace_id, user_id, member_role
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Member not found.")
        return updated

    async def remove_user_from_workspace(
        self,
        workspace_id: int,
        user_id: int,
    ) -> dict:
        """Removes a user from a workspace."""
        removed = await self.workspace_service.workspace_repo.remove_member_from_workspace(
            workspace_id, user_id
        )
        if not removed:
            raise HTTPException(status_code=404, detail="Member not found.")
        return {"message": "Member removed successfully"}

    async def delete_team_workspace_admin(self, workspace_id: int) -> bool:
        """Deletes a team workspace."""
        workspace = await self.workspace_service.workspace_repo.get_by_id(
            workspace_id
        )
        if not workspace:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )
        if workspace.type != WorkspaceTypeEnum.TEAM:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only team workspaces can be deleted from admin.",
            )

        deleted = await self.workspace_service.workspace_repo.delete_team_workspace(
            workspace_id
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete team workspace.",
            )
        return True

    async def reset_dev_database(self) -> dict:
        """DEV ONLY: Truncates all application data tables for fresh start."""
        from sqlalchemy import text

        tables_to_truncate = [
            "workspace_members",
            "workspace_usage_daily",
            "workspaces",
            "media_items",
            "media_templates",
            "images",
            "videos",
            "audios",
            "projects",
            "workflows",
            "workflows_executor",
            "galleries",
            "tags",
            "brand_guidelines",
            "source_assets",
            "users",
        ]

        truncated_count = 0
        errors = []

        for table in tables_to_truncate:
            try:
                await self.admin_repo.db.execute(
                    text(f"TRUNCATE TABLE {table} CASCADE")
                )
                truncated_count += 1
            except Exception as e:
                errors.append(f"{table}: {str(e)}")

        await self.admin_repo.db.commit()

        return {
            "status": "success" if truncated_count == len(tables_to_truncate) else "partial",
            "tables_truncated": truncated_count,
            "total_tables": len(tables_to_truncate),
            "errors": errors,
            "message": "Dev database reset complete.",
        }
