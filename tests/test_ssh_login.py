from tests.helpers import open_shell, read_until_prompt


def test_ssh_login_shows_banner_and_prompt(sim_env):
    settings = sim_env["settings"]
    client, channel = open_shell(host="127.0.0.1", port=settings.ssh_port)
    try:
        transcript = read_until_prompt(channel)
        assert "Synthetic CLI Device Simulator" in transcript
        assert "LAB-EDGE-01>" in transcript
    finally:
        channel.close()
        client.close()
