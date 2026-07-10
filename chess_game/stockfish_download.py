"""Download and install a Stockfish binary for the current platform.

This uses a background thread polled by the main loop, matching the
worker pattern used elsewhere in the app. Only official Stockfish
GitHub release assets are downloaded.

Integrity
---------
No checksums are hardcoded in this file. Instead, each downloaded
archive is verified against the SHA-256 digest GitHub itself computes
and publishes for release assets (the `digest` field on the Releases
API, populated automatically at upload time - see
https://github.blog/changelog/2025-06-03-releases-now-expose-digests-for-release-assets/).
This is fetched fresh from the GitHub API for the pinned release tag
before the archive is trusted, so a hash never goes stale relative to
the actual asset and nothing needs updating by hand when _RELEASE_TAG
changes. See _fetch_expected_digest / _verify_digest below.
"""
from __future__ import annotations

import hashlib
import json
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

# Pinned to a specific known-good tag rather than "latest".
# Asset filenames can change across Stockfish releases.
_RELEASE_TAG = "sf_18"
_RELEASE_BASE_URL = f"https://github.com/official-stockfish/Stockfish/releases/download/{_RELEASE_TAG}"
_RELEASE_API_URL = (
    f"https://api.github.com/repos/official-stockfish/Stockfish/releases/tags/{_RELEASE_TAG}"
)

# Use the plain platform asset variant, not a CPU-specific build.
# This avoids launch failures on unsupported CPUs.
_ASSET_BY_PLATFORM = {
    "windows-x86_64": "stockfish-windows-x86-64.zip",
    "macos-arm64": "stockfish-macos-m1-apple-silicon.tar",
    "macos-x86_64": "stockfish-macos-x86-64.tar",
    "linux-x86_64": "stockfish-ubuntu-x86-64.tar",
}

_DOWNLOAD_TIMEOUT_S = 30.0
_API_TIMEOUT_S = 15.0
_CHUNK_SIZE = 1 << 16  # 64 KiB


class UnsupportedPlatformError(Exception):
    """Raised when the current OS/architecture has no known release asset."""


class DigestMismatchError(Exception):
    """Raised when a downloaded archive's SHA-256 doesn't match the digest
    GitHub reports for that release asset. Treated the same as any other
    download failure by callers - the archive is never extracted."""


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


