import os
from urllib.parse import urlparse


class UnsafeTestDatabaseError(RuntimeError):
    pass


def validate_test_database_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    database_name = parsed.path.lstrip("/")
    allowed_hosts = {"127.0.0.1", "localhost", "db"}

    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise UnsafeTestDatabaseError("Tests require a PostgreSQL test database URL")
    if parsed.hostname not in allowed_hosts:
        raise UnsafeTestDatabaseError("Test database host must be local or the test compose service")
    if database_name != "shop_test":
        raise UnsafeTestDatabaseError("Refusing to use a database not named shop_test")
    if os.getenv("SHOP_ALLOW_TEST_DATABASE_RESET") != "1":
        raise UnsafeTestDatabaseError("Set SHOP_ALLOW_TEST_DATABASE_RESET=1 to enable test DB setup")
