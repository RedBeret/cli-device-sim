from tests.helpers import open_shell, read_until_prompt, send_command, strip_echo


def test_prompt_transitions_follow_exec_privileged_and_config_modes(sim_env):
    settings = sim_env["settings"]
    client, channel = open_shell(host="127.0.0.1", port=settings.ssh_port)
    try:
        read_until_prompt(channel)

        enable_output = strip_echo(send_command(channel, "enable"), "enable")
        assert enable_output.endswith("LAB-EDGE-01#")

        config_output = strip_echo(send_command(channel, "configure terminal"), "configure terminal")
        assert config_output.endswith("LAB-EDGE-01(config)#")

        interface_output = strip_echo(send_command(channel, "interface GigabitEthernet0/2"), "interface GigabitEthernet0/2")
        assert interface_output.endswith("LAB-EDGE-01(config-if)#")

        end_output = strip_echo(send_command(channel, "end"), "end")
        assert end_output.endswith("LAB-EDGE-01#")

        disable_output = strip_echo(send_command(channel, "disable"), "disable")
        assert disable_output.endswith("LAB-EDGE-01>")
    finally:
        channel.close()
        client.close()
