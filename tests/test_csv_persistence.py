import csv
import os
import tempfile
from collectors.iperf import write_iperf_csv


def test_write_csv_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        rows = [
            {"start": 0, "end": 1, "bits_per_second": 256000000, "retransmits": 2},
            {"start": 1, "end": 2, "bits_per_second": 248000000, "retransmits": 5},
        ]
        write_iperf_csv(rows, path)
        assert os.path.exists(path)
        with open(path) as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert len(read_rows) == 2
        assert read_rows[0]["retransmits"] == "2"


def test_write_csv_appends():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        rows1 = [{"start": 0, "end": 1, "bits_per_second": 256000000}]
        rows2 = [{"start": 1, "end": 2, "bits_per_second": 248000000}]
        write_iperf_csv(rows1, path)
        write_iperf_csv(rows2, path)
        with open(path) as f:
            reader = csv.DictReader(f)
            read_rows = list(reader)
        assert len(read_rows) == 2


def test_write_csv_empty_rows():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.csv")
        write_iperf_csv([], path)
        assert not os.path.exists(path)
