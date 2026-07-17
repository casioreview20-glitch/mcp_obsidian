"""Import a user-selected Downloads source into the vault."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re

from .core import INDEXABLE_EXTENSIONS, VaultPolicy


def normalize_user_path(value: str | Path) -> Path:
    """Accept `C:/...` and `/c/...` when the CLI runs from Git Bash on Windows."""

    raw = str(value).replace("\\", "/")
    match = re.fullmatch(r"/([A-Za-z])(?:/(.*))?", raw)
    if os.name == "nt" and match:
        return Path(f"{match.group(1).upper()}:/{match.group(2) or ''}")
    return Path(value)


@dataclass(frozen=True)
class ImportResult:
    source_path: str
    relative_path: str
    bytes_copied: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _copy_bounded_without_overwrite(source: Path, directory: Path, max_bytes: int) -> tuple[Path, int]:
    """Stream-copy into an exclusively created file and remove partial output on failure."""

    suffix = 1
    while True:
        filename = source.name if suffix == 1 else f"{source.stem} ({suffix}){source.suffix}"
        destination = directory / filename
        try:
            output = destination.open("xb")
            break
        except FileExistsError:
            suffix += 1

    copied = 0
    try:
        with source.open("rb") as input_file, output:
            while True:
                block = input_file.read(min(64 * 1024, max_bytes + 1 - copied))
                if not block:
                    break
                copied += len(block)
                if copied > max_bytes:
                    raise ValueError(f"Source exceeds the {max_bytes}-byte limit while copying")
                output.write(block)
            if input_file.read(1):
                raise ValueError(f"Source exceeds the {max_bytes}-byte limit while copying")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination, copied


def import_source(*, vault_root: Path, source_path: Path, import_root: Path) -> ImportResult:
    """Safely copy a supported Downloads file without moving, deleting, or overwriting the source."""

    root = normalize_user_path(vault_root).resolve()
    source = normalize_user_path(source_path).resolve()
    allowed_root = normalize_user_path(import_root).resolve()
    try:
        source.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError(f"Source must be inside the approved Downloads root: {allowed_root}") from exc
    if not source.is_file():
        raise ValueError(f"Source file was not found: {source}")
    if source.suffix.lower() not in INDEXABLE_EXTENSIONS:
        raise ValueError(f"Unsupported format: {source.suffix}")

    policy = VaultPolicy(vault_root=root)
    if source.stat().st_size > policy.max_file_bytes:
        raise ValueError(f"Source exceeds the {policy.max_file_bytes}-byte limit")

    destination_dir = (root / "10 - Source Data" / "Raw Documents").resolve(strict=False)
    try:
        destination_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Destination directory must remain inside the vault") from exc
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination_dir = destination_dir.resolve()
    try:
        destination_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Destination directory must remain inside the vault") from exc
    destination, bytes_copied = _copy_bounded_without_overwrite(source, destination_dir, policy.max_file_bytes)
    return ImportResult(
        source_path=str(source),
        relative_path=destination.relative_to(root).as_posix(),
        bytes_copied=bytes_copied,
    )
