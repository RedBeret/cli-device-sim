from __future__ import annotations

import pytest

from cli_device_sim.config import SimulatorSettings
from cli_device_sim.runtime import SimulatorRuntime
from tests.helpers import free_port, wait_for_http


@pytest.fixture()
def sim_env(tmp_path):
    settings = SimulatorSettings(
        api_host="127.0.0.1",
        api_port=free_port(),
        ssh_host="127.0.0.1",
        ssh_port=free_port(),
        db_path=tmp_path / "sim.db",
        ssh_host_key_path=tmp_path / "host_key.pem",
        log_level="WARNING",
    )
    runtime = SimulatorRuntime(settings)
    runtime.start()
    wait_for_http(f"http://127.0.0.1:{settings.api_port}/healthz")
    try:
        yield {
            "runtime": runtime,
            "settings": settings,
            "api_url": f"http://127.0.0.1:{settings.api_port}",
        }
    finally:
        runtime.stop()

