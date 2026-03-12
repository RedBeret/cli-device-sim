from __future__ import annotations

from cli_device_sim.models import DeviceConfig


def render_config(config: DeviceConfig) -> str:
    lines = [
        "version 1.0",
        "service timestamps log datetime",
        f"hostname {config.hostname}",
    ]
    for user in sorted(config.users, key=lambda item: item.username):
        lines.append(f"username {user.username} secret {user.secret}")

    for interface in config.interfaces:
        lines.append(f"interface {interface.name}")
        if interface.description:
            lines.append(f" description {interface.description}")
        if interface.shutdown:
            lines.append(" shutdown")
        else:
            lines.append(" no shutdown")
        lines.append("!")

    lines.append("end")
    return "\n".join(lines)


def render_interfaces_summary(config: DeviceConfig) -> str:
    lines = [
        "Interface              Admin  Oper  IPv4            Description",
        "---------------------  -----  ----  --------------  ------------------------------",
    ]
    for interface in config.interfaces:
        admin_status = "down" if interface.shutdown else "up"
        oper_status = "down" if interface.shutdown else "up"
        lines.append(
            f"{interface.name:<21}  {admin_status:<5}  {oper_status:<4}  {interface.ipv4_address:<14}  {interface.description or '-'}"
        )
    return "\n".join(lines)


def render_version(config: DeviceConfig, *, dirty: bool, running_revision: int, startup_revision: int) -> str:
    config_state = "running differs from startup" if dirty else "running and startup are in sync"
    return "\n".join(
        [
            "Synthetic Network OS Software, cli-device-sim",
            f"Model Number: {config.model}",
            f"Hostname: {config.hostname}",
            f"Serial Number: {config.serial_number}",
            "Management Loopback: 192.0.2.1",
            f"Config State: {config_state}",
            f"Running Revision: {running_revision}",
            f"Startup Revision: {startup_revision}",
            f"Software Version: {config.version}",
        ]
    )
