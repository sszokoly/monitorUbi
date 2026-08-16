"""Standard-library deployment copying for the systemd service runtime."""

import json
import os
import shutil
import tempfile
from pathlib import Path


_MANIFEST_NAME = ".monitorubi-deployment-manifest.json"
_IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__"}
_IGNORED_FILENAMES = {"app.log", _MANIFEST_NAME}
_IGNORED_SUFFIXES = (".db", ".db-wal", ".db-shm")


def copy_runtime_files(source_root: str | Path, deployment_root: str | Path) -> None:
    """Copy source and virtualenv while preserving deployed state files."""
    source = Path(source_root).resolve()
    destination = Path(deployment_root).resolve()
    virtualenv_source = source / ".venv"
    if not virtualenv_source.is_dir():
        raise RuntimeError(f"Virtual environment is missing: {virtualenv_source}")

    destination.mkdir(parents=True, exist_ok=True)
    previous_files = _load_manifest(destination)
    copied_files = _copy_source_files(source, destination)
    _remove_stale_files(destination, previous_files - copied_files)
    _write_manifest(destination, copied_files)
    _replace_virtualenv(virtualenv_source, destination / ".venv")


def _copy_source_files(source: Path, destination: Path) -> set[Path]:
    """Copy deployable project files and return their relative paths."""
    copied_files: set[Path] = set()
    for root, directory_names, file_names in os.walk(source):
        directory_names[:] = [
            name for name in directory_names if name not in _IGNORED_DIRECTORIES
        ]
        root_path = Path(root)
        for file_name in file_names:
            source_path = root_path / file_name
            relative_path = source_path.relative_to(source)
            if _is_ignored(relative_path):
                continue

            target_path = destination / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path, follow_symlinks=False)
            copied_files.add(relative_path)
    return copied_files


def _is_ignored(relative_path: Path) -> bool:
    """Exclude source-control, runtime-state, and cache files from deployment."""
    if any(part in _IGNORED_DIRECTORIES for part in relative_path.parts):
        return True
    return (
        relative_path.name in _IGNORED_FILENAMES
        or relative_path.name.endswith(_IGNORED_SUFFIXES)
    )


def _load_manifest(destination: Path) -> set[Path]:
    """Load paths copied by the previous deployment."""
    manifest_path = destination / _MANIFEST_NAME
    if not manifest_path.is_file():
        return set()
    try:
        paths = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {Path(path) for path in paths if _is_safe_relative_path(Path(path))}


def _remove_stale_files(destination: Path, stale_files: set[Path]) -> None:
    """Remove only source files known to have been deployed previously."""
    for relative_path in sorted(stale_files, key=lambda path: len(path.parts), reverse=True):
        target_path = destination / relative_path
        if target_path.is_file() or target_path.is_symlink():
            target_path.unlink()
        _remove_empty_parents(target_path.parent, destination)


def _remove_empty_parents(path: Path, destination: Path) -> None:
    """Remove empty source directories without touching deployment root."""
    while path != destination:
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _write_manifest(destination: Path, copied_files: set[Path]) -> None:
    """Atomically record source files copied by this deployment."""
    manifest_path = destination / _MANIFEST_NAME
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=destination, delete=False
    ) as manifest_file:
        json.dump(sorted(path.as_posix() for path in copied_files), manifest_file)
        manifest_file.write("\n")
        temporary_path = Path(manifest_file.name)
    temporary_path.replace(manifest_path)


def _replace_virtualenv(source: Path, destination: Path) -> None:
    """Replace the non-persistent virtualenv with the current source virtualenv."""
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, symlinks=True)


def _is_safe_relative_path(path: Path) -> bool:
    """Reject manifest entries that could escape the deployment directory."""
    return not path.is_absolute() and ".." not in path.parts
