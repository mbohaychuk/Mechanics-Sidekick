# Phase 1 — Backend Foundation & Management API — Implementation Plan

**Goal:** Stand up a FastAPI backend that exposes the existing vehicle → document → job workflow over HTTP, with OpenAI-backed embeddings/contextualization and browser-upload background ingestion — no chat yet.

**Architecture:** A new `app/api/` package wraps the existing, unchanged service/repository layer. The engine and a session factory live on `app.state`; a per-request dependency yields a committing session. OpenAI replaces Ollama behind a small config-driven factory that reuses the existing `EmbeddingService`/`ContextualizationService` unchanged. Document upload registers a row synchronously and processes it in a FastAPI background task.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, OpenAI Python SDK, SQLAlchemy 2.0 (existing), pytest + FastAPI `TestClient`.

This is the first of four Phase 1 plans (foundation → agentic chat → MCP host/tools → Vue SPA). It produces working, independently testable software: a complete management API.

## Global Constraints

- Python ≥ 3.11; manage dependencies with `uv` (`uv add …`, run via `uv run …`).
- All HTTP routes are prefixed `/api`.
- Default providers: chat + embeddings = OpenAI. Embedding model `text-embedding-3-small` (1536-dim) — **incompatible with existing `nomic-embed-text` (768-dim) chunks; previously ingested documents must be re-ingested.**
- Tests never hit the network: OpenAI and any LLM backend are mocked with `MagicMock(spec=…)`, matching the existing test convention.
- Run the full suite with `uv run pytest tests/ -v`. The existing Typer CLI and its tests must stay green.
- Keep commit messages plain and authored in the conventional-commit style already used in this repo.

---

### Task 1: Add dependencies and configuration

**Files:**
- Modify: `pyproject.toml` (dependencies — via `uv add`)
- Modify: `app/config.py`
- Test: `tests/test_config.py` (create)

**Interfaces:**
- Produces: `Settings` fields — `llm_provider: str`, `embed_provider: str`, `openai_api_key: str`, `openai_chat_model: str`, `openai_embed_model: str`, `api_host: str`, `api_port: int`, `cors_origin: str`, `spa_dist_dir: str`.

- [ ] **Step 1: Add runtime and dev dependencies**

Run:
```bash
uv add fastapi "uvicorn[standard]" openai python-multipart
uv add --group dev httpx
```
Expected: `pyproject.toml` gains the deps; `uv.lock` updates; no errors. (`python-multipart` is required by FastAPI for file uploads; `httpx` is required by `TestClient`.)

- [ ] **Step 2: Write the failing config test**

Create `tests/test_config.py`:
```python
from app.config import Settings


def test_settings_have_openai_and_api_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai"
    assert s.embed_provider == "openai"
    assert s.openai_chat_model == "gpt-4.1-mini"
    assert s.openai_embed_model == "text-embedding-3-small"
    assert s.api_port == 8000
    assert s.cors_origin == "http://localhost:5173"
    assert s.spa_dist_dir == "frontend/dist"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError`/validation error on the missing fields.

- [ ] **Step 4: Add the fields to `Settings`**

In `app/config.py`, add inside `Settings` (after the existing fields, before `model_config`):
```python
    llm_provider: str = "openai"
    embed_provider: str = "openai"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embed_model: str = "text-embedding-3-small"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origin: str = "http://localhost:5173"
    spa_dist_dir: str = "frontend/dist"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/config.py tests/test_config.py
git commit -m "feat(api): add web/OpenAI deps and API config settings"
```

---

### Task 2: OpenAIService (embeddings + chat)

**Files:**
- Create: `app/services/openai_service.py`
- Test: `tests/test_services/test_openai_service.py` (create)

**Interfaces:**
- Produces: `OpenAIService(api_key: str, client=None)` with `embed(texts: list[str], model: str) -> list[list[float]]` and `chat(messages: list[dict], model: str) -> str`. Same method surface as `OllamaService`, so it is a drop-in backend for `EmbeddingService` and `ContextualizationService`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_openai_service.py`:
```python
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.openai_service import OpenAIService


def test_embed_returns_one_vector_per_text():
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])]
    )
    svc = OpenAIService(api_key="x", client=client)

    result = svc.embed(["a", "b"], model="text-embedding-3-small")

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small", input=["a", "b"]
    )


