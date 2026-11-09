from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.api.auth import require_operator
from app.config import Settings
from app.database import Base, OperatorAccount, enable_foreign_keys, get_db
from app.main import create_app
from app.knowledge import DEFAULT_CATALOG_PATH, KnowledgeRepository
from app.schemas.auth import OperatorIdentity


@pytest.fixture
def anonymous_client(tmp_path):
    # 每个测试使用自己的临时数据库。
    database_path = tmp_path / "test.db"

    test_engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    event.listen(test_engine, "connect", enable_foreign_keys)
    Base.metadata.create_all(test_engine)

    def override_get_db():
        with Session(test_engine) as session:
            yield session

    catalog_path = tmp_path / "products.json"
    catalog_path.write_bytes(DEFAULT_CATALOG_PATH.read_bytes())

    application = create_app(
        Settings(app_env="test"),
        knowledge_repository=KnowledgeRepository(catalog_path),
    )

    # 测试请求使用临时数据库，替换正常运行时的数据库依赖。
    application.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(application) as test_client:
            test_client.headers["Origin"] = str(test_client.base_url).rstrip("/")
            yield test_client
    finally:
        application.dependency_overrides.clear()
        test_engine.dispose()


@pytest.fixture
def as_test_operator():
    def apply(test_client):
        identity = OperatorIdentity(id="0" * 32, username="test-operator")
        overrides = test_client.app.dependency_overrides
        with closing(overrides[get_db]()) as sessions:
            db = next(sessions)
            if db.get(OperatorAccount, identity.id) is None:
                db.add(OperatorAccount(
                    id=identity.id,
                    username=identity.username,
                    password_hash="unused in business tests",
                ))
                db.commit()
        overrides[require_operator] = lambda: identity
        test_client.headers["Origin"] = str(test_client.base_url).rstrip("/")
        return identity

    return apply


@pytest.fixture
def client(anonymous_client, as_test_operator):
    as_test_operator(anonymous_client)
    return anonymous_client
