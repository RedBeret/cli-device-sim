from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

import paramiko

from cli_device_sim.cli_engine import CliSession
from cli_device_sim.config import SimulatorSettings
from cli_device_sim.logging_utils import log_event
from cli_device_sim.state import StateRepository


class _AuthServer(paramiko.ServerInterface):
    def __init__(self, repository: StateRepository, remote_addr: str) -> None:
        self.repository = repository
        self.remote_addr = remote_addr
        self.shell_requested = threading.Event()
        self.username: str | None = None

    def check_auth_password(self, username: str, password: str) -> int:
        success = self.repository.authenticate(username, password)
        self.repository.append_audit(
            actor=username,
            event_type="ssh.auth",
            success=success,
            details={"remote_addr": self.remote_addr},
        )
        if success:
            self.username = username
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_shell_request(self, channel: paramiko.Channel) -> bool:
        self.shell_requested.set()
        return True

    def check_channel_pty_request(
        self,
        channel: paramiko.Channel,
        term: str,
        width: int,
        height: int,
        pixelwidth: int,
        pixelheight: int,
        modes: bytes,
    ) -> bool:
        return True


class SSHServer:
    def __init__(self, settings: SimulatorSettings, repository: StateRepository, logger: logging.Logger) -> None:
        self.settings = settings
        self.repository = repository
        self.logger = logger
        self.host_key = self._load_or_create_host_key(settings.ssh_host_key_path)
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._listening_event = threading.Event()
        self._workers: list[threading.Thread] = []

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._listening_event.clear()
        self._thread = threading.Thread(target=self._serve, name="cli-device-sim-ssh", daemon=True)
        self._thread.start()
        if not self._listening_event.wait(timeout=5):
            raise RuntimeError("SSH server did not become ready in time.")

    def stop(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        for worker in list(self._workers):
            worker.join(timeout=2)

    def is_healthy(self) -> bool:
        return self._listening_event.is_set() and self._thread is not None and self._thread.is_alive()

    def _serve(self) -> None:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.settings.ssh_host, self.settings.ssh_port))
        server_socket.listen(25)
        server_socket.settimeout(1.0)
        self._server_socket = server_socket
        self._listening_event.set()
        log_event(self.logger, logging.INFO, "SSH server listening", host=self.settings.ssh_host, port=self.settings.ssh_port)

        try:
            while not self._stop_event.is_set():
                try:
                    client, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                worker = threading.Thread(
                    target=self._handle_client,
                    args=(client, address[0]),
                    name=f"cli-device-sim-ssh-{address[0]}",
                    daemon=True,
                )
                self._workers.append(worker)
                worker.start()
        finally:
            self._listening_event.clear()
            try:
                server_socket.close()
            except OSError:
                pass

    def _handle_client(self, client_socket: socket.socket, remote_addr: str) -> None:
        transport: paramiko.Transport | None = None
        channel: paramiko.Channel | None = None
        try:
            client_socket.settimeout(self.settings.socket_timeout_seconds)
            transport = paramiko.Transport(client_socket)
            transport.banner_timeout = self.settings.socket_timeout_seconds
            transport.auth_timeout = self.settings.socket_timeout_seconds
            transport.add_server_key(self.host_key)

            auth_server = _AuthServer(self.repository, remote_addr)
            transport.start_server(server=auth_server)
            channel = transport.accept(timeout=self.settings.socket_timeout_seconds)
            if channel is None:
                return
            if not auth_server.shell_requested.wait(timeout=self.settings.socket_timeout_seconds):
                return

            actor = auth_server.username or "unknown"
            self.repository.append_audit(
                actor=actor,
                event_type="ssh.session",
                success=True,
                details={"remote_addr": remote_addr, "status": "opened"},
            )

            session = CliSession(self.repository, actor=actor, remote_addr=remote_addr)
            channel.settimeout(self.settings.channel_timeout_seconds)
            channel.send("Synthetic CLI Device Simulator\r\n")
            channel.send("Training-only target with synthetic state.\r\n\r\n")
            channel.send(session.prompt)

            buffer = ""
            while not self._stop_event.is_set():
                try:
                    data = channel.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    break
                text = data.decode("utf-8", errors="ignore")
                for char in text:
                    if char in "\r\n":
                        channel.send("\r\n")
                        result = session.execute(buffer)
                        if result.output:
                            channel.send(result.output.replace("\n", "\r\n"))
                            channel.send("\r\n")
                        buffer = ""
                        if result.close_session:
                            return
                        channel.send(session.prompt)
                    elif char in {"\b", "\x7f"}:
                        buffer = buffer[:-1]
                    elif ord(char) >= 32:
                        buffer += char
                        channel.send(char)
        except paramiko.SSHException as exc:
            log_event(self.logger, logging.WARNING, "SSH transport error", error=str(exc), remote_addr=remote_addr)
        finally:
            if channel is not None:
                try:
                    channel.close()
                except OSError:
                    pass
            if transport is not None:
                transport.close()
            try:
                client_socket.close()
            except OSError:
                pass

    @staticmethod
    def _load_or_create_host_key(path: Path) -> paramiko.RSAKey:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return paramiko.RSAKey.from_private_key_file(str(path))
        key = paramiko.RSAKey.generate(bits=2048)
        key.write_private_key_file(str(path))
        return key

