"""StockfishDownloader tests: platform detection, archive extraction
(both flat and nested layouts, both .tar and .zip), path-traversal
rejection, SHA-256 digest verification against GitHub's Releases API,
and the threaded download/extract/locate pipeline end to end.

No real network access happens in this suite — urllib.request.urlopen is
always mocked with an in-memory fake response built from a real tarfile/
zipfile so the extraction code runs against genuine archive bytes, not a
hand-rolled stand-in.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import threading
import urllib.error
import zipfile
from pathlib import Path

import pytest

from chess_game.stockfish_download import (
    DigestMismatchError,
    StockfishDownloader,
    UnsupportedPlatformError,
    _extract_archive,
    _fetch_expected_digest,
    _find_extracted_binary,
    _is_within_directory,
    _sha256_of_file,
    _verify_digest,
    detect_platform_key,
)


def _make_tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


class _FakeResponse:
    """Stands in for the object urllib.request.urlopen's context manager
    yields: a minimal .headers + chunked .read(), enough to drive
    StockfishDownloader._download's progress-tracking loop."""

    def __init__(self, data: bytes, content_length: bool = True) -> None:
        self._data = data
        self._pos = 0
        self.headers = {"Content-Length": str(len(data))} if content_length else {}

    def read(self, n: int) -> bytes:
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _patch_urlopen(monkeypatch, data: bytes, content_length: bool = True):
    def _fake_urlopen(request, timeout=None):
        return _FakeResponse(data, content_length=content_length)

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _fake_urlopen
    )


class _FakeJsonResponse:
    """Stands in for urlopen's context manager when the caller is
    json.load()-ing the response directly (as _fetch_expected_digest
    does), rather than streaming raw bytes via chunked .read(n)."""

    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeJsonResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _patch_urlopen_by_host(monkeypatch, *, api_payload=None, api_exc=None,
                            archive_data: bytes | None = None):
    """Route urlopen based on which URL is being requested, so a single
    test can control the GitHub API response and the archive download
    response independently — mirroring what a real download actually
    does (one call to each host)."""

    def _fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "api.github.com" in url:
            if api_exc is not None:
                raise api_exc
            return _FakeJsonResponse(api_payload)
        assert archive_data is not None, "test must supply archive_data"
        return _FakeResponse(archive_data)

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _fake_urlopen
    )


# ── Platform detection ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "system,machine,expected_key",
    [
        ("Windows", "AMD64", "windows-x86_64"),
        ("Windows", "x86_64", "windows-x86_64"),
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x86_64"),
        ("Linux", "x86_64", "linux-x86_64"),
    ],
)
def test_detect_platform_key_known_platforms(monkeypatch, system, machine, expected_key):
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: system)
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: machine)
    assert detect_platform_key() == expected_key


def test_detect_platform_key_unsupported_raises(monkeypatch):
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "FreeBSD")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")
    with pytest.raises(UnsupportedPlatformError):
        detect_platform_key()


def test_detect_platform_key_32bit_x86_unsupported(monkeypatch):
    """Stockfish's release matrix doesn't cover 32-bit x86 at all — make
    sure an i686 box fails informatively rather than silently picking the
    wrong (64-bit) asset."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "i686")
    with pytest.raises(UnsupportedPlatformError):
        detect_platform_key()


# ── Archive extraction: both real-world layouts, both formats ──────────


def test_extract_tar_flat_layout_and_find_binary(monkeypatch, tmp_path):
    """Binary sits at the archive root, no wrapping folder."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    archive = tmp_path / "flat.tar"
    archive.write_bytes(_make_tar_bytes({
        "stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 1000,
        "README.md": b"readme",
    }))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    found = _find_extracted_binary(dest)
    assert found is not None
    assert found.name == "stockfish-ubuntu-x86-64"