def test_chat_returns_message_content():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
    )
    svc = OpenAIService(api_key="x", client=client)

    result = svc.chat([{"role": "user", "content": "hi"}], model="gpt-4.1-mini")

    assert result == "hello"
    client.chat.completions.create.assert_called_once_with(
        model="gpt-4.1-mini", messages=[{"role": "user", "content": "hi"}]
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_services/test_openai_service.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.openai_service`.

- [ ] **Step 3: Write the implementation**

Create `app/services/openai_service.py`:
```python
from openai import OpenAI


class OpenAIService:
    """Low-level wrapper around the OpenAI client.

    Mirrors OllamaService's surface (embed, chat) so it is a drop-in backend
    for EmbeddingService and ContextualizationService.
    """

    def __init__(self, api_key: str, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=api_key)

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        response = self._client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    def chat(self, messages: list[dict], model: str) -> str:
        response = self._client.chat.completions.create(model=model, messages=messages)
        return response.choices[0].message.content
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_services/test_openai_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/openai_service.py tests/test_services/test_openai_service.py
git commit -m "feat(api): add OpenAIService (embed + chat)"
```

---

### Task 3: Provider-select LLM factory

**Files:**
- Create: `app/services/llm_factory.py`
- Test: `tests/test_services/test_llm_factory.py` (create)

**Interfaces:**
- Consumes: `OpenAIService` (Task 2), existing `OllamaService`, `EmbeddingService`, `ContextualizationService`, `Settings`.
- Produces: `make_embedding_service(settings) -> EmbeddingService`, `make_contextualization_service(settings) -> ContextualizationService`. These pick the backend by `settings.embed_provider` / `settings.llm_provider` (`"openai"` → OpenAI, else Ollama). `EmbeddingService`/`ContextualizationService` are reused unchanged (they accept any object exposing `embed`/`chat`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_llm_factory.py`:
```python
from app.config import Settings
from app.services.embedding_service import EmbeddingService
from app.services.contextualization_service import ContextualizationService
from app.services.openai_service import OpenAIService
from app.services.ollama_service import OllamaService
from app.services.llm_factory import (
    make_embedding_service,
    make_contextualization_service,
)


def test_openai_providers_selected_by_default():
    s = Settings(_env_file=None, openai_api_key="x")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb, EmbeddingService)
    assert isinstance(ctx, ContextualizationService)
    assert isinstance(emb._ollama, OpenAIService)
    assert isinstance(ctx._ollama, OpenAIService)
    assert emb._model == "text-embedding-3-small"
    assert ctx._model == "gpt-4.1-mini"


def test_ollama_selected_when_configured():
    s = Settings(_env_file=None, embed_provider="ollama", llm_provider="ollama")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb._ollama, OllamaService)
    assert isinstance(ctx._ollama, OllamaService)
    assert emb._model == "nomic-embed-text"
    assert ctx._model == "llama3.2:3b"
```
(`_ollama` is the existing private attribute name on both services — see `app/services/embedding_service.py:6` and `contextualization_service.py:15`. It now holds an OpenAI backend when configured; renaming it is a deferred cleanup, not part of this plan.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_services/test_llm_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.llm_factory`.

- [ ] **Step 3: Write the implementation**

Create `app/services/llm_factory.py`:
```python
from app.config import Settings
from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService
from app.services.ollama_service import OllamaService
from app.services.openai_service import OpenAIService


def make_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.embed_provider == "openai":
        return EmbeddingService(
            OpenAIService(api_key=settings.openai_api_key),
            settings.openai_embed_model,
        )
    return EmbeddingService(
        OllamaService(settings.ollama_base_url),
        settings.embed_model,
    )


def make_contextualization_service(settings: Settings) -> ContextualizationService:
    if settings.llm_provider == "openai":
        return ContextualizationService(
            OpenAIService(api_key=settings.openai_api_key),
            settings.openai_chat_model,
        )
    return ContextualizationService(
        OllamaService(settings.ollama_base_url),
        settings.context_model,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_services/test_llm_factory.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/llm_factory.py tests/test_services/test_llm_factory.py
git commit -m "feat(api): add provider-select LLM factory (OpenAI default)"
```

---

### Task 4: FastAPI app skeleton (lifespan, session dependency, health, SPA mount, entrypoint)

**Files:**
- Create: `app/api/__init__.py`, `app/api/deps.py`, `app/api/main.py`, `app/api/server.py`
- Create: `app/api/routers/__init__.py`
- Modify: `pyproject.toml` (add `[project.scripts]` entry)
- Create: `tests/test_api/__init__.py`, `tests/test_api/conftest.py`, `tests/test_api/test_health.py`

**Interfaces:**
- Produces:
  - `app.api.deps.get_session() -> Iterator[Session]` — FastAPI dependency reading `request.app.state.session_factory`, commits on success / rolls back on exception / always closes.
  - `app.api.main.create_app() -> FastAPI`.
  - `app.api.main.configure_db(app, db_url: str) -> None` — sets `app.state.engine` and `app.state.session_factory`, runs `create_all`.
  - Test fixture `api_client` (in `tests/test_api/conftest.py`) — a `TestClient` bound to a temp-file SQLite DB.

- [ ] **Step 1: Write the failing health test + fixture**

Create `tests/test_api/__init__.py` (empty).

Create `tests/test_api/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app, configure_db


@pytest.fixture
def api_client(tmp_path):
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as client:
        yield client
```

Create `tests/test_api/test_health.py`:
```python
def test_health_ok(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: app.api.main`.

- [ ] **Step 3: Write the session dependency**

Create `app/api/__init__.py` (empty) and `app/api/routers/__init__.py` (empty).

Create `app/api/deps.py`:
```python
from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Write the app factory**

Create `app/api/main.py`:
```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401 — register models with Base before create_all
from app.config import settings
from app.db import Base, get_engine, get_session_factory


def configure_db(app: FastAPI, db_url: str) -> None:
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = get_session_factory(engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(app.state, "session_factory", None):
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        configure_db(app, f"sqlite:///{db_path}")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Mechanics Sidekick API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Routers are included here in later tasks.

    spa_dir = Path(settings.spa_dist_dir)
    if spa_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dir), html=True), name="spa")

    return app
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_health.py -v`
Expected: PASS. (`configure_db` in the fixture pre-sets `session_factory`, so `lifespan` skips the real DB path.)

- [ ] **Step 6: Add the uvicorn entrypoint and script**

Create `app/api/server.py`:
```python
import uvicorn

from app.api.main import create_app
from app.config import settings


def main() -> None:
    uvicorn.run(create_app(), host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
```

In `pyproject.toml`, under `[project.scripts]`, add the second line:
```toml
[project.scripts]
mechanic-sidekick = "app.cli:app"
mechanic-sidekick-api = "app.api.server:main"
```

- [ ] **Step 7: Verify the server boots, then commit**

Run: `uv run python -c "from app.api.main import create_app; create_app()"`
Expected: no error (app constructs without a SPA build present).

```bash
git add app/api tests/test_api pyproject.toml
git commit -m "feat(api): FastAPI skeleton with health, session dep, SPA mount, entrypoint"
```

---

### Task 5: Vehicles router

**Files:**
- Create: `app/api/schemas.py`
- Create: `app/api/routers/vehicles.py`
- Modify: `app/api/main.py` (include the router)
- Test: `tests/test_api/test_vehicles.py` (create)

**Interfaces:**
- Consumes: `get_session` (Task 4), existing `VehicleService`/`VehicleRepository`.
- Produces: schemas `VehicleCreate`, `VehicleOut`; routes `GET /api/vehicles`, `POST /api/vehicles` (201), `GET /api/vehicles/{vehicle_id}` (404 if missing).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_vehicles.py`:
```python
def test_create_then_get_and_list_vehicle(api_client):
    payload = {
        "year": 2004,
        "make": "Audi",
        "model": "A8",
        "engine": "4.2L V8",
        "vin": None,
        "notes": None,
    }
    created = api_client.post("/api/vehicles", json=payload)
    assert created.status_code == 201
    body = created.json()
    assert body["id"] >= 1
    assert body["make"] == "Audi"

    vid = body["id"]
    got = api_client.get(f"/api/vehicles/{vid}")
    assert got.status_code == 200
    assert got.json()["model"] == "A8"

    listed = api_client.get("/api/vehicles")
    assert listed.status_code == 200
    assert [v["id"] for v in listed.json()] == [vid]


def test_get_missing_vehicle_is_404(api_client):
    r = api_client.get("/api/vehicles/999")
    assert r.status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_vehicles.py -v`
Expected: FAIL — 404 from a non-existent route / `ModuleNotFoundError` for schemas.

- [ ] **Step 3: Create the schemas**

Create `app/api/schemas.py`:
```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VehicleCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    year: int
    make: str
    model: str
    engine: str
    vin: str | None = None
    notes: str | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    year: int
    make: str
    model: str
    engine: str
    vin: str | None
    notes: str | None
    created_utc: datetime
```
(`protected_namespaces=()` suppresses Pydantic's warning about the field named `model`.)

- [ ] **Step 4: Create the router**

Create `app/api/routers/vehicles.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import VehicleCreate, VehicleOut
from app.repositories.vehicle_repository import VehicleRepository
from app.services.vehicle_service import VehicleService

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def _service(session: Session) -> VehicleService:
    return VehicleService(VehicleRepository(session))


@router.get("", response_model=list[VehicleOut])
def list_vehicles(session: Session = Depends(get_session)):
    return _service(session).list_vehicles()


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, session: Session = Depends(get_session)):
    vehicle = _service(session).add_vehicle(**payload.model_dump())
    session.flush()
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, session: Session = Depends(get_session)):
    try:
        return _service(session).get_vehicle(vehicle_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

- [ ] **Step 5: Include the router**

In `app/api/main.py`, add the import at the top (with the other imports):
```python
from app.api.routers import vehicles
```
And replace the `# Routers are included here in later tasks.` line with:
```python
    app.include_router(vehicles.router)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_vehicles.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/api/schemas.py app/api/routers/vehicles.py app/api/main.py tests/test_api/test_vehicles.py
git commit -m "feat(api): vehicles CRUD endpoints"
```

---

### Task 6: Jobs router

**Files:**
- Modify: `app/api/schemas.py` (add job schemas)
- Create: `app/api/routers/jobs.py`
- Modify: `app/api/main.py` (include the router)
- Test: `tests/test_api/test_jobs.py` (create)

**Interfaces:**
- Consumes: `get_session`, existing `JobService(JobRepository, VehicleRepository)`.
- Produces: schemas `JobCreate`, `JobOut`; routes `GET /api/vehicles/{vehicle_id}/jobs`, `POST /api/vehicles/{vehicle_id}/jobs` (201, 404 if vehicle missing), `GET /api/jobs/{job_id}` (404 if missing).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_jobs.py`:
```python
def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def test_create_list_and_get_job(api_client):
    vid = _make_vehicle(api_client)

    created = api_client.post(
        f"/api/vehicles/{vid}/jobs",
        json={"title": "Oil leak", "description": "front main seal"},
    )
    assert created.status_code == 201
    job = created.json()
    assert job["title"] == "Oil leak"
    assert job["status"] == "open"
    assert job["vehicle_id"] == vid

    listed = api_client.get(f"/api/vehicles/{vid}/jobs")
    assert [j["id"] for j in listed.json()] == [job["id"]]

    got = api_client.get(f"/api/jobs/{job['id']}")
    assert got.status_code == 200
    assert got.json()["title"] == "Oil leak"


def test_create_job_for_missing_vehicle_is_404(api_client):
    r = api_client.post("/api/vehicles/999/jobs", json={"title": "x"})
    assert r.status_code == 404


def test_get_missing_job_is_404(api_client):
    assert api_client.get("/api/jobs/999").status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_jobs.py -v`
Expected: FAIL — routes/schemas not defined.

- [ ] **Step 3: Add job schemas**

Append to `app/api/schemas.py`:
```python
class JobCreate(BaseModel):
    title: str
    description: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    title: str
    description: str | None
    status: str
    created_utc: datetime
```

- [ ] **Step 4: Create the router**

Create `app/api/routers/jobs.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import JobCreate, JobOut
from app.repositories.job_repository import JobRepository
from app.repositories.vehicle_repository import VehicleRepository
from app.services.job_service import JobService

router = APIRouter(prefix="/api", tags=["jobs"])


def _service(session: Session) -> JobService:
    return JobService(JobRepository(session), VehicleRepository(session))


@router.get("/vehicles/{vehicle_id}/jobs", response_model=list[JobOut])
def list_jobs(vehicle_id: int, session: Session = Depends(get_session)):
    return _service(session).list_jobs(vehicle_id)


@router.post("/vehicles/{vehicle_id}/jobs", response_model=JobOut, status_code=201)
def create_job(vehicle_id: int, payload: JobCreate, session: Session = Depends(get_session)):
    try:
        job = _service(session).add_job(vehicle_id=vehicle_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    session.flush()
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, session: Session = Depends(get_session)):
    try:
        return _service(session).get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
```

- [ ] **Step 5: Include the router**

In `app/api/main.py`, add `jobs` to the routers import and include it:
```python
from app.api.routers import vehicles, jobs
```
```python
    app.include_router(vehicles.router)
    app.include_router(jobs.router)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_jobs.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/api/schemas.py app/api/routers/jobs.py app/api/main.py tests/test_api/test_jobs.py
git commit -m "feat(api): jobs endpoints"
```

---

### Task 7: Documents read router

**Files:**
- Modify: `app/api/schemas.py` (add `DocumentOut`)
- Create: `app/api/routers/documents.py`
- Modify: `app/api/main.py` (include the router)
- Test: `tests/test_api/test_documents_read.py` (create)

**Interfaces:**
- Consumes: `get_session`, existing `DocumentRepository`.
- Produces: schema `DocumentOut`; routes `GET /api/vehicles/{vehicle_id}/documents`, `GET /api/documents/{document_id}` (404 if missing). Reads use `DocumentRepository` directly (no heavy `DocumentService` construction for list/get).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_documents_read.py`:
```python
from app.models.document import Document


def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def test_list_and_get_document(api_client):
    vid = _make_vehicle(api_client)

    # Seed a document row directly through the app's session factory.
    factory = api_client.app.state.session_factory
    session = factory()
    doc = Document(vehicle_id=vid, file_name="m.pdf", stored_path="/x/m.pdf")
    session.add(doc)
    session.commit()
    doc_id = doc.id
    session.close()

    listed = api_client.get(f"/api/vehicles/{vid}/documents")
    assert listed.status_code == 200
    assert [d["id"] for d in listed.json()] == [doc_id]
    assert listed.json()[0]["processing_status"] == "pending"

    got = api_client.get(f"/api/documents/{doc_id}")
    assert got.status_code == 200
    assert got.json()["file_name"] == "m.pdf"


def test_get_missing_document_is_404(api_client):
    assert api_client.get("/api/documents/999").status_code == 404
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_documents_read.py -v`
Expected: FAIL — routes/schema not defined.

- [ ] **Step 3: Add the document schema**

Append to `app/api/schemas.py`:
```python
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vehicle_id: int
    file_name: str
    document_type: str
    processing_status: str
    uploaded_utc: datetime
```

- [ ] **Step 4: Create the router**

Create `app/api/routers/documents.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import DocumentOut
from app.repositories.document_repository import DocumentRepository

router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/vehicles/{vehicle_id}/documents", response_model=list[DocumentOut])
def list_documents(vehicle_id: int, session: Session = Depends(get_session)):
    return DocumentRepository(session).list_by_vehicle(vehicle_id)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, session: Session = Depends(get_session)):
    doc = DocumentRepository(session).get_by_id(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    return doc
```

- [ ] **Step 5: Include the router**

In `app/api/main.py`, add `documents` to the routers import and include it:
```python
from app.api.routers import vehicles, jobs, documents
```
```python
    app.include_router(vehicles.router)
    app.include_router(jobs.router)
    app.include_router(documents.router)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_documents_read.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/api/schemas.py app/api/routers/documents.py app/api/main.py tests/test_api/test_documents_read.py
git commit -m "feat(api): document list/get endpoints"
```

---

### Task 8: Split DocumentService into register + process

**Files:**
- Modify: `app/services/document_service.py`
- Test: `tests/test_services/test_document_service_split.py` (create)

**Interfaces:**
- Produces on `DocumentService`:
  - `register_document(vehicle_id: int, file_name: str, document_type: str = "service_manual") -> Document` — creates the row (`processing_status="pending"`), flushes to assign `id`, does **not** process.
  - `process_document(doc_id: int, pdf_path: str) -> Document` — copies `pdf_path` into `docs_dir`, extracts/chunks/contextualizes/embeds/stores, sets status `ready`; on failure sets `failed` and raises `RuntimeError`.
  - `add_document(...)` keeps its existing external behavior (register then process), so the CLI and existing tests are unaffected.

- [ ] **Step 1: Write the failing test**

Create `tests/test_services/test_document_service_split.py`:
```python
from unittest.mock import MagicMock

import fitz  # PyMuPDF

from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.models.vehicle import Vehicle
from app.services.contextualization_service import ContextualizationService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Valve clearance intake is 0.20 mm cold.")
    doc.save(str(path))
    doc.close()


def _service(session, docs_dir):
    emb = MagicMock(spec=EmbeddingService)
    emb.embed_texts.side_effect = lambda texts: [[0.0, 1.0] for _ in texts]
    ctx = MagicMock(spec=ContextualizationService)
    ctx.generate_context.side_effect = lambda **kwargs: "context summary"
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(500, 100),
        contextualization_service=ctx,
        embedding_service=emb,
        docs_dir=str(docs_dir),
    )


def test_register_creates_pending_row(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")

    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")

    assert doc.id is not None
    assert doc.processing_status == "pending"


def test_process_marks_ready_and_stores_chunks(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")
    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")
    pdf = tmp_path / "m.pdf"
    _make_pdf(pdf)

    result = svc.process_document(doc.id, str(pdf))

    assert result.processing_status == "ready"
    chunks = ChunkRepository(db_session).list_by_vehicle(1)
    assert len(chunks) >= 1


def test_process_marks_failed_on_missing_file(db_session, tmp_path):
    db_session.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L"))
    db_session.flush()
    svc = _service(db_session, tmp_path / "docs")
    doc = svc.register_document(vehicle_id=1, file_name="m.pdf")

    try:
        svc.process_document(doc.id, str(tmp_path / "does-not-exist.pdf"))
    except FileNotFoundError:
        pass

    assert DocumentRepository(db_session).get_by_id(doc.id).processing_status == "failed"
```
(Confirm `ChunkRepository.list_by_vehicle` exists — it is used by `RetrievalService` at `app/services/retrieval_service.py:21`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_services/test_document_service_split.py -v`
Expected: FAIL — `AttributeError: 'DocumentService' object has no attribute 'register_document'`.

- [ ] **Step 3: Refactor `DocumentService`**

Replace the body of `add_document` and add the two new methods. In `app/services/document_service.py`, replace the `add_document` method (lines 36–102) with:
```python
    def register_document(
        self, vehicle_id: int, file_name: str, document_type: str = "service_manual"
    ) -> Document:
        doc = self._doc_repo.create(
            vehicle_id=vehicle_id,
            file_name=file_name,
            stored_path="",
            document_type=document_type,
        )
        self._doc_repo.session.flush()  # assigns doc.id
        return doc

    def process_document(self, doc_id: int, pdf_path: str) -> Document:
        doc = self._doc_repo.get_by_id(doc_id)
        if doc is None:
            raise ValueError(f"Document {doc_id} not found")
        source = Path(pdf_path)
        if not source.exists():
            self._doc_repo.update_status(doc.id, "failed")
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        dest = get_document_path(self._docs_dir, doc.vehicle_id, doc.id, doc.file_name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(source, dest)
            doc.stored_path = str(dest)
            page_blocks = self._pdf_service.extract_blocks(str(dest))
            raw_chunks = self._chunking_service.chunk_blocks(page_blocks)
            total = len(raw_chunks)

            contexts = [
                self._contextualization_service.generate_context(
                    chunk_content=c["content"],
                    filename=doc.file_name,
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    chunk_index=c["chunk_index"],
                    total_chunks=total,
                )
                for c in raw_chunks
            ]

            contextualized_texts = [
                (
                    f"Document: {doc.file_name} | "
                    f"Section: {c.get('section_title') or 'Unknown'} | "
                    f"Page: {c.get('page_number', 'unknown')}\n"
                    f"{ctx}\n\n{c['content']}"
                )
                for c, ctx in zip(raw_chunks, contexts)
            ]
            embeddings = self._embedding_service.embed_texts(contextualized_texts)

            self._chunk_repo.bulk_create([
                DocumentChunk(
                    document_id=doc.id,
                    chunk_index=c["chunk_index"],
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    content=c["content"],
                    context_summary=ctx,
                    embedding_json=json.dumps(emb),
                )
                for c, ctx, emb in zip(raw_chunks, contexts, embeddings)
            ])
            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def add_document(
        self, vehicle_id: int, pdf_path: str, document_type: str = "service_manual"
    ) -> Document:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        doc = self.register_document(vehicle_id, source.name, document_type)
        return self.process_document(doc.id, str(source))
```
(`FileNotFoundError` is re-raised before the `try`, so a missing source in `add_document` behaves exactly as before. In `process_document` the missing-file path sets `failed` first because the row already exists.)

- [ ] **Step 4: Run the new tests AND the existing suite**

Run: `uv run pytest tests/test_services/test_document_service_split.py -v`
Expected: PASS.

Run: `uv run pytest tests/ -v`
Expected: PASS — existing `add_document` behavior is preserved.

- [ ] **Step 5: Commit**

```bash
git add app/services/document_service.py tests/test_services/test_document_service_split.py
git commit -m "refactor: split DocumentService into register_document + process_document"
```

---

### Task 9: Document upload endpoint with background ingestion

**Files:**
- Create: `app/api/ingestion.py`
- Modify: `app/api/routers/documents.py` (add the upload route)
- Test: `tests/test_api/test_documents_upload.py` (create)

**Interfaces:**
- Consumes: `register`/`process_document` (Task 8), `make_embedding_service`/`make_contextualization_service` (Task 3), existing `DocumentRepository`, app `session_factory` (Task 4).
- Produces:
  - `app.api.ingestion.build_document_service(session, settings) -> DocumentService`.
  - `app.api.ingestion.ingest_document(session_factory, settings, doc_id: int, pdf_path: str) -> None` — runs `process_document` in its own session, commits on success; on failure rolls back and persists `failed` in a fresh session; always deletes the temp file.
  - Route `POST /api/vehicles/{vehicle_id}/documents` (202) — saves the upload to a temp file, registers the row synchronously (committed), schedules background ingestion, returns the `pending` document.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_documents_upload.py`:
```python
from unittest.mock import MagicMock

import fitz  # PyMuPDF

from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService


def _make_vehicle(api_client):
    return api_client.post(
        "/api/vehicles",
        json={"year": 2004, "make": "Audi", "model": "A8", "engine": "4.2L"},
    ).json()["id"]


def _fake_emb():
    emb = MagicMock(spec=EmbeddingService)
    emb.embed_texts.side_effect = lambda texts: [[0.0, 1.0] for _ in texts]
    return emb


def _fake_ctx():
    ctx = MagicMock(spec=ContextualizationService)
    ctx.generate_context.side_effect = lambda **kwargs: "context summary"
    return ctx


def test_upload_registers_then_processes_to_ready(api_client, monkeypatch, tmp_path):
    vid = _make_vehicle(api_client)

    monkeypatch.setattr("app.api.ingestion.make_embedding_service", lambda s: _fake_emb())
    monkeypatch.setattr(
        "app.api.ingestion.make_contextualization_service", lambda s: _fake_ctx()
    )

    pdf = tmp_path / "manual.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Torque the head bolts to 40 Nm.")
    doc.save(str(pdf))
    doc.close()

    with open(pdf, "rb") as fh:
        r = api_client.post(
            f"/api/vehicles/{vid}/documents",
            files={"file": ("manual.pdf", fh, "application/pdf")},
        )

    assert r.status_code == 202
    body = r.json()
    assert body["processing_status"] == "pending"
    doc_id = body["id"]

    # TestClient runs background tasks before returning, so processing is done.
    final = api_client.get(f"/api/documents/{doc_id}").json()
    assert final["processing_status"] == "ready"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_documents_upload.py -v`
Expected: FAIL — upload route returns 404/405 (not defined) and `app.api.ingestion` missing.

- [ ] **Step 3: Write the ingestion module**

Create `app/api/ingestion.py`:
```python
from pathlib import Path

from app.config import Settings
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.llm_factory import (
    make_contextualization_service,
    make_embedding_service,
)
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService


def build_document_service(session, settings: Settings) -> DocumentService:
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(
            settings.chunk_size, settings.chunk_overlap
        ),
        contextualization_service=make_contextualization_service(settings),
        embedding_service=make_embedding_service(settings),
        docs_dir=settings.docs_dir,
    )


def _mark_failed(session_factory, doc_id: int) -> None:
    session = session_factory()
    try:
        DocumentRepository(session).update_status(doc_id, "failed")
        session.commit()
    finally:
        session.close()


def ingest_document(session_factory, settings: Settings, doc_id: int, pdf_path: str) -> None:
    session = session_factory()
    try:
        build_document_service(session, settings).process_document(doc_id, pdf_path)
        session.commit()
    except Exception:
        session.rollback()
        _mark_failed(session_factory, doc_id)
    finally:
        session.close()
        Path(pdf_path).unlink(missing_ok=True)
```

- [ ] **Step 4: Add the upload route**

In `app/api/routers/documents.py`, update the imports at the top:
```python
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.ingestion import ingest_document
from app.api.schemas import DocumentOut
from app.config import settings
from app.repositories.document_repository import DocumentRepository
```
Then append this route to the same file:
```python
@router.post("/vehicles/{vehicle_id}/documents", response_model=DocumentOut, status_code=202)
def upload_document(
    vehicle_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        shutil.copyfileobj(file.file, tmp)
    finally:
        tmp.close()

    doc = DocumentRepository(session).create(
        vehicle_id=vehicle_id,
        file_name=file.filename or "upload.pdf",
        stored_path="",
    )
    session.commit()  # persist so the background worker's new session sees the row

    background_tasks.add_task(
        ingest_document,
        request.app.state.session_factory,
        settings,
        doc.id,
        tmp.name,
    )
    return doc
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_api/test_documents_upload.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS (all existing + new tests).

- [ ] **Step 7: Commit**

```bash
git add app/api/ingestion.py app/api/routers/documents.py tests/test_api/test_documents_upload.py
git commit -m "feat(api): document upload with background ingestion"
```

---

## Manual smoke test (after all tasks)

With a real `OPENAI_API_KEY` in `.env`:
```bash
uv run mechanic-sidekick-api          # starts uvicorn on http://127.0.0.1:8000
# in another shell:
curl -s localhost:8000/api/health
curl -s -X POST localhost:8000/api/vehicles \
  -H 'content-type: application/json' \
  -d '{"year":2004,"make":"Audi","model":"A8","engine":"4.2L"}'
curl -s -F file=@/path/to/small.pdf localhost:8000/api/vehicles/1/documents
curl -s localhost:8000/api/documents/1     # poll until processing_status == "ready"
```

## Self-review

**Spec coverage (Phase 1 §1.2, §1.6, §1.11 portions in this plan):**
- FastAPI skeleton + lifespan + session dep + CORS + guarded SPA mount + entrypoint → Task 4. ✔
- OpenAI chat+embeddings + provider seam + factory → Tasks 2–3. ✔
- REST CRUD vehicles/jobs/documents (§1.11) → Tasks 5–7. ✔
- Browser upload + background ingestion (§1.6 ingestion, processing_status) → Tasks 8–9. ✔
- Re-embedding consequence (§1.6) → Global Constraints + manual smoke test note. ✔
- Out of scope for this plan (later Phase 1 plans): chat/SSE/orchestrator, MCP host, web_search, scanner status, the Vue SPA. Correctly excluded.

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test shows assertions. ✔

**Type consistency:** `register_document`/`process_document`/`add_document` signatures match between Task 8 (definition) and Task 9 (use). `build_document_service`/`ingest_document` signatures match between Task 9 definition and its test monkeypatch targets (`app.api.ingestion.make_embedding_service`). `get_session`, `configure_db`, `create_app`, `session_factory` names are consistent across Tasks 4–9. `_ollama` private-attr assertions in Task 3 match the existing service internals. ✔
