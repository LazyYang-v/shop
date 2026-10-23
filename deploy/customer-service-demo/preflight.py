"""Validate the candidate with synthetic values; never starts Docker resources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    directory = Path(__file__).resolve().parent
    fixture = directory / "products.v1.json"
    products = json.loads(fixture.read_text())
    assert 1 <= len(products) <= 20
    assert len({product["id"] for product in products}) == len(products)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("COMPOSE_", "DEMO_", "SHOP_"))}
    environment.update(
        SHOP_POSTGRES_IMAGE="postgres@sha256:" + "0" * 64,
        DEMO_SHOP_API_IMAGE="shop-api@sha256:" + "1" * 64,
        DEMO_SHOP_DB_PASSWORD="syntheticOnly12345678901234567890",
        DEMO_WEKNORA_DB_PASSWORD="syntheticOnly12345678901234567890",
        DEMO_WEKNORA_JWT_SECRET="syntheticOnly12345678901234567890",
        DEMO_WEKNORA_CONFIG="/nonexistent/synthetic-config.yaml",
    )
    command = ["docker", "compose", "--env-file", os.devnull,
               "-f", str(directory / "compose.yaml")]

    def configuration(profiles):
        result = subprocess.run(command + profiles + ["config", "--format", "json"],
                                env=environment, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError("Synthetic Compose parsing failed; no resources started")
        return json.loads(result.stdout)

    assert not configuration([]).get("services")
    candidate = configuration(["--profile", "*"])
    assert candidate["name"] == "shop-customer-service-demo"
    services = candidate["services"]
    assert set(services) == {"shop-db", "shop-api", "postgres", "redis", "docreader", "app", "mcp-proxy"}
    for service in services.values():
        assert service["profiles"] and service["logging"]["driver"] == "none"
        assert not service.get("container_name") and not service.get("env_file")
        for port in service.get("ports", []):
            assert port["host_ip"] == "127.0.0.1"
        for volume in service.get("volumes", []):
            if volume["type"] == "bind":
                assert volume["read_only"] and not volume.get("bind", {}).get("create_host_path", False)
    assert all(network["internal"] and not network.get("external") for network in candidate["networks"].values())
    assert all(not volume.get("external") for volume in candidate["volumes"].values())
    api = services["shop-api"]
    assert api["profiles"] == ["pending-demo-guards"]
    assert "--no-proxy-headers" in api["command"] and "--no-access-log" in api["command"]
    settings = api["environment"]
    assert settings["SHOP_REGISTRATION_ENABLED"] == "false"
    assert settings["SHOP_CUSTOMER_SERVICE_DEMO_MODE"] == "1"
    assert settings["SHOP_CUSTOMER_SERVICE_FIXTURE_SHA256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert set(settings["SHOP_CUSTOMER_SERVICE_BUYER_IDS"].split(",")) == {
        "de100000-0000-4000-8000-000000000001", "de100000-0000-4000-8000-000000000002"}
    assert "shop_customer_service_demo" in settings["SHOP_DATABASE_URL"]
    assert "shop-api" not in configuration(["--profile", "pending-demo-gates"])["services"]
    print("Preflight passed: synthetic configuration only; default zero services; no resources started.")


if __name__ == "__main__":
    main()
