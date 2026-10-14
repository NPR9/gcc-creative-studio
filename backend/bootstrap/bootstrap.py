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

import asyncio
import logging
import mimetypes
import os

# --- Setup Logging Globally First ---
from src.config.logger_config import setup_logging

setup_logging()

from sqlalchemy.ext.asyncio import AsyncSession

from bootstrap.seed_data import (
    TEMPLATES,
)  # pylint: disable=wrong-import-position
from src.common.base_dto import AspectRatioEnum
from src.common.schema.media_item_model import AssetRoleEnum
from src.common.storage_service import GcsService
from src.config.config_service import config_service
from src.database import async_session_local, cleanup_connector
from src.media_templates.repository.media_template_repository import (
    MediaTemplateRepository,
)
from src.media_templates.schema.media_template_model import (
    GenerationParameters,
    IndustryEnum,
    MediaTemplateModel,
)
from src.source_assets.repository.source_asset_repository import (
    SourceAssetRepository,
)
from src.source_assets.schema.source_asset_model import (
    AssetScopeEnum as AssetScope,
)
from src.source_assets.schema.source_asset_model import (
    AssetTypeEnum as AssetType,
)
from src.source_assets.schema.source_asset_model import SourceAssetModel
from src.common.email_service import EmailService
from src.images.repository.media_item_repository import MediaRepository
from src.users.dto.user_create_dto import UserCreateDto
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.workspaces.dto.create_workspace_dto import CreateWorkspaceDto
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.schema.workspace_model import (
    WorkspaceMember,
    WorkspaceModel,
    WorkspaceRoleEnum,
    WorkspaceTypeEnum,
)
from src.workspaces.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

# Get the absolute path of the directory where this script is located.
# This makes all file paths relative to the script's own location.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Well-known name of the single shared workspace that all platform admins
# belong to. It is looked up by workspace type (ADMIN), so this name is only
# used for display when the workspace is first created.
ADMIN_WORKSPACE_NAME = "Administrators"


def resolve_bootstrap_admin_email() -> str | None:
    """Resolves the email used to seed the first platform admin.

    Priority:
    1. ADMIN_USER_EMAIL when set to a real user (bootstrap.sh sets gcloud account)
    2. First ADMIN_OWNER_EMAILS entry when ADMIN_USER_EMAIL is 'system'
    """
    admin_email = (config_service.ADMIN_USER_EMAIL or "").strip().lower()
    if admin_email and admin_email != "system":
        return admin_email

    owner_emails = sorted(
        email.strip().lower()
        for email in config_service.ADMIN_OWNER_EMAILS
        if email.strip()
    )
    if owner_emails:
        logger.info(
            "Bootstrap running as 'system'. Using owner email: %s",
            owner_emails[0],
        )
        return owner_emails[0]

    logger.warning(
        "No bootstrap admin email configured. Set ADMIN_USER_EMAIL or ADMIN_OWNER_EMAILS."
    )
    return None


def _has_admin_role(roles: list[UserRoleEnum | str]) -> bool:
    return any(
        (role.value if isinstance(role, UserRoleEnum) else str(role)).lower()
        == UserRoleEnum.ADMIN.value
        for role in roles
    )


def build_workspace_service(db: AsyncSession) -> WorkspaceService:
    """Constructs WorkspaceService outside FastAPI dependency injection."""
    workspace_repo = WorkspaceRepository(db)
    return WorkspaceService(
        workspace_repo=workspace_repo,
        user_repo=UserRepository(db),
        email_service=EmailService(),
    )


async def ensure_admin_user_has_admin_role(
    db: AsyncSession,
    admin_user: UserModel,
) -> UserModel:
    """Ensures the bootstrap admin retains the platform admin role."""
    if _has_admin_role(admin_user.roles):
        return admin_user

    user_repo = UserRepository(db)
    updated_roles = [
        role.value if isinstance(role, UserRoleEnum) else str(role)
        for role in admin_user.roles
    ]
    updated_roles.append(UserRoleEnum.ADMIN.value)
    logger.info(
        "Promoting bootstrap admin '%s' to platform admin role.",
        admin_user.email,
    )
    return await user_repo.update(admin_user.id, {"roles": updated_roles})


async def ensure_personal_workspace(
    db: AsyncSession,
    admin_user: UserModel,
) -> None:
    """Ensures the bootstrap admin has a personal workspace."""
    workspace_service = build_workspace_service(db)
    await workspace_service.ensure_personal_workspace(admin_user)
    logger.info(
        "Bootstrap admin personal workspace ensured for '%s'.",
        admin_user.email,
    )


