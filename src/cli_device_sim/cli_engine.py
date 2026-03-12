from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from cli_device_sim.models import DeviceConfig
from cli_device_sim.rendering import render_interfaces_summary, render_version
from cli_device_sim.state import StateRepository, sanitize_command


Mode = Literal["exec", "privileged", "config", "config-if"]


@dataclass(slots=True)
class CommandResult:
    output: str = ""
    close_session: bool = False
    success: bool = True
    mutated: bool = False


class CliSession:
    def __init__(self, repository: StateRepository, *, actor: str, remote_addr: str) -> None:
        self.repository = repository
        self.actor = actor
        self.remote_addr = remote_addr
        self.mode: Mode = "exec"
        self.current_interface: str | None = None
        running = repository.get_snapshot("running").config
        self.terminal_length = running.terminal_length_default
        self.hostname = running.hostname

    @property
    def prompt(self) -> str:
        if self.mode == "exec":
            return f"{self.hostname}>"
        if self.mode == "privileged":
            return f"{self.hostname}#"
        if self.mode == "config":
            return f"{self.hostname}(config)#"
        return f"{self.hostname}(config-if)#"

    def execute(self, raw_command: str) -> CommandResult:
        command = " ".join(raw_command.strip().split())
        if not command:
            return CommandResult()

        try:
            result = self._dispatch(command)
        except (ValidationError, ValueError) as exc:
            result = CommandResult(output=f"% Validation failed: {exc}", success=False)

        self.repository.append_audit(
            actor=self.actor,
            event_type="cli.command",
            success=result.success,
            details={
                "command": sanitize_command(command),
                "mode": self.mode,
                "mutated": result.mutated,
                "remote_addr": self.remote_addr,
            },
        )
        return result

    def _dispatch(self, command: str) -> CommandResult:
        lowered = command.lower()
        if lowered in {"quit", "logout"}:
            return CommandResult(output="Connection closed by foreign host.", close_session=True)
        if lowered == "exit":
            return self._handle_exit()
        if lowered == "enable":
            return self._handle_enable()
        if lowered == "disable":
            return self._handle_disable()
        if lowered == "terminal length 0":
            return self._handle_terminal_length()
        if lowered == "show version":
            return self._handle_show_version()
        if lowered == "show running-config":
            return self._handle_show_config("running")
        if lowered == "show startup-config":
            return self._handle_show_config("startup")
        if lowered == "show interfaces summary":
            return self._handle_show_interfaces()
        if lowered == "configure terminal":
            return self._handle_configure_terminal()
        if lowered == "end":
            return self._handle_end()
        if lowered == "write memory":
            return self._handle_write_memory()
        if lowered.startswith("hostname "):
            return self._handle_hostname(command)
        if lowered.startswith("username "):
            return self._handle_username(command)
        if lowered.startswith("interface "):
            return self._handle_interface(command)
        if lowered.startswith("description "):
            return self._handle_description(command)
        if lowered == "no shutdown":
            return self._handle_shutdown(enabled=True)
        if lowered == "shutdown":
            return self._handle_shutdown(enabled=False)
        return CommandResult(output=f"% Invalid command: {command}", success=False)

    def _handle_exit(self) -> CommandResult:
        if self.mode == "config-if":
            self.mode = "config"
            self.current_interface = None
            return CommandResult()
        if self.mode == "config":
            self.mode = "privileged"
            return CommandResult()
        return CommandResult(output="Connection closed by foreign host.", close_session=True)

    def _handle_enable(self) -> CommandResult:
        if self.mode == "exec":
            self.mode = "privileged"
            return CommandResult()
        if self.mode == "privileged":
            return CommandResult(output="Already in privileged mode.")
        return CommandResult(output="% 'enable' is not available in configuration modes.", success=False)

    def _handle_disable(self) -> CommandResult:
        if self.mode == "privileged":
            self.mode = "exec"
            return CommandResult()
        return CommandResult(output="% 'disable' requires privileged EXEC mode.", success=False)

    def _handle_terminal_length(self) -> CommandResult:
        if self.mode not in {"exec", "privileged"}:
            return CommandResult(output="% 'terminal length 0' is only available in EXEC modes.", success=False)
        self.terminal_length = 0
        return CommandResult(output="Terminal length set to 0.")

    def _handle_show_version(self) -> CommandResult:
        if self.mode not in {"exec", "privileged"}:
            return CommandResult(output="% 'show version' is only available in EXEC modes.", success=False)
        running = self.repository.get_snapshot("running")
        startup = self.repository.get_snapshot("startup")
        dirty = running.config.model_dump() != startup.config.model_dump()
        self.hostname = running.config.hostname
        return CommandResult(
            output=render_version(
                running.config,
                dirty=dirty,
                running_revision=running.revision,
                startup_revision=startup.revision,
            )
        )

    def _handle_show_config(self, kind: str) -> CommandResult:
        if self.mode != "privileged":
            return CommandResult(output="% Privileged EXEC mode is required. Use 'enable' first.", success=False)
        return CommandResult(output=self.repository.render_snapshot(kind))

    def _handle_show_interfaces(self) -> CommandResult:
        if self.mode not in {"exec", "privileged"}:
            return CommandResult(output="% 'show interfaces summary' is only available in EXEC modes.", success=False)
        running = self.repository.get_snapshot("running")
        self.hostname = running.config.hostname
        return CommandResult(output=render_interfaces_summary(running.config))

    def _handle_configure_terminal(self) -> CommandResult:
        if self.mode != "privileged":
            return CommandResult(output="% 'configure terminal' requires privileged EXEC mode.", success=False)
        self.mode = "config"
        return CommandResult()

    def _handle_end(self) -> CommandResult:
        if self.mode in {"config", "config-if"}:
            self.mode = "privileged"
            self.current_interface = None
            return CommandResult()
        return CommandResult(output="% 'end' is only useful from configuration modes.", success=False)

    def _handle_write_memory(self) -> CommandResult:
        if self.mode != "privileged":
            return CommandResult(output="% 'write memory' requires privileged EXEC mode.", success=False)
        mutation = self.repository.sync_startup_with_running()
        return CommandResult(output=mutation.message, mutated=mutation.status == "updated")

    def _handle_hostname(self, command: str) -> CommandResult:
        if self.mode != "config":
            return CommandResult(output="% 'hostname' requires global configuration mode.", success=False)
        _, value = command.split(maxsplit=1)
        mutation = self.repository.mutate_running(
            mutator=lambda config: setattr(config, "hostname", value),
            updated_message=f"Hostname updated to {value}.",
            no_change_message=f"Hostname already set to {value}.",
        )
        self.hostname = mutation.snapshot.config.hostname
        return CommandResult(output=mutation.message, mutated=mutation.status == "updated")

    def _handle_username(self, command: str) -> CommandResult:
        if self.mode != "config":
            return CommandResult(output="% 'username ... secret ...' requires global configuration mode.", success=False)
        parts = command.split()
        if len(parts) != 4 or parts[2].lower() != "secret":
            return CommandResult(output="% Usage: username <name> secret <value>", success=False)
        username = parts[1]
        secret = parts[3]

        def mutator(config: DeviceConfig) -> None:
            user = next((candidate for candidate in config.users if candidate.username == username), None)
            if user is None:
                config.users.append({"username": username, "secret": secret})
            else:
                user.secret = secret

        mutation = self.repository.mutate_running(
            mutator=mutator,
            updated_message=f"Username {username} updated in running configuration.",
            no_change_message=f"Username {username} already present with the requested secret.",
        )
        return CommandResult(output=mutation.message, mutated=mutation.status == "updated")

    def _handle_interface(self, command: str) -> CommandResult:
        if self.mode != "config":
            return CommandResult(output="% 'interface' requires global configuration mode.", success=False)
        _, interface_name = command.split(maxsplit=1)
        mutation = self.repository.mutate_running(
            mutator=lambda config: config.ensure_interface(interface_name),
            updated_message=f"Interface {interface_name} selected.",
            no_change_message=f"Interface {interface_name} selected.",
        )
        selected = mutation.snapshot.config.get_interface(interface_name)
        self.current_interface = selected.name if selected is not None else interface_name
        self.mode = "config-if"
        return CommandResult(mutated=mutation.status == "updated")

    def _handle_description(self, command: str) -> CommandResult:
        if self.mode != "config-if" or self.current_interface is None:
            return CommandResult(output="% 'description' requires interface configuration mode.", success=False)
        _, description = command.split(maxsplit=1)

        def mutator(config: DeviceConfig) -> None:
            interface = config.ensure_interface(self.current_interface)
            interface.description = description

        mutation = self.repository.mutate_running(
            mutator=mutator,
            updated_message=f"Description updated on {self.current_interface}.",
            no_change_message=f"Description already set on {self.current_interface}.",
        )
        return CommandResult(output=mutation.message, mutated=mutation.status == "updated")

    def _handle_shutdown(self, *, enabled: bool) -> CommandResult:
        if self.mode != "config-if" or self.current_interface is None:
            return CommandResult(output="% Interface configuration mode is required.", success=False)

        def mutator(config: DeviceConfig) -> None:
            interface = config.ensure_interface(self.current_interface)
            interface.shutdown = not enabled

        state_word = "enabled" if enabled else "disabled"
        mutation = self.repository.mutate_running(
            mutator=mutator,
            updated_message=f"Interface {self.current_interface} {state_word}.",
            no_change_message=f"Interface {self.current_interface} already {state_word}.",
        )
        return CommandResult(output=mutation.message, mutated=mutation.status == "updated")
