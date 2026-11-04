"""Resume one session in a visible Windows terminal with literal arguments."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
from pathlib import Path

from .domain import Provider, Session, SessionError, valid_id


def powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def resume_session(session: Session) -> None:
    """Use a visible terminal; encoded PowerShell keeps paths out of shell syntax."""
    if os.name != "nt":
        raise SessionError("Resuming sessions needs Windows.")
    provider = session.provider
    session_id = session.id
    if not valid_id(session_id):
        raise SessionError("This item has an invalid session ID.")
    cwd = session.cwd
    home = str(session.home)
    if not cwd or not Path(cwd).is_dir():
        raise SessionError(f"The session's project folder no longer exists: {cwd}")
    if not home or not Path(home).is_dir():
        raise SessionError("The session's configuration folder no longer exists.")
    executable = shutil.which(provider.value)
    if not executable:
        raise SessionError(f"Install {provider.label} and make {provider.value} available on PATH.")
    shell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if not shell:
        raise SessionError("PowerShell is required to resume a session.")
    resume = "resume" if provider == Provider.CODEX else "--resume"
    script = (
        f"$env:{provider.home_variable} = {powershell_literal(home)}; "
        f"Set-Location -LiteralPath {powershell_literal(cwd)}; "
        f"& {powershell_literal(executable)} {resume} {powershell_literal(str(session_id))}"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = [shell, "-NoLogo", "-NoExit", "-EncodedCommand", encoded]
    terminal = shutil.which("wt.exe")
    if terminal:
        command = [terminal, "-w", "new", "new-tab", "--startingDirectory", cwd, *command]
    try:
        subprocess.Popen(
            command,
            cwd=cwd,
            creationflags=0 if terminal else subprocess.CREATE_NEW_CONSOLE,
        )
    except OSError as exc:
        raise SessionError(f"Could not open the terminal: {exc}") from exc