async def ensure_default_team_workspace_exists(
    db: AsyncSession,
    admin_user: UserModel | None,
):
    """Checks if a default team workspace exists and creates one if needed."""
    try:
        logger.info("Checking for default team workspace...")
        workspace_repo = WorkspaceRepository(db)
        if not await workspace_repo.get_system_team_workspace():
            logger.warning("No team workspace found. Creating a default one.")
            if not admin_user:
                logger.error(
                    "Cannot create default team workspace without an admin user."
                )
                return

            project_id = config_service.PROJECT_ID
            workspace_name = (
                project_id.replace("-", " ").replace("_", " ").title()
                + " Workspace"
            )

            owner_member = WorkspaceMember(
                user_id=admin_user.id,
                email=admin_user.email,
                name=admin_user.name,
                role=WorkspaceRoleEnum.ADMIN,
            )
            default_workspace = WorkspaceModel(
                name=workspace_name,
                owner_id=admin_user.id,
                type=WorkspaceTypeEnum.TEAM,
            )
            # The admin is recorded as the owner for referential integrity but
            # is intentionally NOT added as a member: admins must not be able to
            # view the assets of shared/user workspaces.
            _ = owner_member
            await workspace_repo.create(
                default_workspace,
                initial_members=[],
            )
            logger.info(
                f"Default team '{workspace_name}' created successfully."
            )
    except Exception as e:
        logger.error(
            f"Failed to ensure default team workspace exists: {e}", exc_info=True
        )


async def ensure_admin_workspace_exists(
    db: AsyncSession,
    admin_user: UserModel | None,
) -> None:
    """Ensures the shared admin workspace exists, owned by the bootstrap admin."""
    if not admin_user:
        logger.error(
            "Cannot create admin workspace without a bootstrap admin user."
        )
        return
    try:
        workspace_service = build_workspace_service(db)
        await workspace_service.ensure_admin_workspace(
            admin_user, ADMIN_WORKSPACE_NAME
        )
        logger.info("Shared admin workspace ensured.")
    except Exception as e:
        logger.error(
            f"Failed to ensure admin workspace exists: {e}", exc_info=True
        )


async def remove_admins_from_shared_workspaces(db: AsyncSession) -> None:
    """Removes admin users from any team (shared) workspace membership.

    Admins belong only to their personal workspace and the shared admin
    workspace. They must not be members of team/user workspaces so they cannot
    view those workspaces' assets.
    """
    admin_emails = set(config_service.ADMIN_OWNER_EMAILS)
    primary_admin_email = resolve_bootstrap_admin_email()
    if primary_admin_email:
        admin_emails.add(primary_admin_email)
    if not admin_emails:
        return

    user_repo = UserRepository(db)
    workspace_repo = WorkspaceRepository(db)
    for email in sorted(admin_emails):
        user = await user_repo.get_by_email(email)
        if not user:
            continue
        team_workspaces = await workspace_repo.find_team_by_member_id(user.id)
        for team_ws in team_workspaces:
            if team_ws.id is not None:
                await workspace_repo.remove_member_from_workspace(
                    team_ws.id, user.id
                )
                logger.info(
                    "Removed admin '%s' from team workspace '%s'.",
                    email,
                    team_ws.name,
                )


async def cleanup_invalid_personal_workspaces(db: AsyncSession) -> None:
    """Removes personal workspaces that are not named after the owner's email."""
    workspace_service = build_workspace_service(db)
    deleted_count = await workspace_service.cleanup_invalid_personal_workspaces()
    if deleted_count:
        logger.info(
            "Removed %d invalid personal workspace(s) during bootstrap.",
            deleted_count,
        )


async def ensure_bootstrap_admin_workspaces(db: AsyncSession) -> None:
    """Provisions personal workspaces for all configured bootstrap admin emails."""
    admin_emails = set(config_service.ADMIN_OWNER_EMAILS)
    primary_admin_email = resolve_bootstrap_admin_email()
    if primary_admin_email:
        admin_emails.add(primary_admin_email)

    if not admin_emails:
        logger.warning(
            "Skipping bootstrap admin workspace provisioning: no admin emails."
        )
        return

    user_repo = UserRepository(db)
    workspace_service = build_workspace_service(db)
    logger.info("--- Ensuring Bootstrap Admin Workspaces ---")

    for email in sorted(admin_emails):
        user = await user_repo.get_by_email(email)
        if not user:
            logger.info(
                "Admin email '%s' has no user yet; skipping workspace.",
                email,
            )
            continue
        user = await ensure_admin_user_has_admin_role(db, user)
        await workspace_service.ensure_personal_workspace(user)
        await workspace_service.add_user_to_admin_workspace(user)
        logger.info(
            "Bootstrap admin personal + admin workspace ensured for '%s'.",
            email,
        )