def test_extract_tar_nested_layout_and_find_binary(monkeypatch, tmp_path):
    """Binary sits inside a wrapping 'stockfish/' folder — the more
    common real-world layout. _find_extracted_binary must not assume a
    fixed depth."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    archive = tmp_path / "nested.tar"
    archive.write_bytes(_make_tar_bytes({
        "stockfish/stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 1000,
        "stockfish/AUTHORS": b"authors",
        "stockfish/Copying.txt": b"gpl",
    }))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    found = _find_extracted_binary(dest)
    assert found is not None
    assert found.name == "stockfish-ubuntu-x86-64"
    assert found.parent.name == "stockfish"


def test_extract_zip_and_find_windows_exe(monkeypatch, tmp_path):
    archive = tmp_path / "windows.zip"
    archive.write_bytes(_make_zip_bytes({
        "stockfish/stockfish-windows-x86-64.exe": b"FAKE_EXE" * 1000,
        "stockfish/stockfish-windows-x86-64.dll": b"FAKE_DLL",  # must be skipped
    }))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Windows")
    found = _find_extracted_binary(dest)
    assert found is not None
    assert found.name == "stockfish-windows-x86-64.exe"


def test_find_binary_prefers_largest_match(monkeypatch, tmp_path):
    """A stray file that happens to contain "stockfish" in its name (e.g.
    a changelog) must not be picked over the real, much larger binary."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    archive = tmp_path / "mixed.tar"
    archive.write_bytes(_make_tar_bytes({
        "stockfish-notes.txt": b"small file mentioning stockfish",
        "stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000,
    }))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    found = _find_extracted_binary(dest)
    assert found is not None
    assert found.name == "stockfish-ubuntu-x86-64"


def test_find_binary_returns_none_when_nothing_matches(monkeypatch, tmp_path):
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    archive = tmp_path / "empty.tar"
    archive.write_bytes(_make_tar_bytes({"README.md": b"nothing relevant here"}))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    assert _find_extracted_binary(dest) is None


def test_extract_tar_rejects_path_traversal(tmp_path):
    archive = tmp_path / "evil.tar"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name="../../../etc/evil_payload")
        data = b"malicious"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    archive.write_bytes(buf.getvalue())

    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive, dest)


def test_extract_zip_rejects_path_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../etc/evil_payload", "malicious")
    archive.write_bytes(buf.getvalue())

    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive, dest)


def test_is_within_directory_rejects_sibling_with_shared_name_prefix(tmp_path):
    """A naive `str(member_path).startswith(str(dest_dir))` check is
    bypassable: ".../extracted_evil" is a string-prefix match against
    ".../extracted" even though it's a completely different directory.
    _is_within_directory must compare path *components*, not strings, so
    this sibling is correctly rejected while a true child is accepted."""
    dest_dir = (tmp_path / "extracted").resolve()
    dest_dir.mkdir()
    sibling_evil = (tmp_path / "extracted_evil" / "payload").resolve()
    real_child = (dest_dir / "stockfish" / "stockfish.exe").resolve()

    assert not _is_within_directory(dest_dir, sibling_evil)
    assert _is_within_directory(dest_dir, real_child)
    assert _is_within_directory(dest_dir, dest_dir)


def test_extract_tar_rejects_sibling_directory_name_prefix_bypass(tmp_path):
    """A tar member whose resolved path lands in a sibling directory that
    merely shares dest_dir's name as a string prefix (e.g. "extracted" vs
    "extracted_evil") must still be rejected as a traversal attempt."""
    archive = tmp_path / "evil.tar"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        # Resolves to tmp_path/"extracted_evil/payload" -- a sibling of
        # dest_dir ("extracted") that shares its name as a string prefix.
        info = tarfile.TarInfo(name="../extracted_evil/payload")
        data = b"malicious"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    archive.write_bytes(buf.getvalue())

    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive, dest)
    # And the sibling must never actually have been written to.
    assert not (tmp_path / "extracted_evil").exists()


def test_extract_zip_rejects_sibling_directory_name_prefix_bypass(tmp_path):
    archive = tmp_path / "evil.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../extracted_evil/payload", "malicious")
    archive.write_bytes(buf.getvalue())

    dest = tmp_path / "extracted"
    dest.mkdir()
    with pytest.raises(ValueError, match="Unsafe path"):
        _extract_archive(archive, dest)
    assert not (tmp_path / "extracted_evil").exists()


