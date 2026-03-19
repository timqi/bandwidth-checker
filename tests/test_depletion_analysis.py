import csv
import os
import tempfile

from report.generator import detect_depletion_from_csv


def _write_csv(rows, path):
    """Helper to write test CSV data."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["phase_elapsed_sec", "bits_per_second"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def test_detect_depletion_when_present():
    """High throughput then low throughput should detect depletion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "tcp.csv")
        rows = []
        # 50 rows of high throughput (10 Gbps)
        for i in range(50):
            rows.append({"phase_elapsed_sec": i * 10, "bits_per_second": 10_000_000_000})
        # 50 rows of low throughput (800 Mbps)
        for i in range(50):
            rows.append({"phase_elapsed_sec": (50 + i) * 10, "bits_per_second": 800_000_000})
        _write_csv(rows, path)

        result = detect_depletion_from_csv(path)
        assert result["depletion_detected"] is True
        assert result["depletion_time_sec"] is not None
        assert result["burst_mbps"] > 5000
        assert result["baseline_mbps"] < 2000


def test_detect_no_depletion_stable():
    """Uniform throughput should not detect depletion."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "tcp.csv")
        rows = [{"phase_elapsed_sec": i * 10, "bits_per_second": 5_000_000_000} for i in range(100)]
        _write_csv(rows, path)

        result = detect_depletion_from_csv(path)
        assert result["depletion_detected"] is False


def test_detect_insufficient_data():
    """Less than 10 rows should return empty dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "tcp.csv")
        rows = [{"phase_elapsed_sec": i * 10, "bits_per_second": 5_000_000_000} for i in range(5)]
        _write_csv(rows, path)

        result = detect_depletion_from_csv(path)
        assert result == {}


def test_detect_missing_file():
    """Missing file should return empty dict."""
    result = detect_depletion_from_csv("/nonexistent/file.csv")
    assert result == {}


def test_depletion_time_near_transition():
    """Depletion time should be near the actual transition, not far after."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "tcp.csv")
        rows = []
        # 30 rows high
        for i in range(30):
            rows.append({"phase_elapsed_sec": i * 10, "bits_per_second": 10_000_000_000})
        # 70 rows low
        for i in range(70):
            rows.append({"phase_elapsed_sec": (30 + i) * 10, "bits_per_second": 800_000_000})
        _write_csv(rows, path)

        result = detect_depletion_from_csv(path)
        assert result["depletion_detected"] is True
        # Depletion time should be around 290s (last high row at index 29, time=290)
        assert 280 <= result["depletion_time_sec"] <= 300