async def ensure_admin_user_exists(db: AsyncSession) -> UserModel | None:
    """Ensures user documents exist for all admin owner emails.

    Returns the primary admin user model configured via ADMIN_USER_EMAIL or
    the first ADMIN_OWNER_EMAILS entry when ADMIN_USER_EMAIL is 'system'.
    """
    logger.info("--- Ensuring Admin Users Exist ---")
    primary_admin_email = resolve_bootstrap_admin_email()

    admin_emails = set()
    if config_service.ADMIN_OWNER_EMAILS:
        admin_emails.update(
            email.strip().lower()
            for email in config_service.ADMIN_OWNER_EMAILS
            if email.strip()
        )
    if primary_admin_email:
        admin_emails.add(primary_admin_email)

    if not admin_emails:
        logger.info("No admin user emails configured. Skipping admin user creation.")
        return None

    user_repo = UserRepository(db)
    primary_user = None

    for email_to_create in sorted(admin_emails):
        try:
            logger.info(f"Looking up user for email: {email_to_create}")
            existing_user = await user_repo.get_by_email(email_to_create)

            if existing_user:
                logger.info(
                    f"User document for '{email_to_create}' already exists. ID: {existing_user.id}",
                )
                if (
                    UserRoleEnum.ADMIN not in existing_user.roles
                    and UserRoleEnum.ADMIN.value not in existing_user.roles
                ):
                    updated_roles = list(existing_user.roles)
                    updated_roles.append(UserRoleEnum.ADMIN)
                    existing_user = await user_repo.update(
                        existing_user.id, {"roles": updated_roles}
                    )
                if email_to_create == primary_admin_email:
                    primary_user = existing_user
                continue

            logger.warning(
                f"No user document found for email '{email_to_create}'. Creating one.",
            )
            name = email_to_create.split("@")[0]
            logger.info(f"Setting user's default name to '{name}'.")

            new_user_dto = UserCreateDto(
                email=email_to_create,
                name=name,
            )
            user_data = new_user_dto.model_dump()
            user_data["roles"] = [UserRoleEnum.USER, UserRoleEnum.ADMIN]

            created_user = await user_repo.create(user_data)
            logger.info(
                f"Successfully created admin user document for '{email_to_create}'. ID: {created_user.id}",
            )
            if email_to_create == primary_admin_email:
                primary_user = created_user

        except Exception as e:
            logger.error(
                f"Failed to create or verify admin user for '{email_to_create}': {e}",
                exc_info=True,
            )

    return primary_user


def upload_assets_from_folder(
    local_folder: str, gcs_prefix: str
) -> dict[str, str]:
    """Uploads all files from a local folder to a GCS path and returns a mapping."""
    gcs_service = GcsService()
    uri_map = {}
    logger.info(f"Uploading assets from '{local_folder}' to GCS...")

    # Construct an absolute path to the assets folder
    abs_local_folder = os.path.join(SCRIPT_DIR, "assets", local_folder)
    logger.info(
        f"Uploading assets from '{abs_local_folder}' to GCS prefix '{gcs_prefix}'...",
    )

    if not os.path.isdir(abs_local_folder):
        logger.warning(f"Local asset folder not found: {abs_local_folder}")
        return {}

    for filename in os.listdir(abs_local_folder):
        local_path = os.path.join(abs_local_folder, filename)

        if os.path.isfile(local_path):
            destination_blob_name = f"{gcs_prefix}/{filename}"
            mime_type, _ = mimetypes.guess_type(local_path)
            # Provide a default mime_type if it cannot be guessed
            if not mime_type:
                mime_type = "application/octet-stream"
            gcs_uri = gcs_service.upload_file_to_gcs(  # type: ignore
                local_path=local_path,
                destination_blob_name=destination_blob_name,
                mime_type=mime_type,
            )
            if gcs_uri:
                uri_map[filename] = gcs_uri
                logger.info(f"  - Uploaded {filename} to {gcs_uri}")
    return uri_map


