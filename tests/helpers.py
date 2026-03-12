from __future__ import annotations

import json
import re
import socket
import time
import urllib.request

import paramiko


PROMPT_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9-]*(?:\(config(?:-if)?\))?[>#]$")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def wait_for_http(url: str, timeout_seconds: float = 10.0) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {url}")


def api_json(url: str, *, method: str = "GET") -> dict:
    request = urllib.request.Request(url=url, method=method)
    with urllib.request.urlopen(request, timeout=5.0) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def api_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5.0) as response:
        return response.read().decode("utf-8")


def open_shell(*, host: str, port: int, username: str = "operator", password: str = "lab-operator"):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
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
    return client, channel


def read_until_prompt(channel: paramiko.Channel, timeout_seconds: float = 5.0) -> str:
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
    raise TimeoutError("Timed out waiting for CLI prompt.")


def strip_echo(transcript: str, command: str | None = None) -> str:
    lines = transcript.replace("\r", "").splitlines()
    if command and lines and lines[0].strip() == command:
        lines = lines[1:]
    return "\n".join(line for line in lines if line).strip()


def send_command(channel: paramiko.Channel, command: str) -> str:
    channel.send(f"{command}\n")
    return read_until_prompt(channel)
