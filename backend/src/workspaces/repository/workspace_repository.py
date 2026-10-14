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


from fastapi import Depends
from sqlalchemy import delete, exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.base_repository import BaseRepository
from src.database import get_db
from src.users.user_model import User
from src.workspaces.schema.workspace_model import (
    Workspace,
    WorkspaceMember,
    WorkspaceMemberAssociation,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceTypeEnum,
)


class WorkspaceRepository(BaseRepository[Workspace, WorkspaceModel]):
    """Repository for all database operations related to the 'workspaces' table."""

    def __init__(self, db: AsyncSession = Depends(get_db)):
        """Initializes the repository."""
        super().__init__(model=Workspace, schema=WorkspaceModel, db=db)

    async def get_system_team_workspace(self) -> WorkspaceModel | None:
        """Finds the first team workspace (used for templates/bootstrap assets)."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.type == WorkspaceTypeEnum.TEAM.value)
            .limit(1),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return None
        return self._map_to_schema(workspace)

    async def get_admin_workspace(self) -> WorkspaceModel | None:
        """Finds the single shared admin workspace, if it exists."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.type == WorkspaceTypeEnum.ADMIN.value)
            .limit(1),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return None
        return self._map_to_schema(workspace)

    async def create(
        self,
        schema: WorkspaceModel,
        initial_members: list[WorkspaceMember] = [],
    ) -> WorkspaceModel:
        """Creates a new workspace and handles the members association manually."""
        data = schema.model_dump(exclude_unset=True, exclude={"members"})
        if data.get("id") is None:
            data.pop("id", None)

        db_item = self.model(**data)

        for member in initial_members:
            association = WorkspaceMemberAssociation(
                user_id=member.user_id,
                role=member.role.value if hasattr(member.role, "value") else member.role,
            )
            db_item.members.append(association)

        self.db.add(db_item)
        await self.db.commit()
        await self.db.refresh(db_item)

        return self._map_to_schema(db_item)

    async def add_member_to_workspace(
        self,
        workspace_id: int,
        member: WorkspaceMember,
        user_id: int,
    ) -> WorkspaceModel | None:
        """Atomically adds a new member to a workspace's members list."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == workspace_id),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return None

        existing_member = next(
            (m for m in workspace.members if m.user_id == user_id),
            None,
        )

        if not existing_member:
            new_association = WorkspaceMemberAssociation(
                workspace_id=workspace_id,
                user_id=user_id,
                role=member.role.value if hasattr(member.role, "value") else member.role,
            )
            workspace.members.append(new_association)
            await self.db.commit()
            await self.db.refresh(workspace)

        return self._map_to_schema(workspace)

    async def update_member_role(
        self,
        workspace_id: int,
        user_id: int,
        role: str,
    ) -> WorkspaceModel | None:
        """Updates a member's role in a workspace."""
        result = await self.db.execute(
            select(WorkspaceMemberAssociation).where(
                WorkspaceMemberAssociation.workspace_id == workspace_id,
                WorkspaceMemberAssociation.user_id == user_id,
            ),
        )
        association = result.scalar_one_or_none()
        if not association:
            return None

        association.role = role
        await self.db.commit()
        return await self.get_by_id(workspace_id)

    async def remove_member_from_workspace(
        self,
        workspace_id: int,
        user_id: int,
    ) -> bool:
        """Removes a member from a workspace."""
        result = await self.db.execute(
            select(WorkspaceMemberAssociation).where(
                WorkspaceMemberAssociation.workspace_id == workspace_id,
                WorkspaceMemberAssociation.user_id == user_id,
            ),
        )
        association = result.scalar_one_or_none()
        if not association:
            return False

        await self.db.delete(association)
        await self.db.commit()
        return True

    async def find_by_member_id(self, user_id: int) -> list[WorkspaceModel]:
        """Finds all workspaces where the user is a member."""
        result = await self.db.execute(
            select(self.model)
            .join(WorkspaceMemberAssociation)
            .where(WorkspaceMemberAssociation.user_id == user_id)
            .order_by(self.model.name),
        )
        workspaces = result.scalars().all()
        return [self._map_to_schema(w) for w in workspaces]

    async def find_personal_by_member_id(
        self, user_id: int
    ) -> list[WorkspaceModel]:
        """Finds personal workspaces where the user is a member."""
        result = await self.db.execute(
            select(self.model)
            .join(WorkspaceMemberAssociation)
            .where(
                WorkspaceMemberAssociation.user_id == user_id,
                self.model.type == WorkspaceTypeEnum.PERSONAL.value,
            ),
        )
        workspaces = result.scalars().all()
        return [self._map_to_schema(w) for w in workspaces]

    async def find_team_by_member_id(
        self, user_id: int
    ) -> list[WorkspaceModel]:
        """Finds team workspaces where the user is a member."""
        result = await self.db.execute(
            select(self.model)
            .join(WorkspaceMemberAssociation)
            .where(
                WorkspaceMemberAssociation.user_id == user_id,
                self.model.type == WorkspaceTypeEnum.TEAM.value,
            )
            .order_by(self.model.name),
        )
        workspaces = result.scalars().all()
        return [self._map_to_schema(w) for w in workspaces]

    async def find_all_team(
        self,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[WorkspaceModel]:
        """Finds all team workspaces."""
        result = await self.db.execute(
            select(self.model)
            .where(self.model.type == WorkspaceTypeEnum.TEAM.value)
            .order_by(self.model.name)
            .limit(limit)
            .offset(offset),
        )
        workspaces = result.scalars().all()
        return [self._map_to_schema(w) for w in workspaces]

    async def find_all_team_and_admin(
        self,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[WorkspaceModel]:
        """Finds all team and admin workspaces for the admin management view."""
        result = await self.db.execute(
            select(self.model)
            .where(
                self.model.type.in_(
                    [
                        WorkspaceTypeEnum.TEAM.value,
                        WorkspaceTypeEnum.ADMIN.value,
                    ]
                )
            )
            .order_by(self.model.type, self.model.name)
            .limit(limit)
            .offset(offset),
        )
        workspaces = result.scalars().all()
        return [self._map_to_schema(w) for w in workspaces]

    async def find_personal_for_user(self, user_id: int) -> WorkspaceModel | None:
        """Finds a user's personal workspace by ownership."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.owner_id == user_id,
                self.model.type == WorkspaceTypeEnum.PERSONAL.value,
            ),
        )
        workspace = result.scalar_one_or_none()
        return self._map_to_schema(workspace) if workspace else None

    async def is_member(self, workspace_id: int, user_id: int) -> bool:
        """Checks if a user is a member of a workspace."""
        result = await self.db.execute(
            select(
                exists().where(
                    WorkspaceMemberAssociation.workspace_id == workspace_id,
                    WorkspaceMemberAssociation.user_id == user_id,
                ),
            ),
        )
        return result.scalar()

    async def get_workspace_type(self, workspace_id: int) -> str | None:
        """Retrieves the type of a workspace."""
        result = await self.db.execute(
            select(self.model.type).where(self.model.id == workspace_id),
        )
        return result.scalar_one_or_none()

    async def find_by_name(self, name: str) -> WorkspaceModel | None:
        """Find workspace by name."""
        result = await self.db.execute(
            select(self.model).where(self.model.name == name),
        )
        workspace = result.scalar_one_or_none()
        return self._map_to_schema(workspace) if workspace else None

    async def delete_personal_workspace(self, workspace_id: int) -> bool:
        """Deletes a personal workspace and its workspace-scoped dependencies."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.id == workspace_id,
                self.model.type == WorkspaceTypeEnum.PERSONAL.value,
            ),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return False

        await self._delete_workspace_dependencies(workspace_id)
        await self.db.delete(workspace)
        await self.db.commit()
        return True

    async def find_invalid_personal_workspaces(self) -> list[WorkspaceModel]:
        """Finds personal workspaces whose name is not the owner's email."""
        # Compare in SQL — do not access workspace.owner here; lazy loads fail
        # under AsyncSession (greenlet_spawn / await_only errors).
        result = await self.db.execute(
            select(self.model)
            .join(User, self.model.owner_id == User.id)
            .where(
                self.model.type == WorkspaceTypeEnum.PERSONAL.value,
                func.lower(func.trim(self.model.name))
                != func.lower(func.trim(User.email)),
            ),
        )
        workspaces = result.scalars().all()
        return [
            WorkspaceModel(
                id=workspace.id,
                name=workspace.name,
                owner_id=workspace.owner_id,
                type=WorkspaceTypeEnum.PERSONAL,
            )
            for workspace in workspaces
        ]

    async def delete_team_workspace(self, workspace_id: int) -> bool:
        """Deletes a team workspace and its workspace-scoped dependencies."""
        result = await self.db.execute(
            select(self.model).where(
                self.model.id == workspace_id,
                self.model.type == WorkspaceTypeEnum.TEAM.value,
            ),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return False

        await self._delete_workspace_dependencies(workspace_id)
        await self.db.delete(workspace)
        await self.db.commit()
        return True

    async def _delete_workspace_dependencies(self, workspace_id: int) -> None:
        """Removes rows that reference a workspace before the workspace is deleted."""
        await self.db.execute(
            text(
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
        await self.db.execute(
            delete(WorkspaceMemberAssociation).where(
                WorkspaceMemberAssociation.workspace_id == workspace_id
            )
        )
        for statement in (
            "DELETE FROM media_items WHERE workspace_id = :workspace_id",
            "DELETE FROM source_assets WHERE workspace_id = :workspace_id",
            "DELETE FROM brand_guidelines WHERE workspace_id = :workspace_id",
            "DELETE FROM tags WHERE workspace_id = :workspace_id",
        ):
            await self.db.execute(
                text(statement),
                {"workspace_id": workspace_id},
            )

    async def get_by_id(self, item_id: int) -> WorkspaceModel | None:
        """Gets a workspace by ID with members."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == item_id),
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            return None
        return self._map_to_schema(workspace)

    async def find_all(
        self,
        limit: int = 100,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[WorkspaceModel]:
        """Finds all workspaces with members mapped for API responses."""
        query = (
            select(self.model)
            .order_by(self.model.name)
            .execution_options(include_deleted=include_deleted)
        )
        result = await self.db.execute(query.limit(limit).offset(offset))
        workspaces = result.scalars().all()
        return [self._map_to_schema(workspace) for workspace in workspaces]

    def _normalize_member_role(self, role: str) -> WorkspaceRoleEnum:
        """Maps legacy DB role values to the workspace-only model."""
        if role in {WorkspaceRoleEnum.ADMIN.value, "owner"}:
            return WorkspaceRoleEnum.ADMIN
        return WorkspaceRoleEnum.USER

    def _normalize_workspace_type(self, workspace_type: str) -> WorkspaceTypeEnum:
        """Maps legacy DB workspace type values to personal/team/admin."""
        if workspace_type == WorkspaceTypeEnum.ADMIN.value:
            return WorkspaceTypeEnum.ADMIN
        if workspace_type in {
            WorkspaceTypeEnum.TEAM.value,
            "global",
            "public",
        }:
            return WorkspaceTypeEnum.TEAM
        return WorkspaceTypeEnum.PERSONAL

    def _map_to_schema(self, workspace: Workspace) -> WorkspaceModel:
        """Helper to map SQLAlchemy Workspace to Pydantic WorkspaceModel."""
        members = []
        for member_assoc in workspace.members or []:
            members.append(
                WorkspaceMember(
                    user_id=member_assoc.user_id,
                    email=member_assoc.user.email if member_assoc.user else "unknown",
                    name=member_assoc.user.name if member_assoc.user else None,
                    role=self._normalize_member_role(member_assoc.role),
                )
            )

        workspace_dict = {
            "id": workspace.id,
            "name": workspace.name,
            "owner_id": workspace.owner_id,
            "type": self._normalize_workspace_type(workspace.type),
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "members": members,
        }

        return self.schema.model_validate(workspace_dict)