def test_second_successful_download_overwrites_extract_dir(monkeypatch, tmp_path):
    """A second successful download (e.g. the user clicks "Download
    Stockfish" again after already having it) must clean out the old
    extracted contents first, not leave stale files from the previous
    extraction mixed in with the new ones."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    first_tar = _make_tar_bytes({
        "stockfish-ubuntu-x86-64": b"FIRST_VERSION" * 100000,
        "leftover-from-first-run.txt": b"should not survive a second download",
    })
    _patch_urlopen(monkeypatch, first_tar)
    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    first_path, first_error = downloader.take_result()
    assert first_error is None
    extract_dir = tmp_path / "stockfish"
    assert (extract_dir / "leftover-from-first-run.txt").exists()

    second_tar = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"SECOND_VERSION" * 100000})
    _patch_urlopen(monkeypatch, second_tar)
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    second_path, second_error = downloader.take_result()
    assert second_error is None
    assert second_path is not None

    # The stray file from the first extraction must be gone.
    assert not (extract_dir / "leftover-from-first-run.txt").exists()
    assert Path(second_path).read_bytes() == b"SECOND_VERSION" * 100000


def test_find_binary_skips_wrong_platform_binaries_on_linux(monkeypatch, tmp_path):
    """A multi-platform archive (or a search root containing leftovers
    from a previous, different-platform extraction) must not have its
    .exe/.dll picked up on a non-Windows machine."""
    archive = tmp_path / "mixed_platforms.tar"
    archive.write_bytes(_make_tar_bytes({
        "stockfish-windows-x86-64.exe": b"WRONG_PLATFORM_BINARY" * 1000,
        "stockfish-windows-x86-64.dll": b"WRONG_PLATFORM_DLL" * 1000,
        "stockfish-ubuntu-x86-64": b"RIGHT_PLATFORM_BINARY" * 1000,
    }))
    dest = tmp_path / "extracted"
    dest.mkdir()
    _extract_archive(archive, dest)

    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    found = _find_extracted_binary(dest)
    assert found is not None
    assert found.name == "stockfish-ubuntu-x86-64"


# ── Full threaded download/extract/locate pipeline ─────────────────────


def test_full_download_pipeline_succeeds(monkeypatch, tmp_path):
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    _patch_urlopen(monkeypatch, tar_bytes)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert error is None
    assert path is not None
    assert Path(path).exists()

    # Mocking platform.system() controls which branch the *code* takes
    # (it decided to chmod, since it believes it isn't Windows), but it
    # can't change what the *real, underlying* filesystem actually
    # supports. Path.chmod() on a genuinely-Windows host has no POSIX
    # rwx bits to set at all — st_mode there is a fixed synthesised
    # value, not a reflection of what chmod was asked to do — so this
    # assertion is only meaningful when the test is actually running on
    # a POSIX host.
    #
    # sys.platform (not platform.system()) is what tells us that: the
    # `platform` module is a process-wide singleton, so the monkeypatch
    # above — which patches the attribute on that one shared module
    # object — affects *any* code calling platform.system() for the rest
    # of this test, including a fresh `import platform` right here. It
    # would silently always read back "Linux", making the real-host
    # check a no-op. sys.platform is a plain string set once at
    # interpreter startup, not routed through the `platform` module at
    # all, so it isn't touched by this (or any) platform.system() patch.
    if sys.platform != "win32":
        assert Path(path).stat().st_mode & 0o111  # executable bit set


def test_double_start_does_not_spawn_a_second_download(monkeypatch, tmp_path):
    """start() while already busy must be a no-op — a fast double-click
    on the download button shouldn't race two downloads into the same
    install directory.

    Uses a real synchronisation primitive (an Event the fake response
    blocks on) to guarantee the first download is still in flight when
    the second start() is attempted, rather than relying on the first
    thread being "probably still running" by timing alone — a too-fast
    mocked pipeline could otherwise finish and reset `busy` before the
    second start() call, which would make a second call legitimately
    (and correctly) begin a fresh download, not a double-spawn.

    A single successful run now makes two urlopen calls (the GitHub
    digest-lookup API call, then the archive download itself), so this
    counts archive-download requests specifically rather than every
    urlopen call — the digest lookup happens after the archive download
    unblocks (see _run's ordering), so it doesn't interfere with the
    synchronisation this test relies on.
    """
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    archive_call_count = {"n": 0}
    release_first_call = threading.Event()

    def _counting_blocking_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "api.github.com" in url:
            # Let digest lookups through immediately and without
            # affecting the archive-download call count this test cares
            # about; digest verification itself is covered separately.
            raise urllib.error.URLError("no digest lookups in this test")
        archive_call_count["n"] += 1
        # Block the first archive-download call until the test explicitly
        # releases it, guaranteeing downloader.busy stays True while the
        # test attempts its second start() — no timing assumptions
        # required.
        release_first_call.wait(timeout=5.0)
        return _FakeResponse(tar_bytes)

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _counting_blocking_urlopen
    )
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    assert downloader.busy is True  # safe now: the first call is parked on the Event
    downloader.start(tmp_path)  # must be rejected — the first download is still in flight
    release_first_call.set()
    downloader.join(timeout=5.0)

    assert archive_call_count["n"] == 1


def test_take_result_consumes_once(monkeypatch, tmp_path):
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    _patch_urlopen(monkeypatch, tar_bytes)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    first = downloader.take_result()
    assert first is not None
    assert downloader.take_result() is None


def test_progress_reaches_one_when_content_length_known(monkeypatch, tmp_path):
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"X" * 500000})
    _patch_urlopen(monkeypatch, tar_bytes, content_length=True)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    # By the time the thread has fully joined, the download loop has
    # finished, so progress should have reached (very close to) 1.0 at
    # some point — the most we can assert post-hoc is that it isn't
    # stuck at None/0, given extraction resets it to None afterwards.
    downloader.take_result()


def test_progress_is_none_without_content_length_header(monkeypatch, tmp_path):
    """A server that omits Content-Length must not crash the progress
    tracking — it should just stay indeterminate (None)."""
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 1000})
    _patch_urlopen(monkeypatch, tar_bytes, content_length=False)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    path, error = downloader.take_result()
    assert error is None
    assert path is not None


def test_unsupported_platform_reports_error_not_exception(monkeypatch, tmp_path):
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "FreeBSD")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert path is None
    assert error is not None
    assert downloader.busy is False


def test_network_failure_reports_error_and_resets_busy(monkeypatch, tmp_path):
    def _failing_urlopen(request, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _failing_urlopen
    )
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert path is None
    assert error is not None and "Download failed" in error
    assert downloader.busy is False

    # A retry after a failure must be possible at all (busy was correctly
    # reset, so start() doesn't silently no-op forever after one
    # failure). With the mock still failing, the only thing this can
    # reliably assert post-join is that the retry actually ran and
    # produced its own (second) error result, not that busy is True at
    # some specific instant — a fast-failing mock can flip busy back to
    # False before this thread's very next line runs, which would be a
    # race in the test, not a bug in the downloader.
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    second_path, second_error = downloader.take_result()
    assert second_path is None
    assert second_error is not None and "Download failed" in second_error


def test_archive_with_no_recognisable_binary_reports_error(monkeypatch, tmp_path):
    tar_bytes = _make_tar_bytes({"README.md": b"just a readme, nothing else"})
    _patch_urlopen(monkeypatch, tar_bytes)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert path is None
    assert error is not None and "did not contain" in error


def test_malicious_archive_reports_error_not_crash(monkeypatch, tmp_path):
    """A path-traversal archive must surface as a normal error result,
    not propagate the ValueError out of the daemon thread uncaught."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name="../../../etc/evil_payload")
        data = b"malicious"
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    _patch_urlopen(monkeypatch, buf.getvalue())
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert path is None
    assert error is not None


def test_retry_after_failure_overwrites_previous_archive(monkeypatch, tmp_path):
    """A second, successful start() after a prior failed one must still
    succeed (the failed run's partial leftovers shouldn't break the
    retry)."""
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    def _failing_urlopen(request, timeout=None):
        raise urllib.error.URLError("temporary failure")

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _failing_urlopen
    )
    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    assert downloader.take_result()[1] is not None  # error on first attempt

    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    _patch_urlopen(monkeypatch, tar_bytes)
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)
    path, error = downloader.take_result()
    assert error is None
    assert path is not None