def upload_specific_assets(
    local_filenames: set[str],
    local_folder: str,
    gcs_prefix: str,
) -> dict[str, str]:
    """Uploads a specific list of files from a local folder to a GCS path."""
    gcs_service = GcsService()
    uri_map = {}
    logger.info(
        f"Uploading {len(local_filenames)} specific assets from '{local_folder}' to GCS...",
    )

    abs_local_folder = os.path.join(SCRIPT_DIR, "assets", local_folder)

    for filename in local_filenames:
        local_path = os.path.join(abs_local_folder, filename)
        if os.path.isfile(local_path):
            destination_blob_name = f"{gcs_prefix}/{filename}"
            mime_type, _ = mimetypes.guess_type(local_path)
            mime_type = mime_type or "application/octet-stream"

            gcs_uri = gcs_service.upload_file_to_gcs(  # type: ignore
                local_path=local_path,
                destination_blob_name=destination_blob_name,
                mime_type=mime_type,
            )
            if gcs_uri:
                uri_map[filename] = gcs_uri
                logger.info(f"  - Uploaded {filename} to {gcs_uri}")
    return uri_map


async def seed_media_templates(db: AsyncSession, admin_user: UserModel | None):
    """Uploads media template assets and seeds the media_templates collection."""
    logger.info("--- Starting Media Template Seeding ---")
    template_repo = MediaTemplateRepository(db)
    asset_repo = SourceAssetRepository(db)
    workspace_repo = WorkspaceRepository(db)

    if not admin_user:
        logger.error("Cannot seed media templates without an admin user.")
        return

    # 1. Identify which templates need to be created
    templates_to_create = []
    for template_data in TEMPLATES:
        template_name = template_data["name"]
        existing = await template_repo.get_by_name(template_name)
        if existing:
            logger.info(f"Template '{template_name}' already exists. Skipping.")
        else:
            templates_to_create.append(template_data)

    if not templates_to_create:
        logger.info("All media templates are already seeded. Nothing to do.")
        return

    # 2. Collect all unique asset filenames needed for the new templates
    required_filenames = set()
    for template_data in templates_to_create:
        required_filenames.update(template_data.get("local_uris", []))
        required_filenames.update(template_data.get("local_thumbnail_uris", []))
        for asset_info in template_data.get("input_gcs_uris", []):
            if "local_uri" in asset_info:
                required_filenames.add(asset_info["local_uri"])

    # 3. Upload only the required assets
    # Note: GCS upload is synchronous
    uri_map = upload_specific_assets(
        required_filenames,
        "media-template",
        "media_template_assets",
    )

    # 4. Iterate through the new templates and create documents
    for template_data in templates_to_create:
        template_name = template_data["name"]
        logger.info(f"Processing template: '{template_name}'")

        # Map local URIs to GCS URIs and create system assets
        gcs_uris = [
            uri
            for local_uri in template_data.get("local_uris", [])
            if (uri := uri_map.get(local_uri)) is not None
        ]

        thumbnail_gcs_uris = [
            uri
            for local_uri in template_data.get("local_thumbnail_uris", [])
            if (uri := uri_map.get(local_uri)) is not None
        ]

        if not gcs_uris and template_data.get("local_uris"):
            logger.warning(
                f"  - No assets found/uploaded for template '{template_name}'. Skipping.",
            )
            continue

        team_workspace = await workspace_repo.get_system_team_workspace()
        if not team_workspace:
            logger.error(
                "Team workspace not found. Cannot create system assets for templates.",
            )
            return

        new_source_asset_links = []
        # We only care about the first GCS URI as the main media.
        # The rest are considered input assets for generation.
        main_gcs_uri = gcs_uris[0] if gcs_uris else None
        input_assets_data = template_data.get("input_gcs_uris", [])

        for asset_data in input_assets_data:
            local_uri = asset_data.get("local_uri")
            mime_type = asset_data.get("mime_type")
            role = asset_data.get(
                "role", AssetRoleEnum.INPUT
            )  # Default to INPUT

            if not local_uri or not mime_type:
                logger.warning(
                    f"  - Skipping invalid input asset data in '{template_name}': {asset_data}",
                )
                continue

            gcs_uri = uri_map.get(local_uri)
            if not gcs_uri:
                logger.warning(
                    f"  - GCS URI not found for local file '{local_uri}'."
                )
                continue

            asset_id_to_link: int | None = None
            existing_asset = await asset_repo.get_by_gcs_uri(gcs_uri)

            if existing_asset:
                # If asset already exists, get its ID to link it.
                asset_id_to_link = existing_asset.id
                logger.info(
                    f"  - Found existing asset for '{local_uri}'. Re-using ID: {asset_id_to_link}",
                )
            else:
                # If asset does not exist, create it and get the new ID.
                new_asset = SourceAssetModel(
                    workspace_id=team_workspace.id,
                    original_filename=local_uri,
                    gcs_uri=gcs_uri,
                    mime_type=mime_type,
                    scope=AssetScope.SYSTEM,
                    asset_type=AssetType.GENERIC_IMAGE,  # Default type for templates
                    user_id=admin_user.id,
                    file_hash="",  # Not strictly needed for system assets
                )
                created_asset = await asset_repo.create(new_asset)
                asset_id_to_link = created_asset.id

            if asset_id_to_link:
                new_source_asset_links.append(
                    {"asset_id": asset_id_to_link, "role": role},
                )

        # Create the Pydantic models
        gen_params = GenerationParameters(
            **template_data["generation_parameters"]
        )
        # ID is auto-generated by DB, so we don't pass 'id' from template_data unless we want to force it (not recommended for Serial)
        # But template_data has "id" (string). We should probably ignore it or use it as name/slug if needed.
        # For now, we ignore the string ID from seed data and let DB generate int ID.

        new_template = MediaTemplateModel(
            name=template_name,
            description=template_data["description"],
            mime_type=template_data["mime_type"],
            industry=(
                IndustryEnum(template_data["industry"])
                if template_data.get("industry")
                else None
            ),
            brand=template_data.get("brand"),
            tags=template_data.get("tags", []),
            gcs_uris=[main_gcs_uri] if main_gcs_uri else [],
            thumbnail_uris=thumbnail_gcs_uris,
            source_assets=new_source_asset_links or None,
            generation_parameters=gen_params,
        )

        await template_repo.create(new_template)
        logger.info(f"  - Successfully saved template '{template_name}'.")


