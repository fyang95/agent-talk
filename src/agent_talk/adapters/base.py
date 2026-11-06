"""How to find a vendor CLI and spawn it once. No auth files, no keychain."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

_STATUS_TIMEOUT_S = 15


@dataclass(frozen=True)
class Adapter:
    name: str
    binary: str
    prompt_argv: Callable[[str], list[str]]
    status_argv: tuple[str, ...] | None
    force_flag: str | None

    def detect(self) -> str | None:
        return shutil.which(self.binary)

    def argv(self, prompt: str, force: bool = False) -> list[str]:
        args = [self.binary, *self.prompt_argv(prompt)]
        if force and self.force_flag:
            args.append(self.force_flag)
        return args

    def spawn(
        self,
        prompt: str,
        cwd: str,
        force: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.argv(prompt, force=force),
            cwd=cwd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )

    def status(self) -> str:
        if self.detect() is None:
            return "not installed"
        if self.status_argv is None:
            return "unknown (no status command)"
        try:
            proc = subprocess.run(
                [self.binary, *self.status_argv],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=_STATUS_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "unknown (status timed out)"
        except FileNotFoundError:
            return "not installed"
        for line in f"{proc.stdout or ''}\n{proc.stderr or ''}".splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return "unknown (no status command)"
