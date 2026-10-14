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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.auth.auth_guard import RoleChecker, get_current_user
from src.config.config_service import config_service
from src.users.user_model import UserModel, UserRoleEnum


@pytest.fixture(name="mock_user_service")
def fixture_mock_user_service():
    service = AsyncMock()
    service.user_repo = AsyncMock()
    service.user_repo.get_by_email.return_value = UserModel(
        id=1,
        email="test@example.com",
        roles=["user"],
        name="Test User",
    )
    service.user_repo.update.return_value = None
    return service


def _mock_request(headers: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    return request


class TestGetCurrentUser:
    """Tests for get_current_user (IAP + strict allowlist)."""

    @pytest.mark.anyio
    async def test_get_current_user_local_success(self, mock_user_service):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = ""
        config_service.LOCAL_USER_EMAIL = "test@example.com"

        request = _mock_request(
            {"X-Goog-Authenticated-User-Email": "accounts.google.com:test@example.com"}
        )

        with patch(
            "src.auth.auth_guard._ensure_user_has_workspace_access",
            new=AsyncMock(),
        ):
            user = await get_current_user(
                request=request,
                user_service=mock_user_service,
                db=AsyncMock(),
            )

        assert user.email == "test@example.com"
        mock_user_service.user_repo.get_by_email.assert_called_once_with(
            "test@example.com", include_deleted=False
        )

    @pytest.mark.anyio
    async def test_get_current_user_unprovisioned_forbidden(
        self, mock_user_service
    ):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = ""
        config_service.LOCAL_USER_EMAIL = "unknown@example.com"
        mock_user_service.user_repo.get_by_email.return_value = None

        request = _mock_request()

        with patch(
            "src.auth.auth_guard._ensure_user_has_workspace_access",
            new=AsyncMock(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=request,
                    user_service=mock_user_service,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 403
        assert "not been provisioned" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_get_current_user_no_email(self, mock_user_service):
        config_service.ENVIRONMENT = "local"
        config_service.LOCAL_USER_EMAIL = ""

        request = _mock_request()

        with patch(
            "src.auth.auth_guard._ensure_user_has_workspace_access",
            new=AsyncMock(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=request,
                    user_service=mock_user_service,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 403
        assert "User identity could not be confirmed" in exc_info.value.detail

    @pytest.mark.anyio
    async def test_get_current_user_allowed_orgs_fail(self, mock_user_service):
        config_service.ENVIRONMENT = "local"
        config_service.ALLOWED_ORGS_STR = "allowed.com"
        config_service.LOCAL_USER_EMAIL = "test@forbidden.com"

        request = _mock_request()

        with patch(
            "src.auth.auth_guard._ensure_user_has_workspace_access",
            new=AsyncMock(),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    request=request,
                    user_service=mock_user_service,
                    db=AsyncMock(),
                )

        assert exc_info.value.status_code == 401
        assert "not part of an allowed organization" in exc_info.value.detail


class TestRoleChecker:
    """Tests for RoleChecker class."""

    def test_role_checker_authorized(self):
        checker = RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])
        user = UserModel(
            id=1,
            email="admin@example.com",
            roles=["admin"],
            name="Admin",
        )
        assert checker(user) is None

    def test_role_checker_unauthorized(self):
        checker = RoleChecker(allowed_roles=[UserRoleEnum.ADMIN])
        user = UserModel(
            id=1,
            email="user@example.com",
            roles=["user"],
            name="User",
        )
        with pytest.raises(HTTPException) as exc_info:
            checker(user)
        assert exc_info.value.status_code == 403

    def test_role_checker_allowed_emails(self):
        checker = RoleChecker(
            allowed_roles=[UserRoleEnum.ADMIN],
            allowed_emails={"owner@example.com"},
        )
        user = UserModel(
            id=1,
            email="other-admin@example.com",
            roles=["admin"],
            name="Admin",
        )
        with pytest.raises(HTTPException) as exc_info:
            checker(user)
        assert exc_info.value.status_code == 403