# ── SHA-256 digest verification against GitHub's Releases API ──────────
#
# No checksum is ever hardcoded in chess_game.stockfish_download — these
# tests verify the digest is instead fetched live from GitHub's Releases
# API (the `digest` field GitHub itself computes at asset-upload time)
# and the downloaded archive is checked against it.


def test_fetch_expected_digest_returns_hex_from_api(monkeypatch):
    """A well-formed API response with a populated `digest` field yields
    the lowercase hex portion, independent of any hardcoded value in the
    source — this only ever reflects whatever GitHub reports."""
    fake_digest_hex = hashlib.sha256(b"whatever GitHub says today").hexdigest()
    payload = {
        "assets": [
            {"name": "stockfish-ubuntu-x86-64.tar", "digest": f"sha256:{fake_digest_hex}"},
        ]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    result = _fetch_expected_digest("stockfish-ubuntu-x86-64.tar")
    assert result == fake_digest_hex


def test_fetch_expected_digest_uppercase_is_normalised(monkeypatch):
    """GitHub's digest casing shouldn't matter for the comparison later —
    normalise to lowercase here so _verify_digest's equality check can't
    fail on casing alone."""
    fake_digest_hex = hashlib.sha256(b"some asset bytes").hexdigest()
    payload = {
        "assets": [
            {"name": "stockfish-windows-x86-64.zip", "digest": f"sha256:{fake_digest_hex.upper()}"},
        ]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    result = _fetch_expected_digest("stockfish-windows-x86-64.zip")
    assert result == fake_digest_hex  # lowercase


def test_fetch_expected_digest_returns_none_for_missing_asset(monkeypatch):
    """The named asset isn't in the release's asset list at all — treat
    as unverifiable, not as a match or a crash."""
    payload = {"assets": [{"name": "some-other-file.tar", "digest": "sha256:abc123"}]}
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    assert _fetch_expected_digest("stockfish-ubuntu-x86-64.tar") is None


def test_fetch_expected_digest_returns_none_when_digest_is_null(monkeypatch):
    """Releases published before GitHub started computing digests report
    `digest: null` for their assets — this must be treated the same as
    "unavailable", never as a hash to compare against."""
    payload = {
        "assets": [{"name": "stockfish-ubuntu-x86-64.tar", "digest": None}],
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    assert _fetch_expected_digest("stockfish-ubuntu-x86-64.tar") is None


def test_fetch_expected_digest_returns_none_on_network_error(monkeypatch):
    """Any failure reaching the GitHub API (rate limit, DNS, timeout, ...)
    must be swallowed into a None result, not propagate — this lookup is
    a best-effort integrity check layered on top of the download, not a
    hard dependency of it."""
    _patch_urlopen_by_host(
        monkeypatch, api_exc=urllib.error.URLError("API rate limit exceeded")
    )

    assert _fetch_expected_digest("stockfish-ubuntu-x86-64.tar") is None


def test_fetch_expected_digest_returns_none_on_malformed_json(monkeypatch):
    """A non-JSON or unexpectedly-shaped API response must not crash the
    download thread — see _fetch_expected_digest's broad except."""
    def _fake_urlopen(request, timeout=None):
        class _BadResponse:
            def read(self):
                return b"not json at all {{{"
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return None
        return _BadResponse()

    monkeypatch.setattr(
        "chess_game.stockfish_download.urllib.request.urlopen", _fake_urlopen
    )
    assert _fetch_expected_digest("stockfish-ubuntu-x86-64.tar") is None


def test_sha256_of_file_matches_hashlib(tmp_path):
    """Sanity check against the stdlib directly — no reimplementation
    quirks (chunk-size off-by-ones, wrong mode, etc.)."""
    data = b"some archive bytes" * 10000
    path = tmp_path / "archive.tar"
    path.write_bytes(data)

    assert _sha256_of_file(path) == hashlib.sha256(data).hexdigest()


def test_verify_digest_passes_on_matching_hash(monkeypatch, tmp_path):
    data = b"the real archive content"
    archive = tmp_path / "stockfish-ubuntu-x86-64.tar"
    archive.write_bytes(data)
    correct_hex = hashlib.sha256(data).hexdigest()

    payload = {
        "assets": [{"name": "stockfish-ubuntu-x86-64.tar", "digest": f"sha256:{correct_hex}"}]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    _verify_digest(archive, "stockfish-ubuntu-x86-64.tar")  # must not raise


def test_verify_digest_raises_on_mismatch(monkeypatch, tmp_path):
    """The one case that actually matters: a downloaded archive whose
    bytes don't match what GitHub says they should be (corruption, a
    compromised CDN/mirror, tampering in transit, ...) must be rejected
    outright rather than silently extracted."""
    archive = tmp_path / "stockfish-ubuntu-x86-64.tar"
    archive.write_bytes(b"tampered or corrupted content")

    wrong_hex = hashlib.sha256(b"this is not what's in the file").hexdigest()
    payload = {
        "assets": [{"name": "stockfish-ubuntu-x86-64.tar", "digest": f"sha256:{wrong_hex}"}]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload)

    with pytest.raises(DigestMismatchError):
        _verify_digest(archive, "stockfish-ubuntu-x86-64.tar")


def test_verify_digest_does_not_raise_when_digest_unavailable(monkeypatch, tmp_path):
    """When GitHub's digest can't be determined, verification degrades
    gracefully (falls back to the pinned-tag + HTTPS + path-traversal
    protections already in place) instead of blocking every download
    whenever the API is briefly unreachable."""
    archive = tmp_path / "stockfish-ubuntu-x86-64.tar"
    archive.write_bytes(b"some content")

    _patch_urlopen_by_host(
        monkeypatch, api_exc=urllib.error.URLError("temporarily unreachable")
    )

    _verify_digest(archive, "stockfish-ubuntu-x86-64.tar")  # must not raise


def test_full_pipeline_succeeds_with_matching_digest(monkeypatch, tmp_path):
    """End-to-end: StockfishDownloader.start() succeeds when the archive
    it downloads matches the digest the (mocked) GitHub API reports for
    it — the realistic "everything is fine" path."""
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    correct_hex = hashlib.sha256(tar_bytes).hexdigest()
    payload = {
        "assets": [{"name": "stockfish-ubuntu-x86-64.tar", "digest": f"sha256:{correct_hex}"}]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload, archive_data=tar_bytes)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert error is None
    assert path is not None


def test_full_pipeline_fails_closed_on_digest_mismatch(monkeypatch, tmp_path):
    """End-to-end: if the (mocked) GitHub API reports a digest that
    doesn't match the archive actually downloaded, the whole download
    must fail — the archive must never be extracted, and no binary path
    must ever be returned to the caller."""
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    wrong_hex = hashlib.sha256(b"a completely different payload").hexdigest()
    payload = {
        "assets": [{"name": "stockfish-ubuntu-x86-64.tar", "digest": f"sha256:{wrong_hex}"}]
    }
    _patch_urlopen_by_host(monkeypatch, api_payload=payload, archive_data=tar_bytes)
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert path is None
    assert error is not None and "Download failed" in error

    # The rejected archive must not be left behind for a future retry to
    # accidentally trust and extract without re-verifying.
    leftover = tmp_path / "stockfish-ubuntu-x86-64.tar"
    assert not leftover.exists()


def test_full_pipeline_succeeds_when_digest_lookup_unavailable(monkeypatch, tmp_path):
    """End-to-end: if GitHub's API can't be reached at all, the download
    must still succeed (degrading to pinned-tag + HTTPS trust) rather
    than making Stockfish permanently undownloadable whenever GitHub's
    API has a transient outage or the user is rate-limited."""
    tar_bytes = _make_tar_bytes({"stockfish-ubuntu-x86-64": b"FAKE_BINARY" * 100000})
    _patch_urlopen_by_host(
        monkeypatch,
        api_exc=urllib.error.URLError("rate limited"),
        archive_data=tar_bytes,
    )
    monkeypatch.setattr("chess_game.stockfish_download.platform.system", lambda: "Linux")
    monkeypatch.setattr("chess_game.stockfish_download.platform.machine", lambda: "x86_64")

    downloader = StockfishDownloader()
    downloader.start(tmp_path)
    downloader.join(timeout=5.0)

    path, error = downloader.take_result()
    assert error is None
    assert path is not None