def _fetch_expected_digest(asset_name: str) -> str | None:
    """Look up asset_name's SHA-256 via the GitHub Releases API.

    Returns the lowercase hex digest, or None if it can't be determined
    (network error, rate limiting, or - for releases predating GitHub's
    digest feature - a null `digest` field). None is a legitimate "can't
    verify" result, not a hash; callers must not treat it as a match.

    Nothing here is hardcoded: the tag is pinned (_RELEASE_TAG) but the
    digest itself always comes fresh from GitHub, computed by GitHub at
    upload time, so it can never drift out of sync with the real asset.
    """
    logger = get_logger()
    request = urllib.request.Request(
        _RELEASE_API_URL,
        headers={
            "User-Agent": "python-chess-game",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_API_TIMEOUT_S) as response:
            payload = json.load(response)
    except Exception as exc:
        # Deliberately broad: this is a best-effort integrity check, not
        # the download itself, and must never let an unexpected failure
        # mode here (network error, malformed JSON, an unusual response
        # object, ...) escalate into failing the whole download. Any
        # failure just means "can't verify this time" - see
        # _verify_digest's fallback behaviour when this returns None.
        logger.warning("Could not reach GitHub API for release digests: %s", exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Unexpected GitHub API response shape for release digests")
        return None

    for asset in payload.get("assets", []):
        if asset.get("name") != asset_name:
            continue
        digest = asset.get("digest")
        if not digest or not isinstance(digest, str):
            # Field exists on the schema but is null - e.g. a release
            # published before GitHub started computing digests.
            logger.warning(
                "GitHub reports no digest for asset %s (release predates "
                "digest support, or it hasn't propagated yet)", asset_name,
            )
            return None
        # GitHub's digest field is formatted "sha256:<hex>".
        algo, _, hex_digest = digest.partition(":")
        if algo != "sha256" or not hex_digest:
            logger.warning("Unexpected digest format for %s: %r", asset_name, digest)
            return None
        return hex_digest.lower()

    logger.warning("Asset %s not found in GitHub release %s", asset_name, _RELEASE_TAG)
    return None


def _sha256_of_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of the file at path."""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_digest(archive_path: Path, asset_name: str) -> None:
    """Verify archive_path against the digest GitHub reports for
    asset_name, raising DigestMismatchError on a mismatch.

    If GitHub's digest can't be determined (see _fetch_expected_digest),
    this logs a warning and returns without raising rather than blocking
    every download whenever the API is briefly unreachable - the pinned
    release tag, HTTPS transport, and archive path-traversal checks
    elsewhere in this module still apply either way. A real mismatch
    (the one case that actually indicates a tampered or corrupted
    asset) always raises.
    """
    logger = get_logger()
    expected = _fetch_expected_digest(asset_name)
    if expected is None:
        logger.warning(
            "Skipping SHA-256 verification for %s (digest unavailable from "
            "GitHub); proceeding on pinned-tag + HTTPS trust alone", asset_name,
        )
        return

    actual = _sha256_of_file(archive_path)
    if actual != expected:
        raise DigestMismatchError(
            f"SHA-256 mismatch for {asset_name}: expected {expected}, got {actual} "
            "(downloaded archive does not match GitHub's published digest)"
        )
    logger.info("Verified %s against GitHub-published SHA-256 digest", asset_name)


def _is_within_directory(dest_dir: Path, member_path: Path) -> bool:
    """Return True if member_path is dest_dir or nested inside it.

    Compare path components rather than string prefixes to avoid path
    traversal attacks.
    """
    return member_path == dest_dir or member_path.is_relative_to(dest_dir)


def _extract_archive(archive_path: Path, dest_dir: Path) -> None:
    """Extract a .zip or .tar archive safely.

    Raise if any archive member would write outside dest_dir.
    """
    dest_dir = dest_dir.resolve()

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zf:
            for member_name in zf.namelist():
                member_path = (dest_dir / member_name).resolve()
                if not _is_within_directory(dest_dir, member_path):
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
                if not _is_within_directory(dest_dir, member_path):
                    raise ValueError(f"Unsafe path in archive: {tar_member.name}")
            try:
                tf.extractall(dest_dir, filter="data")
            except TypeError:
                # Python < 3.12 doesn't have the `filter` kwarg; the
                # manual check above already covers the same risk.
                tf.extractall(dest_dir)


def _find_extracted_binary(search_root: Path) -> Path | None:
    """Locate a plausible Stockfish executable under search_root.

    Avoid assuming a fixed archive layout, and prefer platform-appropriate
    executable names.
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
    """Background download/extract task polled by the main loop.

    Start() launches a thread only if one is not already running.
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
        # Assigned as soon as the archive's destination path is known, so
        # the except blocks below can clean up a partially-downloaded or
        # digest-mismatched file even though it's set inside the try.
        archive_path: Path | None = None
        try:
            asset_name, url = _asset_url_for_current_platform()
            install_dir.mkdir(parents=True, exist_ok=True)
            archive_path = install_dir / asset_name

            logger.info("Downloading Stockfish from %s", url)
            self._download(url, archive_path)

            _verify_digest(archive_path, asset_name)

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
                tarfile.TarError, ValueError, DigestMismatchError) as exc:
            logger.warning("Stockfish download failed: %s", exc)
            # Never leave a partially-downloaded or digest-mismatched
            # archive on disk for a future retry to stumble over - the
            # next start() should always fetch a fresh copy rather than
            # risk re-extracting something that already failed here.
            if archive_path is not None:
                try:
                    archive_path.unlink()
                except OSError:
                    pass
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
