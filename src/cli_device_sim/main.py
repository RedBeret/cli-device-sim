from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import paramiko
import typer

from cli_device_sim.config import SimulatorSettings
from cli_device_sim.runtime import SimulatorRuntime

app = typer.Typer(no_args_is_help=True)
PROMPT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?:\(config(?:-if)?\))?[>#]$")


def _http_json(url: str, *, method: str = "GET", timeout: float = 3.0) -> dict:
    request = urllib.request.Request(url=url, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _wait_for_health(url: str, *, retries: int, delay_seconds: float, timeout: float) -> None:
    current_delay = delay_seconds
    for attempt in range(1, retries + 1):
        try:
            payload = _http_json(url, timeout=timeout)
            if payload.get("status") == "ok":
                return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        if attempt == retries:
            break
        time.sleep(current_delay)
        current_delay *= 2
    raise typer.Exit(code=1)


def _read_until_prompt(channel: paramiko.Channel, *, timeout_seconds: float = 5.0) -> str:
    deadline = time.time() + timeout_seconds
    buffer = ""
    while time.time() < deadline:
        try:
            chunk = channel.recv(4096)
        except Exception:
            chunk = b""
        if chunk:
            buffer += chunk.decode("utf-8", errors="ignore").replace("\r", "")
            lines = [line for line in buffer.split("\n") if line]
            if lines and PROMPT_PATTERN.search(lines[-1]):
                return buffer
        else:
            time.sleep(0.05)
    raise RuntimeError("Timed out while waiting for CLI prompt.")


def _strip_transcript(transcript: str, command: str | None = None) -> str:
    lines = transcript.replace("\r", "").splitlines()
    if command and lines and lines[0].strip() == command:
        lines = lines[1:]
    return "\n".join(line for line in lines if line).strip()


@app.command()
def serve(
    api_host: str = "0.0.0.0",
    api_port: int = 8080,
    ssh_host: str = "0.0.0.0",
    ssh_port: int = 2222,
    db_path: Path = Path("data/sim.db"),
    ssh_host_key_path: Path = Path("data/host_key.pem"),
    log_level: str = "INFO",
) -> None:
    settings = SimulatorSettings(
        api_host=api_host,
        api_port=api_port,
        ssh_host=ssh_host,
        ssh_port=ssh_port,
        db_path=db_path,
        ssh_host_key_path=ssh_host_key_path,
        log_level=log_level,
    )
    runtime = SimulatorRuntime(settings)
    runtime.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop()


@app.command()
def healthcheck(
    url: str = "http://127.0.0.1:8080/healthz",
    retries: int = 5,
    delay_seconds: float = 0.25,
    timeout: float = 2.0,
) -> None:
    _wait_for_health(url, retries=retries, delay_seconds=delay_seconds, timeout=timeout)
    typer.echo(f"healthy: {url}")


@app.command("demo-client")
def demo_client(
    ssh_host: str = "127.0.0.1",
    ssh_port: int = 2222,
    api_url: str = "http://127.0.0.1:8080",
    username: str = "operator",
    password: str = "lab-operator",
    probe_only: bool = False,
    reset_first: bool = False,
) -> None:
    api_url = api_url.rstrip("/")
    _wait_for_health(f"{api_url}/healthz", retries=6, delay_seconds=0.25, timeout=2.0)
    if reset_first:
        reset_payload = _http_json(f"{api_url}/reset", method="POST", timeout=5.0)
        typer.echo(f"Reset: {reset_payload['message']}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=ssh_host,
        port=ssh_port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=5,
        banner_timeout=5,
        auth_timeout=5,
    )

    channel = client.invoke_shell()
    channel.settimeout(1.0)
    initial = _strip_transcript(_read_until_prompt(channel))
    typer.echo(initial)

    if probe_only:
        typer.echo("SSH login probe succeeded.")
        channel.close()
        client.close()
        return

    commands = [
        "enable",
        "show version",
        "configure terminal",
        "hostname LAB-EDGE-DEMO",
        "interface GigabitEthernet0/2",
        "description Demo-port-203.0.113.55",
        "no shutdown",
        "end",
        "write memory",
        "show running-config",
    ]
    for command in commands:
        typer.echo(f"\n$ {command}")
        channel.send(f"{command}\n")
        transcript = _strip_transcript(_read_until_prompt(channel), command)
        typer.echo(transcript)

    state = _http_json(f"{api_url}/state", timeout=5.0)
    typer.echo("\nRecent audit entries:")
    for entry in reversed(state["recent_audit"][:5]):
        typer.echo(
            f"- {entry['happened_at']} | {entry['actor']} | {entry['event_type']} | success={entry['success']}"
        )

    channel.close()
    client.close()


def main() -> None:
    app()

