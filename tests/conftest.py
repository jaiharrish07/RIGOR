"""Shared test fixtures.

Each test runs inside a transaction that is rolled back afterwards, so tests
never see each other's rows and the suite can be re-run without cleanup.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(settings.test_database_url, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine) -> Session:
    """Fresh session per test, rolled back at the end.

    Bound to an explicit connection-level transaction so that database-level
    ON DELETE rules still fire inside the test, but nothing is persisted.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        # A test that provoked an IntegrityError leaves the transaction already
        # deassociated, so roll the session back first and only unwind the outer
        # transaction if it is still live.
        session.rollback()
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client wired to the test database session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
