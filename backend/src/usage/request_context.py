# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Request-scoped identity for GenAI usage logging."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar

_current_user_email: ContextVar[str | None] = ContextVar(
    "current_user_email", default=None
)
_current_user_id: ContextVar[int | None] = ContextVar(
    "current_user_id", default=None
)
_current_loop: ContextVar[asyncio.AbstractEventLoop | None] = ContextVar(
    "current_loop", default=None
)


def set_current_user(email: str | None, user_id: int | None) -> None:
    """Stores the authenticated user for the current request context."""
    _current_user_email.set(email)
    _current_user_id.set(user_id)
    try:
        _current_loop.set(asyncio.get_running_loop())
    except RuntimeError:
        _current_loop.set(None)


def get_current_user_email() -> str | None:
    """Returns the email from the current request context, if set."""
    return _current_user_email.get()


def get_current_user_id() -> int | None:
    """Returns the user id from the current request context, if set."""
    return _current_user_id.get()


def get_current_loop() -> asyncio.AbstractEventLoop | None:
    """Returns the request event loop, for scheduling work from worker threads."""
    return _current_loop.get()
