"""TCP socket statistics collection via ss."""
import csv
import os
import re
import subprocess
import threading
import time
from typing import Any, Dict, List

_RTT_RE = re.compile(r"rtt:([\d.]+)/([\d.]+)")
_CWND_RE = re.compile(r"cwnd:(\d+)")
_RETRANS_RE = re.compile(r"retrans:(\d+)/(\d+)")
_ESTAB_RE = re.compile(
    r"ESTAB\s+\d+\s+\d+\s+([\d.]+):(\d+)\s+([\d.]+):(\d+)"
)


def parse_ss_output(output: str) -> List[Dict[str, Any]]:
    """Parse ss -tin output into a list of per-socket dicts."""
    if not output.strip():
        return []

    results = []
    lines = output.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _ESTAB_RE.match(line)
        if m:
            entry: Dict[str, Any] = {
                "local_addr": m.group(1),
                "local_port": int(m.group(2)),
                "remote_addr": m.group(3),
                "remote_port": int(m.group(4)),
                "rtt_ms": 0.0,
                "rttvar_ms": 0.0,
                "cwnd": 0,
                "retrans_current": 0,
                "retrans_total": 0,
            }
            detail = ""
            while i + 1 < len(lines) and not _ESTAB_RE.match(lines[i + 1]):
                i += 1
                detail += " " + lines[i]

            m2 = _RTT_RE.search(detail)
            if m2:
                entry["rtt_ms"] = float(m2.group(1))
                entry["rttvar_ms"] = float(m2.group(2))

            m2 = _CWND_RE.search(detail)
            if m2:
                entry["cwnd"] = int(m2.group(1))

            m2 = _RETRANS_RE.search(detail)
            if m2:
                entry["retrans_current"] = int(m2.group(1))
                entry["retrans_total"] = int(m2.group(2))

            results.append(entry)
        i += 1
    return results


def write_ss_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Append ss stats rows to CSV."""
    if not rows:
        return
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


class TcpStatsCollector:
    """Poll ss for TCP stats at regular intervals."""

    def __init__(self, remote_host: str, csv_path: str, interval: float = 1.0):
        self.remote_host = remote_host
        self.csv_path = csv_path
        self.interval = interval
        self._thread: threading.Thread = None
        self._stop = threading.Event()
        self.samples: list = []

    def start(self) -> None:
        """Start polling thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._poller, daemon=True)
        self._thread.start()

    def _poller(self) -> None:
        """Poll ss every interval."""
        while not self._stop.is_set():
            try:
                result = subprocess.run(
                    ["ss", "-tin", "dst", self.remote_host],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    entries = parse_ss_output(result.stdout)
                    ts = time.time()
                    for entry in entries:
                        entry["timestamp"] = ts
                    self.samples.extend(entries)
                    write_ss_csv(entries, self.csv_path)
            except (subprocess.TimeoutExpired, OSError):
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        """Stop polling thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def get_aggregate(self, last_n_polls: int = 5) -> dict:
        """Return aggregate stats from last N polling rounds.

        Groups samples by timestamp (each poll produces multiple socket entries),
        then aggregates across the last N polls.
        """
        if not self.samples:
            return {"rtt_ms": 0, "cwnd": 0, "retrans_total": 0}

        from collections import defaultdict
        polls = defaultdict(list)
        for s in self.samples:
            polls[s["timestamp"]].append(s)

        sorted_polls = sorted(polls.items(), key=lambda x: x[0])
        recent_polls = sorted_polls[-last_n_polls:]

        if not recent_polls:
            return {"rtt_ms": 0, "cwnd": 0, "retrans_total": 0}

        poll_rtts = []
        poll_cwnds = []
        poll_retrans = []
        for _ts, entries in recent_polls:
            if entries:
                poll_rtts.append(sum(e["rtt_ms"] for e in entries) / len(entries))
                poll_cwnds.append(sum(e["cwnd"] for e in entries))
                poll_retrans.append(sum(e["retrans_total"] for e in entries))

        return {
            "rtt_ms": sum(poll_rtts) / len(poll_rtts) if poll_rtts else 0,
            "cwnd": sum(poll_cwnds) / len(poll_cwnds) if poll_cwnds else 0,
            "retrans_total": max(poll_retrans) if poll_retrans else 0,
        }
