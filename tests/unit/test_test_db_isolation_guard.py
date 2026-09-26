"""The guard that keeps the test suite off the development database."""

import pytest

from tests.support import UnsafeTestDatabaseError, assert_test_database_is_isolated

DEV = "postgresql+psycopg://hms_app:change-me@localhost:5432/hms_dev"


def test_accepts_separate_test_database():
    assert_test_database_is_isolated(DEV, "postgresql+psycopg://hms_app:change-me@localhost:5432/hms_test")


def test_rejects_missing_test_database():
    with pytest.raises(UnsafeTestDatabaseError, match="TEST_DATABASE_URL is not set"):
        assert_test_database_is_isolated(DEV, None)


def test_rejects_test_url_equal_to_dev_url():
    with pytest.raises(UnsafeTestDatabaseError):
        assert_test_database_is_isolated(DEV, DEV)


def test_rejects_name_without_test_suffix():
    with pytest.raises(UnsafeTestDatabaseError, match="must end with '_test'"):
        assert_test_database_is_isolated(DEV, "postgresql+psycopg://hms_app:change-me@localhost/hms_scratch")


def test_rejects_same_database_even_if_named_test():
    dev = "postgresql+psycopg://hms_app:change-me@localhost/hms_test"
    with pytest.raises(UnsafeTestDatabaseError, match="points at the DATABASE_URL"):
        assert_test_database_is_isolated(dev, "postgresql+psycopg://other:change-me@localhost:5432/hms_test")
