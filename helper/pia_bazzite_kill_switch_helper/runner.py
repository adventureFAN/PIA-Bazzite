from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Sequence

from .core import TABLE_NAME

NFT_CANDIDATES = (
    Path("/usr/sbin/nft"),
    Path("/usr/bin/nft"),
    Path("/sbin/nft"),
)


class NftError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def find_nft_binary() -> Path:
    for candidate in NFT_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise NftError("The nft executable was not found in an approved system path.")


class NftRunner:
    def __init__(self, binary: Path | None = None) -> None:
        selected = binary or find_nft_binary()
        if selected not in NFT_CANDIDATES:
            raise NftError("Refusing an nft executable outside approved system paths.")
        self.binary = selected

    def _run(
        self,
        arguments: Sequence[str],
        *,
        input_text: str | None = None,
        timeout: float = 15.0,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                [str(self.binary), *arguments],
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                shell=False,
                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NftError(f"Could not execute nft safely: {exc}") from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    def table_exists(self) -> bool:
        result = self._run(["list", "table", "inet", TABLE_NAME], timeout=5.0)
        if result.returncode == 0:
            return True
        detail = (result.stderr or result.stdout or "").strip()
        if "No such file or directory" in detail:
            return False
        raise NftError(f"Could not determine whether the helper table exists: {detail or 'unknown error'}")

    def list_table_json(self) -> CommandResult:
        return self._run(["-j", "list", "table", "inet", TABLE_NAME], timeout=8.0)

    def check_script(self, script: str) -> None:
        result = self._run(["--check", "-f", "-"], input_text=script)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown nft check error").strip()
            raise NftError(f"nftables rejected the generated transaction: {detail}")

    def apply_script(self, script: str) -> None:
        result = self._run(["-f", "-"], input_text=script)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "unknown nft apply error").strip()
            raise NftError(f"nftables could not apply the transaction: {detail}")
