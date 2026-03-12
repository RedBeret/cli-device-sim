from cli_device_sim.config import SimulatorSettings
from cli_device_sim.runtime import SimulatorRuntime
from tests.helpers import free_port, open_shell, read_until_prompt, send_command, strip_echo, wait_for_http


def test_config_save_and_reload_persists_across_restart(tmp_path):
    db_path = tmp_path / "sim.db"
    host_key_path = tmp_path / "host_key.pem"

    first_runtime = SimulatorRuntime(
        SimulatorSettings(
            api_host="127.0.0.1",
            api_port=free_port(),
            ssh_host="127.0.0.1",
            ssh_port=free_port(),
            db_path=db_path,
            ssh_host_key_path=host_key_path,
            log_level="WARNING",
        )
    )
    first_runtime.start()
    wait_for_http(f"http://127.0.0.1:{first_runtime.settings.api_port}/healthz")
    try:
        client, channel = open_shell(host="127.0.0.1", port=first_runtime.settings.ssh_port)
        try:
            read_until_prompt(channel)
            send_command(channel, "enable")
            send_command(channel, "configure terminal")
            send_command(channel, "hostname LAB-EDGE-PERSIST")
            send_command(channel, "interface GigabitEthernet0/2")
            send_command(channel, "description Persisted-port-203.0.113.88")
            send_command(channel, "no shutdown")
            send_command(channel, "end")
            write_output = strip_echo(send_command(channel, "write memory"), "write memory")
            assert "[OK]" in write_output
        finally:
            channel.close()
            client.close()
    finally:
        first_runtime.stop()

    second_runtime = SimulatorRuntime(
        SimulatorSettings(
            api_host="127.0.0.1",
            api_port=free_port(),
            ssh_host="127.0.0.1",
            ssh_port=free_port(),
            db_path=db_path,
            ssh_host_key_path=host_key_path,
            log_level="WARNING",
        )
    )
    second_runtime.start()
    wait_for_http(f"http://127.0.0.1:{second_runtime.settings.api_port}/healthz")
    try:
        client, channel = open_shell(host="127.0.0.1", port=second_runtime.settings.ssh_port)
        try:
            prompt = read_until_prompt(channel)
            assert "LAB-EDGE-PERSIST>" in prompt
            send_command(channel, "enable")
            startup_config = strip_echo(send_command(channel, "show startup-config"), "show startup-config")
            assert "hostname LAB-EDGE-PERSIST" in startup_config
            assert "description Persisted-port-203.0.113.88" in startup_config
        finally:
            channel.close()
            client.close()
    finally:
        second_runtime.stop()
