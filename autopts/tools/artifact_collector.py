"""AutoPTS per-test artefact collector.

This module provides a singleton :class:`ArtifactCollector` that coordinates
two kinds of artefacts for every AutoPTS test run:

1. **PTS Automation-Mode log** — one ``pts_automation_mode.log`` per test,
   populated by :meth:`ArtifactCollector.append_pts_log` which is called
   from ``ClientCallback.log()`` in ``client.py``.

2. **Result manifest** — ``autopts_result.json`` written at the end of each
   test; consumed by ``tools/autopts_report.py`` to build the HTML report.

Usage in ``testcase.py``
------------------------
::

    from autopts.tools.artifact_collector import get_collector

    # in TestCase.pre_run():
    get_collector().on_test_start(self)

    # in TestCase.post_run(error_code):
    get_collector().on_test_end(self, error_code)

Usage in ``client.py``
-----------------------
::

    from autopts.tools.artifact_collector import get_collector

    # in ClientCallback.log():
    get_collector().append_pts_log(
        test_case_name, logtype_string, log_time, log_message
    )

Configuration
-------------
Call :func:`configure` once from the client entry-point (e.g.
``autoptsclient-zephyr.py``) before any tests run::

    from autopts.tools.artifact_collector import configure
    configure(enabled=True)
"""

import datetime
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ── Module-level config ───────────────────────────────────────────────────────

_enabled: bool = bool(int(os.environ.get("AUTOPTS_ARTIFACTS", "1")))
_instance: Optional["ArtifactCollector"] = None
_instance_lock = threading.Lock()


def configure(
    enabled: bool = True,
) -> None:
    """Configure artifact collection before tests run.

    Parameters
    ----------
    enabled:
        Master switch.  Set to ``False`` to disable all collection silently.
    Additional sniffer-related parameters were intentionally removed. This
    collector now handles only AutoPTS + PTS logs and result manifests.
    """
    global _enabled, _instance
    _enabled = enabled
    with _instance_lock:
        _instance = None  # force re-creation


