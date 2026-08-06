"""System-wide systemd management for the monitorUbi daemon."""

import asyncio
import getpass
import os
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from monitorUbi.deployment import deploy_runtime


UNIT_NAME = "monitorUbi.service"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
DEPLOYMENT_ROOT = Path("/opt/monitorUbi")


class SystemdError(RuntimeError):
    """A privileged systemd operation that could not be completed."""


@dataclass(frozen=True)
class _CommandResult:
    returncode: int | None
    stdout: str
    stderr: str


@dataclass(frozen=True)
class SystemdStatus:
    """The enabled and active states reported by systemctl."""
    enabled: str
    active: str


class SystemdService:
    """Install and control the monitorUbi system service through systemctl."""
    def __init__(
        self,
        project_root: str | Path | None = None,
        deployment_root: str | Path = DEPLOYMENT_ROOT,
    ) -> None:
        self._project_root = Path(project_root or Path(__file__).resolve().parents[1])
        self._deployment_root = Path(deployment_root)

    async def status(self) -> SystemdStatus:
        """Read systemctl states without treating nonzero status checks as errors."""
        enabled = await self._run("systemctl", "is-enabled", UNIT_NAME)
        active = await self._run("systemctl", "is-active", UNIT_NAME)
        return SystemdStatus(
            enabled=_state_output(enabled), active=_state_output(active)
        )

    def can_manage(self) -> bool:
        """Whether the current user owns this singleton service deployment."""
        if os.geteuid() == 0:
            return True
        try:
            return self._deployment_root.stat().st_uid == os.geteuid()
        except FileNotFoundError:
            return True

    async def authenticate(self, password: str) -> None:
        """Force validation of sudo credentials before a privileged operation."""
        await self.clear_authentication()
        result = await self._run("sudo", "-S", "-p", "", "-v", input_text=password)
        if result.returncode:
            raise SystemdError(_command_error(result))

    async def clear_authentication(self) -> None:
        """Discard the cached sudo ticket for the current user."""
        result = await self._run("sudo", "-k")
        if result.returncode:
            raise SystemdError(_command_error(result))

    async def install(self) -> None:
        """Deploy, install, enable, and start the generated system unit."""
        unit_file = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        try:
            await self._deploy_runtime()
            with unit_file:
                unit_file.write(self.unit_text())
            await self._run_privileged("install", "-m", "0644", unit_file.name, UNIT_PATH)
            await self._run_privileged("systemctl", "daemon-reload")
            await self._run_privileged("systemctl", "enable", "--now", UNIT_NAME)
        finally:
            Path(unit_file.name).unlink(missing_ok=True)

    async def enable(self) -> None:
        """Enable and immediately start the installed unit."""
        await self._run_privileged("systemctl", "enable", "--now", UNIT_NAME)

    async def uninstall(self) -> None:
        """Stop, disable, and remove the installed unit."""
        await self._run_privileged("systemctl", "disable", "--now", UNIT_NAME)
        await self._run_privileged("rm", "-f", UNIT_PATH)
        await self._run_privileged("systemctl", "daemon-reload")

    async def start(self) -> None:
        """Start the installed unit without changing its enabled state."""
        await self._run_privileged("systemctl", "start", UNIT_NAME)

    async def stop(self) -> None:
        """Stop the installed unit without changing its enabled state."""
        await self._run_privileged("systemctl", "stop", UNIT_NAME)

    def unit_text(self) -> str:
        """Build a unit that executes the SELinux-compatible deployment."""
        return "\n".join(
            (
                "[Unit]",
                "Description=monitorUbi Ubiquiti UMR monitor",
                "Wants=network-online.target",
                "After=network-online.target",
                "",
                "[Service]",
                "Type=simple",
                f"User={getpass.getuser()}",
                f"WorkingDirectory={_quote(self._deployment_root)}",
                "Environment=PYTHONUNBUFFERED=1",
                f"ExecStart={_quote(self._deployment_python)} -m monitorUbi.daemon",
                "Restart=on-failure",
                "RestartSec=5",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
                "",
            )
        )

    async def _run_privileged(self, *command: str | Path) -> None:
        result = await self._run("sudo", "-n", *command)
        if result.returncode:
            raise SystemdError(_command_error(result))

    @property
    def _deployment_python(self) -> Path:
        """Return the virtual-environment interpreter inside the deployment."""
        return self._deployment_root / ".venv" / "bin" / "python"

    async def _deploy_runtime(self) -> None:
        """Copy source and dependencies into /opt with an executable SELinux label."""
        owner = f"{os.geteuid()}:{os.getegid()}"
        await self._run_privileged(
            "install",
            "-d",
            "-m",
            "0755",
            "-o",
            str(os.geteuid()),
            "-g",
            str(os.getegid()),
            self._deployment_root,
        )
        await self._run_privileged("chown", "-R", owner, self._deployment_root)
        try:
            deploy_runtime(self._project_root, self._deployment_root)
        except OSError as error:
            raise SystemdError(f"Could not deploy application files: {error}") from error
        except RuntimeError as error:
            raise SystemdError(str(error)) from error
        await self._ensure_selinux_context()
        await self._run_privileged("restorecon", "-RF", self._deployment_root)

    async def _ensure_selinux_context(self) -> None:
        """Assign a persistent executable context to the system deployment."""
        context_path = f"{self._deployment_root}(/.*)?"
        result = await self._run(
            "sudo", "-n", "semanage", "fcontext", "-a", "-t", "usr_t", context_path
        )
        if result.returncode == 0:
            return
        if "already defined" not in result.stderr.lower():
            raise SystemdError(_command_error(result))
        result = await self._run(
            "sudo", "-n", "semanage", "fcontext", "-m", "-t", "usr_t", context_path
        )
        if result.returncode:
            raise SystemdError(_command_error(result))

    @staticmethod
    async def _run(
        *command: str | Path, input_text: str | None = None
    ) -> _CommandResult:
        process = await asyncio.create_subprocess_exec(
            *(str(argument) for argument in command),
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        stdout, stderr = await process.communicate(
            None if input_text is None else f"{input_text}\n".encode()
        )
        return _CommandResult(
            process.returncode,
            stdout.decode(errors="replace").strip(),
            stderr.decode(errors="replace").strip(),
        )


def _state_output(result: _CommandResult) -> str:
    """Extract systemctl's state, normalizing its missing-unit diagnostic."""
    if result.stdout:
        return result.stdout
    error_text = result.stderr.lower()
    if any(
        diagnostic in error_text
        for diagnostic in (
            "not found",
            "not loaded",
            "no such file or directory",
            "failed to get unit file state",
        )
    ):
        return "not-found"
    return "unknown"


def _command_error(result: _CommandResult) -> str:
    """Return the most useful diagnostics from a failed subprocess."""
    return result.stderr or result.stdout or "Command failed without output"


def _quote(value: str | Path) -> str:
    """Quote a systemd unit argument only when its path requires it."""
    return shlex.quote(str(value))


if __name__ == "__main__":
    async def example():
        service = SystemdService()
        status = await service.status()
        print(f"Unit {UNIT_NAME} is {status.enabled} and {status.active}")

    asyncio.run(example())
