import pytest

from shop_api.testing import UnsafeTestDatabaseError, validate_test_database_url


def test_accepts_explicit_local_test_database():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SHOP_ALLOW_TEST_DATABASE_RESET", "1")
        validate_test_database_url(
            "postgresql+psycopg://shop:secret@127.0.0.1:55445/shop_test"
        )


def test_refuses_development_database():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SHOP_ALLOW_TEST_DATABASE_RESET", "1")
        with pytest.raises(UnsafeTestDatabaseError):
            validate_test_database_url(
                "postgresql+psycopg://shop:secret@127.0.0.1:55444/shop_dev"
            )


@pytest.mark.parametrize("database", ["shop_test_backup", "shop_test_demo"])
def test_refuses_ambiguous_test_database_name(database):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SHOP_ALLOW_TEST_DATABASE_RESET", "1")
        with pytest.raises(UnsafeTestDatabaseError):
            validate_test_database_url(f"postgresql+psycopg://shop:secret@127.0.0.1:55445/{database}")


def test_refuses_non_local_database_host():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("SHOP_ALLOW_TEST_DATABASE_RESET", "1")
        with pytest.raises(UnsafeTestDatabaseError):
            validate_test_database_url(
                "postgresql+psycopg://shop:secret@example.com/shop_test"
            )


def test_refuses_reset_without_explicit_opt_in():
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.delenv("SHOP_ALLOW_TEST_DATABASE_RESET", raising=False)
        with pytest.raises(UnsafeTestDatabaseError):
            validate_test_database_url(
                "postgresql+psycopg://shop:secret@127.0.0.1:55445/shop_test"
            )
