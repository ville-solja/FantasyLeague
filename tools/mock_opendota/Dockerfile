# Mock OpenDota (issue #146). Dev only: built by docker-compose.mock.yml with the repo
# root as context, never part of the app image (the root .dockerignore excludes tools/
# from the app's build, and the code is mounted, not copied).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
# The backend's models are imported for the season generator; keep `database` on an
# in-memory SQLite so the mock never creates a database file.
ENV DATABASE_URL=sqlite://
ENV MOCK_BACKEND_DIR=/backend

WORKDIR /mock

# The backend's hash-locked dependencies: the mock imports backend/season_generator.py
# and backend/scenarios.py from the read-only /backend mount.
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && rm /tmp/requirements.lock

# tools/mock_opendota is mounted at /mock and backend/ at /backend (read-only).
# 0.0.0.0 inside the container network only: Compose publishes it on 127.0.0.1.
# --no-access-log: the access log would print query strings (?key=, ?api_key=).
CMD ["uvicorn", "app:create_app", "--factory", "--app-dir", "/mock", "--host", "0.0.0.0", "--port", "8090", "--no-access-log"]