def get_collector() -> "ArtifactCollector":
    """Return the module-level :class:`ArtifactCollector` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ArtifactCollector()
    return _instance


# ── ArtifactCollector ─────────────────────────────────────────────────────────

class ArtifactCollector:
    """Collects per-test artefacts: PTS log and result JSON.

    This class is thread-safe.  Multiple LT-threads can call
    :meth:`on_test_start` / :meth:`on_test_end` concurrently; each test's
    state is isolated by the test's ``name`` key.
    """

    def __init__(self):
        # Per-test state: { tc_name → _TestArtefacts }
        self._tests: dict[str, "_TestArtefacts"] = {}
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────

    def on_test_start(self, test_case) -> None:
        """Called at the end of :meth:`TestCase.pre_run`.

        Parameters
        ----------
        test_case:
            A :class:`autopts.ptsprojects.testcase.TestCase` instance.
            Must have ``name``, ``project_name``, and ``log_dir`` attributes.
        """
        if not _enabled:
            return
        tc = _TestArtefacts(test_case)
        with self._lock:
            self._tests[test_case.name] = tc
        tc.open_pts_log()

    def on_test_end(self, test_case, error_code: Optional[str]) -> None:
        """Called at the start of :meth:`TestCase.post_run`, before ``sleep(3)``.

        Parameters
        ----------
        test_case:
            Same instance passed to :meth:`on_test_start`.
        error_code:
            Error string from PTS (or ``None`` on clean run).
        """
        if not _enabled:
            return
        with self._lock:
            tc = self._tests.get(test_case.name)
        if tc is None:
            log.warning("on_test_end called for unknown test %r", test_case.name)
            return
        tc.finalize(test_case)
        with self._lock:
            self._tests.pop(test_case.name, None)

    def append_pts_log(
        self,
        test_case_name: str,
        logtype_string: str,
        log_time: str,
        log_message: str,
    ) -> None:
        """Append one PTS log line to the per-test ``pts_automation_mode.log``.

        Called from ``ClientCallback.log()`` in ``client.py`` on every PTS
        event.  Thread-safe.
        """
        if not _enabled:
            return
        with self._lock:
            tc = self._tests.get(test_case_name)
        if tc is None:
            return  # test not yet started or already finished — silently ignore
        tc.append_pts_log(logtype_string, log_time, log_message)


# ── Per-test state ────────────────────────────────────────────────────────────

class _TestArtefacts:
    """Holds open file handles and timing for one test case."""

    PTS_LOG_FILENAME = "pts_automation_mode.log"
    MANIFEST_FILENAME = "autopts_result.json"

    def __init__(self, test_case):
        self.name: str = test_case.name
        self.project: str = getattr(test_case, "project_name", "")
        self.log_dir: str = getattr(test_case, "log_dir", "")
        self.start_time: datetime.datetime = datetime.datetime.now()
        self._pts_log_fh = None
        self._pts_log_lock = threading.Lock()

    # ── PTS log ───────────────────────────────────────────────────────────────

    def open_pts_log(self) -> None:
        if not self.log_dir:
            return
        try:
            path = os.path.join(self.log_dir, self.PTS_LOG_FILENAME)
            self._pts_log_fh = open(path, "w", encoding="utf-8")
            self._pts_log_fh.write(
                f"# PTS Automation Mode log — {self.name}\n"
                f"# Started: {self.start_time.isoformat(timespec='seconds')}\n\n"
            )
            self._pts_log_fh.flush()
        except OSError as exc:
            log.error("Cannot open PTS log for %r: %s", self.name, exc)
            self._pts_log_fh = None

    def append_pts_log(self, logtype_string: str, log_time: str, log_message: str) -> None:
        with self._pts_log_lock:
            if self._pts_log_fh is None:
                return
            try:
                self._pts_log_fh.write(f"[{log_time}] [{logtype_string}] {log_message}\n")
                self._pts_log_fh.flush()
            except OSError as exc:
                log.error("PTS log write failed for %r: %s", self.name, exc)

    def _close_pts_log(self) -> None:
        with self._pts_log_lock:
            if self._pts_log_fh is not None:
                try:
                    self._pts_log_fh.close()
                except OSError:
                    pass
                self._pts_log_fh = None

    def finalize(self, test_case) -> None:
        """Close PTS log and write result manifest."""
        end_time = datetime.datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        # Close the PTS log file
        self._close_pts_log()

        # Write the result manifest
        if self.log_dir:
            self._write_manifest(test_case, end_time, duration)

    def _write_manifest(
        self,
        test_case,
        end_time: datetime.datetime,
        duration: float,
    ) -> None:
        status = getattr(test_case, "status", "UNKNOWN")
        log_filename = getattr(test_case, "log_filename", "")
        log_dir = self.log_dir

        def _rel(path_str: Optional[str]) -> Optional[str]:
            """Return path relative to log_dir, or None."""
            if not path_str:
                return None
            try:
                return str(Path(path_str).relative_to(log_dir))
            except ValueError:
                return path_str  # not under log_dir — return as-is

        pts_log_abs = os.path.join(log_dir, self.PTS_LOG_FILENAME)
        manifest = {
            "name": self.name,
            "project": self.project,
            "status": status,
            "start_time": self.start_time.isoformat(timespec="seconds"),
            "end_time": end_time.isoformat(timespec="seconds"),
            "duration_s": round(duration, 2),
            "log_dir": log_dir,
            "autopts_log": _rel(log_filename),
            "pts_log": self.PTS_LOG_FILENAME if os.path.exists(pts_log_abs) else None,
            "sniffer_capture": None,
        }
        dest = os.path.join(log_dir, self.MANIFEST_FILENAME)
        try:
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)
            log.debug("Result manifest written: %s", dest)
        except OSError as exc:
            log.error("Failed to write manifest for %r: %s", self.name, exc)
