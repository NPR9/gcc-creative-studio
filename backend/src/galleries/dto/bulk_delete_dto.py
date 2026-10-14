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


from pydantic import BaseModel, Field


class BulkDeleteItemDto(BaseModel):
    id: int
    type: str
    # When set for media_item, delete only that image within the generation set.
    image_index: int | None = Field(default=None, ge=0)


class BulkDeleteDto(BaseModel):
    items: list[BulkDeleteItemDto]
    workspace_id: int
