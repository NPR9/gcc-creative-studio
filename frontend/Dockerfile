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

# Local docker-compose uses this stage (`target: builder`) with `npm start`.
FROM node:20-alpine AS builder

WORKDIR /app
COPY . /app/

RUN npm ci

# Production image: build Angular then serve with nginx (Cloud Run).
FROM builder AS production-build
RUN npm run build -- --configuration=production

# Production runtime: static SPA + /api proxy that attaches a Cloud Run
# identity token for the frontend runtime SA (roles/run.invoker on backend).
FROM python:3.12-alpine

ARG BACKEND_HOST=localhost:8080
ENV BACKEND_HOST=${BACKEND_HOST}
ENV STATIC_ROOT=/usr/share/nginx/html
ENV PORT=8080

COPY --from=production-build /app/dist/creative-studio/browser /usr/share/nginx/html
COPY cloud_run_api_proxy.py /app/cloud_run_api_proxy.py

EXPOSE 8080
CMD ["python", "/app/cloud_run_api_proxy.py"]