async def seed_vto_assets(db: AsyncSession, admin_user: UserModel | None):
    """Uploads system-level VTO assets (garments, models) for the VTO feature."""
    logger.info("--- Starting VTO System Asset Seeding ---")
    asset_repo = SourceAssetRepository(db)
    workspace_repo = WorkspaceRepository(db)
    team_workspace = await workspace_repo.get_system_team_workspace()

    if not team_workspace:
        logger.error("Cannot seed VTO assets: Public workspace not found.")
        return

    if not admin_user:
        logger.error("Cannot seed VTO assets without an admin user.")
        return

    vto_asset_folders = ["vto/garments", "vto/models"]

    for folder in vto_asset_folders:
        local_folder = folder
        gcs_prefix = f"system_assets/{folder}"
        mime_type = "image/png"  # Assuming all VTO assets are PNGs

        uri_map = upload_assets_from_folder(local_folder, gcs_prefix)

        for filename, gcs_uri in uri_map.items():
            # Check if an asset with this GCS URI already exists
            existing = await asset_repo.get_by_gcs_uri(gcs_uri)
            if existing:
                logger.info(
                    f"VTO asset for '{gcs_uri}' already exists. Skipping."
                )
                continue

            # --- Dynamically determine asset type from filename convention ---
            asset_type = None
            try:
                # Get filename without extension, e.g., "vto_top_0"
                base_name = os.path.splitext(filename)[0]
                # Split by underscore and remove the last part (the index)
                type_parts = base_name.split("_")[:-1]
                # Join the remaining parts to get the type string, e.g., "vto_top"
                type_string = "_".join(type_parts)
                # Convert the string to an AssetType enum member
                asset_type = AssetType(type_string)
                logger.info(
                    f"  - Detected asset type as '{asset_type.value}' for {filename}",
                )
            except (ValueError, IndexError):
                logger.warning(
                    f"  - Could not determine asset type for '{filename}' from its name. Skipping.",
                )
                continue

            logger.info(f"Creating VTO asset for: {filename}")
            new_asset = SourceAssetModel(
                workspace_id=team_workspace.id,
                original_filename=filename,
                gcs_uri=gcs_uri,
                mime_type=mime_type,  # type: ignore
                file_hash="",  # Not strictly needed for system assets
                scope=AssetScope.SYSTEM,
                asset_type=asset_type,
                user_id=admin_user.id,
                aspect_ratio=AspectRatioEnum.RATIO_9_16,
            )
            await asset_repo.create(new_asset)
            logger.info(f"  - Successfully saved VTO asset '{filename}'.")


async def main():
    try:
        # Run Database Migrations before seeding
        from src.database_migrations import run_pending_migrations

        await run_pending_migrations()

        async with async_session_local() as db:
            admin_user = await ensure_admin_user_exists(db)
            await ensure_default_team_workspace_exists(db, admin_user)
            await cleanup_invalid_personal_workspaces(db)
            await ensure_bootstrap_admin_workspaces(db)
            await seed_vto_assets(db, admin_user)
            await seed_media_templates(db, admin_user)
    finally:
        await cleanup_connector()


if __name__ == "__main__":
    asyncio.run(main())
