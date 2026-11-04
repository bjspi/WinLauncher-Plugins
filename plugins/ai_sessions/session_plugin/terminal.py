"""Resume one session in a visible Windows terminal with literal arguments."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

from .domain import Provider, ResumeTarget, SessionError

POWERSHELL_ENCODING = "utf-16-le"  # What -EncodedCommand is specified to contain.


def resume_session(target: ResumeTarget) -> None:
    """Check everything the user can fix first, then open a terminal for the session."""
    if os.name != "nt":
        raise SessionError("Resuming sessions needs Windows.")
    _require_folders(target)
    executable = _provider_executable(target.provider)
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not shell:
        raise SessionError("PowerShell is required to resume a session.")
    _open_terminal(shell, resume_script(target, executable), target.cwd)


def resume_script(target: ResumeTarget, executable: str) -> str:
    """The PowerShell statements that continue the session, with every value quoted."""
    verb = "resume" if target.provider == Provider.CODEX else "--resume"
    statements = [
        f"Set-Location -LiteralPath {_powershell_literal(target.cwd)}",
        f"& {_powershell_literal(executable)} {verb} {_powershell_literal(target.id)}",
    ]
    if _needs_home_variable(target):
        home = _powershell_literal(str(target.home))
        statements.insert(0, f"$env:{target.provider.home_variable} = {home}")
    return "; ".join(statements)


def _needs_home_variable(target: ResumeTarget) -> bool:
    """Leave a default installation alone: a CLI may read the variable as a relocation.

    Claude Code does. With CLAUDE_CONFIG_DIR set it keeps `.claude.json` in that folder
    instead of the profile, and so would start without the user's global state.
    """
    provider = target.provider
    return target.home != provider.default_home or bool(os.environ.get(provider.home_variable))


def _require_folders(target: ResumeTarget) -> None:
    if not Path(target.cwd).is_dir():
        raise SessionError(f"The session's project folder no longer exists: {target.cwd}")
    if not target.home.is_dir():
        raise SessionError("The session's configuration folder no longer exists.")


def _provider_executable(provider: Provider) -> str:
    executable = shutil.which(provider.value)
    if not executable:
        raise SessionError(f"Install {provider.label} and make {provider.value} available on PATH.")
    return executable


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _open_terminal(shell: str, script: str, cwd: str) -> None:
    """Prefer Windows Terminal, and keep the window open when the CLI exits.

    The script is encoded so paths never pass through shell syntax. The folder is not
    given to wt.exe: it splits its command line at semicolons, even inside a path.
    """
    encoded = base64.b64encode(script.encode(POWERSHELL_ENCODING)).decode("ascii")
    command = [shell, "-NoLogo", "-NoExit", "-EncodedCommand", encoded]
    windows_terminal = shutil.which("wt.exe")
    if windows_terminal:
        command = [windows_terminal, "-w", "new", "new-tab", *command]
    try:
        subprocess.Popen(
            command,
            cwd=cwd,
            creationflags=0 if windows_terminal else subprocess.CREATE_NEW_CONSOLE,
        )
    except OSError as exc:
        raise SessionError(f"Could not open the terminal: {exc}") from exc
