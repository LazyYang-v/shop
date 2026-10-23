"""Database-free maintenance boundary regressions (also runnable outside conftest)."""

import asyncio
from datetime import UTC, datetime, timedelta

from shop_api.customer_service import SafeLogWriter
from shop_api.customer_service_maintenance import CustomerServiceMaintenance


class UnavailableDatabase:
    def __call__(self):
        raise ConnectionError("synthetic database outage")

    def begin(self):
        raise ConnectionError("synthetic database outage")


def test_startup_and_hourly_log_expiry_survive_database_outage(tmp_path):
    now = datetime(2026, 10, 23, tzinfo=UTC)
    elapsed = [0.0]
    writer = SafeLogWriter(str(tmp_path))
    tmp_path.chmod(0o700)
    expired = tmp_path / "customer-service-2026-10-16.jsonl"
    expired.write_text("{}\n")
    upcoming = tmp_path / "customer-service-2026-10-17.jsonl"
    upcoming.write_text("{}\n")
    maintenance = CustomerServiceMaintenance(UnavailableDatabase(), writer, lambda: now,
                                             monotonic=lambda: elapsed[0])
    asyncio.run(maintenance.run_due())
    assert not expired.exists()
    assert upcoming.exists()
    now += timedelta(days=1)
    elapsed[0] = 3600
    asyncio.run(maintenance.run_due())
    assert not upcoming.exists()


def test_file_deletion_failure_retries_next_scan(tmp_path, monkeypatch):
    from pathlib import Path

    now = datetime(2026, 10, 23, tzinfo=UTC)
    tmp_path.chmod(0o700)
    expired = tmp_path / "customer-service-2026-10-16.jsonl"
    expired.write_text("{}\n")
    unlink = Path.unlink

    def unavailable(path, *args, **kwargs):
        if path == expired:
            raise PermissionError("synthetic file failure")
        return unlink(path, *args, **kwargs)

    elapsed = [0.0]
    maintenance = CustomerServiceMaintenance(UnavailableDatabase(), SafeLogWriter(str(tmp_path)),
                                             lambda: now, monotonic=lambda: elapsed[0])
    monkeypatch.setattr(Path, "unlink", unavailable)
    asyncio.run(maintenance.run_due())
    assert expired.exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    elapsed[0] = 30
    asyncio.run(maintenance.run_due())
    assert not expired.exists()


def test_failed_log_prune_retries_next_scan_without_waiting_an_hour(tmp_path):
    now = datetime(2026, 10, 23, tzinfo=UTC)
    elapsed = [0.0]
    directory = tmp_path / "logs"
    maintenance = CustomerServiceMaintenance(UnavailableDatabase(), SafeLogWriter(str(directory)),
                                             lambda: now, monotonic=lambda: elapsed[0])
    asyncio.run(maintenance.run_due())
    directory.mkdir(mode=0o700)
    expired = directory / "customer-service-2026-10-16.jsonl"
    expired.write_text("{}\n")
    elapsed[0] = 30
    asyncio.run(maintenance.run_due())
    assert not expired.exists()
