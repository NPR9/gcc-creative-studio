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
"""Authentication guards and user retrieval via IAP (or local bypass)."""

import asyncio
import logging
from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request, status
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token

from sqlalchemy.ext.asyncio import AsyncSession

from src.common.email_service import EmailService
from src.config.config_service import config_service
from src.usage.request_context import set_current_user
from src.database import get_db
from src.users.repository.user_repository import UserRepository
from src.users.user_model import UserModel, UserRoleEnum
from src.users.user_service import UserService
from src.workspaces.repository.workspace_repository import WorkspaceRepository
from src.workspaces.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"


def _parse_iap_email_header(header_value: str) -> str:
    """Parse `accounts.google.com:user@example.com` into an email."""
    if not header_value:
        return ""
    decoded = unquote(header_value)
    if ":" in decoded:
        return decoded.split(":", 1)[1].strip().lower()
    return decoded.strip().lower()


def _verify_iap_jwt(iap_jwt: str) -> dict:
    """Verify an IAP-signed JWT and return claims."""
    audience = config_service.IAP_AUDIENCE or config_service.GOOGLE_TOKEN_AUDIENCE
    if not audience:
        raise ValueError(
            "IAP_AUDIENCE (or GOOGLE_TOKEN_AUDIENCE) is not configured."
        )
    return id_token.verify_token(
        iap_jwt,
        google_auth_requests.Request(),
        audience=audience,
        certs_url=IAP_CERTS_URL,
    )


async def _ensure_user_has_workspace_access(
    db: AsyncSession,
    user: UserModel,
) -> None:
    """Creates a personal workspace when a provisioned user has none."""
    if not user.id:
        return

    workspace_repo = WorkspaceRepository(db)
    memberships = await workspace_repo.find_by_member_id(user.id)
    if memberships:
        return

    workspace_service = WorkspaceService(
        workspace_repo=workspace_repo,
        user_repo=UserRepository(db),
        email_service=EmailService(),
    )
    await workspace_service.ensure_personal_workspace(user)
    logger.info("Auto-provisioned personal workspace for user %s", user.email)


async def get_current_user(
    request: Request,
    user_service: UserService = Depends(UserService),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    """Authenticate via IAP JWT (deployed) or local identity header.

    Strict allowlist (match test): only users already provisioned by an admin
    may log in. Auto-create on first login is disabled.
    """
    try:
        email = ""
        name = ""
        picture = ""
        token_info_hd = None

        if config_service.ENVIRONMENT == "local":
            email = _parse_iap_email_header(
                request.headers.get("X-Goog-Authenticated-User-Email", "")
            )
            if not email:
                email = (config_service.LOCAL_USER_EMAIL or "").strip().lower()
            name_header = request.headers.get(
                "X-Goog-Authenticated-User-Name", ""
            )
            name = unquote(name_header) if name_header else email.split("@")[0]
            if "@" in email:
                token_info_hd = email.split("@", 1)[1]
        else:
            # Direct IAP → service, or FE proxy (X-CS-IAP-JWT): Cloud Run
            # strips X-Goog-IAP-* on FE→BE calls, so the proxy rewrites it.
            iap_jwt = request.headers.get(
                "X-Goog-IAP-JWT-Assertion"
            ) or request.headers.get("X-CS-IAP-JWT")
            if not iap_jwt:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing IAP credentials.",
                )
            decoded_token = await asyncio.to_thread(_verify_iap_jwt, iap_jwt)
            email = (decoded_token.get("email") or "").strip().lower()
            name = decoded_token.get("name") or email.split("@")[0]
            picture = decoded_token.get("picture", "")
            token_info_hd = decoded_token.get("hd")
            if not token_info_hd and "@" in email:
                token_info_hd = email.split("@", 1)[1]

        if not email:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Forbidden: User identity could not be confirmed from "
                    "IAP credentials."
                ),
            )

        if config_service.ALLOWED_ORGS:
            if (
                not token_info_hd
                or token_info_hd not in config_service.ALLOWED_ORGS
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=(
                        f"User from '{token_info_hd}' is not part of an "
                        "allowed organization."
                    ),
                )

        # Strict Allowlist: Only users explicitly added by admin can login.
        user_doc = await user_service.user_repo.get_by_email(
            email, include_deleted=False
        )

        if not user_doc:
            logger.warning(
                "Login attempt by unauthorized user: %s. "
                "User must be added by admin first.",
                email,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Access denied. Your account has not been provisioned. "
                    "Please contact an administrator to request access."
                ),
            )

        if not user_doc.picture and picture:
            logger.info("Updating picture for user: %s", email)
            user_doc.picture = picture
            if user_doc.id:
                await user_service.user_repo.update(
                    user_doc.id, {"picture": picture}
                )

        await _ensure_user_has_workspace_access(db, user_doc)

        logger.info(
            "User authenticated successfully: %s (ID: %s)",
            email,
            user_doc.id,
        )
        set_current_user(user_doc.email, user_doc.id)
        return user_doc

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[get_current_user - Exception]: %s", e)
        raise HTTPException(
            status_code=getattr(
                e,
                "status_code",
                status.HTTP_401_UNAUTHORIZED,
            ),
            detail=f"Authentication failed: {e}",
        ) from e


class RoleChecker:
    """Dependency that checks if the authenticated user has the required roles.
    It depends on `get_current_user` to ensure the user is authenticated first.
    """

    def __init__(
        self,
        allowed_roles: list[UserRoleEnum],
        allowed_emails: set[str] | None = None,
    ):
        self.allowed_roles = allowed_roles
        self.allowed_emails = {
            email.strip().lower()
            for email in (allowed_emails or set())
            if email.strip()
        }

    def __call__(self, user: UserModel = Depends(get_current_user)):
        """Checks the user's roles against the allowed roles."""
        is_authorized = any(role in self.allowed_roles for role in user.roles)

        if not is_authorized:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have sufficient permissions to perform this "
                    "action."
                ),
            )

        if self.allowed_emails:
            user_email = user.email.strip().lower()
            if user_email not in self.allowed_emails:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "You do not have sufficient permissions to "
                        "perform this action."
                    ),
                )
