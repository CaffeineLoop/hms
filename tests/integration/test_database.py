"""PostgreSQL connectivity, SQLAlchemy sessions, and test-database isolation."""

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import load_settings
from app.db.session import build_session_factory, get_db

pytestmark = pytest.mark.integration


def test_engine_connects_to_postgresql(test_engine):
    with test_engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        version = connection.execute(text("SHOW server_version")).scalar_one()
    assert version


def test_engine_uses_psycopg3_driver(test_engine):
    assert test_engine.dialect.name == "postgresql"
    assert test_engine.dialect.driver == "psycopg"


def test_session_can_be_created_and_queried(test_engine):
    session_factory = build_session_factory(test_engine)
    with session_factory() as session:
        assert isinstance(session, Session)
        assert session.execute(text("SELECT 40 + 2")).scalar_one() == 42


def test_session_rolls_back_uncommitted_work(test_engine):
    session_factory = build_session_factory(test_engine)
    with session_factory() as session:
        session.execute(text("CREATE TEMP TABLE stage0_probe (id int)"))
        session.execute(text("INSERT INTO stage0_probe VALUES (1)"))
        session.rollback()
        exists = session.execute(text("SELECT to_regclass('pg_temp.stage0_probe')")).scalar_one()
    assert exists is None


def test_get_db_dependency_yields_and_closes_session(client):
    request = SimpleNamespace(app=client.app)  # get_db only reads request.app.state
    generator = get_db(request)
    session = next(generator)
    assert session.execute(text("SELECT 1")).scalar_one() == 1
    with pytest.raises(StopIteration):
        next(generator)
    assert not session.in_transaction()


def test_connected_to_isolated_test_database(test_engine, test_settings):
    with test_engine.connect() as connection:
        current = connection.execute(text("SELECT current_database()")).scalar_one()
    assert current == test_settings.database_url_parsed.database
    assert current.endswith("_test")
    dev_database = load_settings().database_url_parsed.database
    assert current != dev_database
