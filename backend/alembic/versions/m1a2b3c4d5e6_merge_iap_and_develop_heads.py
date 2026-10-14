# Copyright 2026 Google LLC
"""Merge IAP branch system-settings head with develop groups head.

Revision ID: m1a2b3c4d5e6
Revises: 7c8d9e0f1a2b, cb3c4680571b
Create Date: 2026-07-28 00:00:00.000000
"""
from typing import Sequence, Union

revision: str = "m1a2b3c4d5e6"
down_revision: Union[str, tuple[str, ...], None] = ("7c8d9e0f1a2b", "cb3c4680571b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
