"""Download and install a Stockfish binary for the current platform.

Mirrors the cancellable-worker shape used by AnalysisWorker/BotWorker (a
background daemon thread, polled by the main loop rather than blocked on),
but the unit of work here is "download + extract + locate the binary"
instead of "run a search" — there's no epoch/abort dance because a
download isn't restarted on every move, only by an explicit user click,
and the existing thread is simply joined before a retry.

Only ever downloads from the official GitHub releases for
official-stockfish/Stockfish, per Stockfish's own documented guidance
("We only recommend downloading from the official GitHub releases. We
cannot guarantee the safety, reliability, and availability of binaries
downloaded from third parties.") — never from stockfishchess.org's HTML
pages or any other mirror.
"""
from __future__ import annotations

import platform
import shutil
import stat
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from chess_game.log import get_logger

# Pinned to a specific, known-good tag rather than "latest" — the asset
# filenames for a new release aren't guaranteed to match this list (new
# CPU-feature suffixes get added over time), so chasing "latest"
# automatically risks silently breaking the download on a Stockfish
# release this code was never updated for. Bump deliberately.
_RELEASE_TAG = "sf_18"
_RELEASE_BASE_URL = f"https://github.com/official-stockfish/Stockfish/releases/download/{_RELEASE_TAG}"

# One asset per platform — deliberately the plain, no-CPU-extension
# variant (no avx2/bmi2/avx512/... suffix) rather than the fastest one
# available. A wrong CPU-feature pick (e.g. bmi2 on a CPU that doesn't
# support BMI2) fails at process-launch time in a way this code can't
# easily distinguish from "Stockfish isn't installed", whereas the plain
# variant runs correctly everywhere, just somewhat slower. Confirmed
# against the real sf_18 release asset list — see module docstring.
_ASSET_BY_PLATFORM = {
    "windows-x86_64": "stockfish-windows-x86-64.zip",
    "macos-arm64": "stockfish-macos-m1-apple-silicon.tar",
    "macos-x86_64": "stockfish-macos-x86-64.tar",
    "linux-x86_64": "stockfish-ubuntu-x86-64.tar",
}

_DOWNLOAD_TIMEOUT_S = 30.0
_CHUNK_SIZE = 1 << 16  # 64 KiB


class UnsupportedPlatformError(Exception):
    """Raised when the current OS/architecture has no known release asset."""


def detect_platform_key() -> str:
    """Return a key into _ASSET_BY_PLATFORM for the current machine, or
    raise UnsupportedPlatformError if there's no matching asset.

    Only x86-64 Windows/Linux and x86-64/arm64 macOS are covered, matching
    the platforms this project already ships PyInstaller builds for
    (release.yml targets ubuntu-latest, macos-latest, windows-latest).
    """
    system = platform.system()
    machine = platform.machine().lower()
    is_64bit_x86 = machine in ("x86_64", "amd64")
    is_arm64 = machine in ("arm64", "aarch64")

    if system == "Windows" and is_64bit_x86:
        return "windows-x86_64"
    if system == "Darwin" and is_arm64:
        return "macos-arm64"
    if system == "Darwin" and is_64bit_x86:
        return "macos-x86_64"
    if system == "Linux" and is_64bit_x86:
        return "linux-x86_64"
    raise UnsupportedPlatformError(f"No Stockfish release asset for {system} {machine}")


def _asset_url_for_current_platform() -> tuple[str, str]:
    """Returns (asset_filename, full_download_url) for this machine."""
    key = detect_platform_key()
    asset_name = _ASSET_BY_PLATFORM[key]
    return asset_name, f"{_RELEASE_BASE_URL}/{asset_name}"


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    """Extract a .zip or .tar archive. Raises on any path-traversal member
    (a malicious or corrupt archive trying to write outside dest_dir) —
    this is a real download from the network, not a trusted local file,
    so member paths get validated before anything is written.
    """
    dest_dir = dest_dir.resolve()

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for member_name in zf.namelist():
                member_path = (dest_dir / member_name).resolve()
                if not str(member_path).startswith(str(dest_dir)):
                    raise ValueError(f"Unsafe path in archive: {member_name}")
            zf.extractall(dest_dir)
    else:
        # python-chess's project already depends on nothing beyond the
        # stdlib for this; tarfile's own `filter="data"` (Python 3.12+)
        # gives the same traversal protection where available. Manual
        # validation below covers 3.10/3.11 too, since pyproject.toml
        # pins requires-python = ">=3.10".
        with tarfile.open(archive_path) as tf:
            for tar_member in tf.getmembers():
                member_path = (dest_dir / tar_member.name).resolve()
                if not str(member_path).startswith(str(dest_dir)):
                    raise ValueError(f"Unsafe path in archive: {tar_member.name}")
            try:
                tf.extractall(dest_dir, filter="data")
            except TypeError:
                # Python < 3.12 doesn't have the `filter` kwarg; the
                # manual check above already covers the same risk.
                tf.extractall(dest_dir)


