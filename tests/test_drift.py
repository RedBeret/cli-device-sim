from tests.helpers import api_json, api_text


def test_drift_injection_is_visible_and_idempotent(sim_env):
    api_url = sim_env["api_url"]

    first = api_json(f"{api_url}/inject-drift", method="POST")
    assert first["status"] == "updated"
    assert first["state"]["dirty"] is True

    running_config = api_text(f"{api_url}/running-config")
    assert "DRIFT-INJECTED-to-203.0.113.77" in running_config

    second = api_json(f"{api_url}/inject-drift", method="POST")
    assert second["status"] == "no_change"

    reset = api_json(f"{api_url}/reset", method="POST")
    assert reset["state"]["dirty"] is False
