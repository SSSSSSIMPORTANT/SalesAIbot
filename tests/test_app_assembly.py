"""Regression checks for router registration and per-application dependencies."""

import json
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base, enable_foreign_keys, get_db
from app.knowledge import KnowledgeRepository
from app.llm import MockModelGateway
from app.main import create_app


def make_repository(tmp_path, name, price_cents):
    path = tmp_path / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                "products": [
                    {
                        "knowledge_id": f"synthetic-{name}-terms",
                        "revision": "v1",
                        "product_id": "synthetic-course",
                        "name": "Synthetic course",
                        "status": "published",
                        "price_cents": price_cents,
                        "trial_available": None,
                        "refund_policy": None,
                        "source": "Synthetic assembly test data",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return KnowledgeRepository(path)


@pytest.fixture
def assembly_engine(tmp_path):
    path = tmp_path / "assembly.db"
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    event.listen(engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def override_database(application, engine):
    def override_get_db():
        with Session(engine) as session:
            yield session

    application.dependency_overrides[get_db] = override_get_db


def iter_api_routes(routes):
    """Walk direct routes and FastAPI's lazy included-router containers."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            # This project registers full-path routers without extra prefixes.
            # Walking every container (rather than deduplicating) also detects
            # accidentally including the same router more than once.
            yield from iter_api_routes(route.original_router.routes)


def test_application_settings_are_isolated(tmp_path):
    repository = make_repository(tmp_path, "settings", 19900)
    first = create_app(
        Settings(app_name="Assembly A", app_env="test"),
        knowledge_repository=repository,
    )
    second = create_app(
        Settings(app_name="Assembly B", app_env="development"),
        knowledge_repository=repository,
    )

    with TestClient(first) as first_client, TestClient(second) as second_client:
        for client, name, environment in [
            (first_client, "Assembly A", "test"),
            (second_client, "Assembly B", "development"),
            (first_client, "Assembly A", "test"),
        ]:
            response = client.get("/health")
            assert response.status_code == 200
            assert response.json()["app"] == name
            assert response.json()["environment"] == environment


def test_application_gateways_and_repositories_are_isolated(
    tmp_path, assembly_engine, as_test_operator
):
    class RecordingGateway(MockModelGateway):
        def __init__(self, name):
            self.name = name
            self.tool_requests = 0
            self.generations = 0

        def request_product_tool(self, **kwargs):
            self.tool_requests += 1
            return super().request_product_tool(**kwargs)

        def generate(self, **kwargs):
            self.generations += 1
            return (
                super().generate(**kwargs).model_copy(update={"model_name": self.name})
            )

    first_gateway = RecordingGateway("assembly-model-a")
    second_gateway = RecordingGateway("assembly-model-b")
    first = create_app(
        Settings(app_env="test"),
        model_gateway=first_gateway,
        knowledge_repository=make_repository(tmp_path, "a", 20100),
    )
    second = create_app(
        Settings(app_env="test"),
        model_gateway=second_gateway,
        knowledge_repository=make_repository(tmp_path, "b", 30200),
    )
    override_database(first, assembly_engine)
    override_database(second, assembly_engine)

    try:
        with TestClient(first) as first_client, TestClient(second) as second_client:
            as_test_operator(first_client)
            as_test_operator(second_client)
            created = first_client.post(
                "/conversations",
                json={"customer_name": "Synthetic assembly customer"},
            )
            assert created.status_code == 201
            url = f"/conversations/{created.json()['id']}"
            submitted = first_client.post(
                f"{url}/messages",
                json={
                    "request_key": "assembly-source",
                    "based_on_version": 0,
                    "actor": "customer",
                    "text": "What is the price?",
                },
            )
            assert submitted.status_code == 201

            for client, label, price in [
                (first_client, "a", 20100),
                (second_client, "b", 30200),
                (first_client, "a", 20100),
            ]:
                response = client.post(
                    f"{url}/reply-preview",
                    json={
                        "based_on_version": 1,
                        "product_id": "synthetic-course",
                    },
                )
                assert response.status_code == 200
                data = response.json()
                assert data["reply"]["model_name"] == f"assembly-model-{label}"
                assert data["reply"]["knowledge_id"] == f"synthetic-{label}-terms"
                assert data["retrieved_knowledge"]["price_cents"] == price
                assert f"{price // 100}.00" in data["reply"]["text"]

        assert first_gateway.tool_requests == first_gateway.generations == 2
        assert second_gateway.tool_requests == second_gateway.generations == 1
    finally:
        first.dependency_overrides.clear()
        second.dependency_overrides.clear()


def test_registered_routes_preserve_public_contract(tmp_path):
    expected = {
        ("GET", "/conversations/{conversation_id}/handoffs", "get_handoffs"),
        (
            "PUT",
            "/conversations/{conversation_id}/messages/{message_id}/handoff",
            "put_handoff",
        ),
        (
            "PUT",
            "/conversations/{conversation_id}/messages/{message_id}/handoff/resolution",
            "put_handoff_resolution",
        ),
        ("GET", "/health", "health"),
        ("POST", "/auth/login", "login"),
        ("GET", "/auth/me", "get_me"),
        ("POST", "/auth/logout", "logout"),
        ("POST", "/messages/preview", "preview_message"),
        ("POST", "/customers", "create_customer"),
        ("GET", "/customers/{customer_id}", "get_customer"),
        ("POST", "/conversations", "create_conversation"),
        ("GET", "/conversations", "list_conversations"),
        ("GET", "/conversations/{conversation_id}", "get_conversation"),
        ("PUT", "/conversations/{conversation_id}/assistance", "update_assistance"),
        ("POST", "/conversations/{conversation_id}/messages", "create_message"),
        ("GET", "/conversations/{conversation_id}/messages", "list_messages"),
        ("POST", "/conversations/{conversation_id}/reply-preview", "preview_reply"),
        (
            "POST",
            "/conversations/{conversation_id}/screenshots/preview",
            "preview_screenshot",
        ),
        ("POST", "/conversations/{conversation_id}/facts", "confirm_fact"),
        ("GET", "/conversations/{conversation_id}/facts", "get_facts"),
        (
            "POST",
            "/conversations/{conversation_id}/memory-candidates",
            "extract_memory",
        ),
        (
            "POST",
            "/conversations/{conversation_id}/facts/{fact_id}/revoke",
            "revoke_fact",
        ),
        (
            "GET",
            "/conversations/{conversation_id}/memory-recall",
            "get_recalled_memory",
        ),
        ("POST", "/conversations/{conversation_id}/suggestions", "create_suggestion"),
        ("GET", "/conversations/{conversation_id}/suggestions", "list_suggestions"),
        (
            "GET",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}",
            "get_suggestion",
        ),
        (
            "GET",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/outcome",
            "get_suggestion_outcome",
        ),
        (
            "GET",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/validity",
            "get_suggestion_validity",
        ),
        (
            "POST",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-ready",
            "prepare_suggestion_copy",
        ),
        (
            "POST",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-events",
            "report_suggestion_copy",
        ),
        (
            "GET",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/copy-events",
            "list_suggestion_copy_events",
        ),
        (
            "GET",
            "/conversations/{conversation_id}/generation-requests/by-key",
            "get_generation_request",
        ),
        ("GET", "/products", "list_products"),
        (
            "POST",
            "/conversations/{conversation_id}/screenshots/transcribe",
            "transcribe_screenshot",
        ),
        (
            "POST",
            "/conversations/{conversation_id}/screenshots/import",
            "import_screenshot",
        ),
        (
            "PUT",
            "/conversations/{conversation_id}/suggestions/{suggestion_id}/abandonment",
            "put_suggestion_abandonment",
        ),
    }
    application = create_app(
        Settings(app_env="test"),
        knowledge_repository=make_repository(tmp_path, "routes", 19900),
    )
    registered = [
        (method, route.path, route.name)
        for route in iter_api_routes(application.routes)
        for method in route.methods
    ]

    assert set(registered) == expected
    assert len(registered) == len(expected)
    method_paths = [(method, path) for method, path, _ in registered]
    assert len(method_paths) == len(set(method_paths))

    schema = application.openapi()
    operation_ids = []
    for method, path, name in expected:
        # These are the operation IDs published before moving the endpoints.
        original_id = re.sub(r"\W", "_", f"{name}{path}")
        original_id += f"_{method.lower()}"
        operation_id = schema["paths"][path][method.lower()]["operationId"]
        assert operation_id == original_id
        operation_ids.append(operation_id)

    assert len(operation_ids) == len(set(operation_ids))