def _find_extracted_binary(search_root: Path) -> Path | None:
    """Locate the Stockfish executable somewhere under search_root.

    Deliberately doesn't assume a fixed internal archive layout (root
    file vs. nested folder) — Stockfish's own release packaging has
    changed this before across versions, and re-verifying it against
    every future release isn't sustainable. Instead, this walks the
    extracted tree and picks the most plausible candidate: a file whose
    name contains "stockfish", preferring one with the platform's
    executable extension (.exe on Windows, none elsewhere) and an
    executable permission bit where applicable.
    """
    is_windows = platform.system() == "Windows"
    candidates: list[Path] = []
    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        name_lower = path.name.lower()
        if "stockfish" not in name_lower:
            continue
        if is_windows and not name_lower.endswith(".exe"):
            continue
        if not is_windows and name_lower.endswith((".exe", ".dll", ".so", ".dylib")):
            continue
        candidates.append(path)

    if not candidates:
        return None
    # Prefer the largest match — a real engine binary embedding an NNUE
    # network is on the order of 50-150MB; a stray README or script that
    # happens to mention "stockfish" in its name is not.
    return max(candidates, key=lambda p: p.stat().st_size)


class StockfishDownloader:
    """Background download + extract + locate, polled rather than awaited.

    Mirrors BotWorker/AnalysisWorker's "spawn a daemon thread, store the
    result under a lock, let the main loop poll for it" shape, but models
    a one-shot user-triggered action rather than a per-move restart, so
    there's no epoch counter — start() just refuses to spawn a second
    thread while one is already running, and join()s the old thread
    before a deliberate retry.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._busy = False
        self._progress_fraction: float | None = None  # None = indeterminate
        self._result_path: str | None = None
        self._error: str | None = None
        self._done = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def progress(self) -> float | None:
        """0.0-1.0 if the download reports a Content-Length, else None
        (e.g. during extraction, or if the server omitted the header)."""
        with self._lock:
            return self._progress_fraction

    def start(self, install_dir: Path) -> None:
        """Begin downloading into install_dir (created if missing).
        No-op if a download is already in progress."""
        with self._lock:
            if self._busy:
                return
            self._busy = True
            self._progress_fraction = None
            self._result_path = None
            self._error = None
            self._done = False

        thread = threading.Thread(target=self._run, args=(install_dir,), daemon=True)
        self._thread = thread
        thread.start()

    def take_result(self) -> tuple[str | None, str | None] | None:
        """Returns (path, error) — exactly one of which is non-None — the
        first time a finished download/extract is observed, then None on
        every subsequent call until the next start(). Mirrors
        AnalysisWorker.take()'s "consume once" contract so the caller
        doesn't re-process the same completed download every frame."""
        with self._lock:
            if not self._done:
                return None
            self._done = False
            return self._result_path, self._error

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self, install_dir: Path) -> None:
        logger = get_logger()
        try:
            asset_name, url = _asset_url_for_current_platform()
            install_dir.mkdir(parents=True, exist_ok=True)
            archive_path = install_dir / asset_name

            logger.info("Downloading Stockfish from %s", url)
            self._download(url, archive_path)

            extract_dir = install_dir / "stockfish"
            if extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)
            extract_dir.mkdir(parents=True, exist_ok=True)

            with self._lock:
                self._progress_fraction = None  # extraction has no % progress
            _extract_archive(archive_path, extract_dir)

            binary_path = _find_extracted_binary(extract_dir)
            if binary_path is None:
                raise FileNotFoundError(
                    "Downloaded archive did not contain a recognisable Stockfish binary"
                )

            if platform.system() != "Windows":
                # Archive permissions aren't always preserved faithfully
                # across zip/tar + platform combinations; make sure the
                # binary is actually executable regardless of what the
                # archive said.
                current_mode = binary_path.stat().st_mode
                binary_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            try:
                archive_path.unlink()
            except OSError:
                pass  # cosmetic cleanup only; a leftover archive is harmless

            logger.info("Stockfish installed at %s", binary_path)
            with self._lock:
                self._result_path = str(binary_path)
                self._error = None
                self._done = True
                self._busy = False

        except UnsupportedPlatformError as exc:
            logger.warning("Stockfish download unsupported: %s", exc)
            with self._lock:
                self._error = str(exc)
                self._result_path = None
                self._done = True
                self._busy = False
        except (OSError, urllib.error.URLError, zipfile.BadZipFile,
                tarfile.TarError, ValueError) as exc:
            logger.warning("Stockfish download failed: %s", exc)
            with self._lock:
                self._error = f"Download failed: {exc}"
                self._result_path = None
                self._done = True
                self._busy = False

    def _download(self, url: str, dest: Path) -> None:
        """Stream the asset to disk, updating _progress_fraction as
        bytes arrive when the server reports Content-Length."""
        request = urllib.request.Request(url, headers={"User-Agent": "python-chess-game"})
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_S) as response:
            total_str = response.headers.get("Content-Length")
            total = int(total_str) if total_str else None
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        with self._lock:
                            self._progress_fraction = min(1.0, downloaded / total)
