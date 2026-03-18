import json
from collectors.iperf import parse_iperf_tcp_json, parse_iperf_udp_json

# Minimal iperf3 TCP JSON structure
SAMPLE_TCP_JSON = {
    "intervals": [
        {
            "sum": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 32000000, "bits_per_second": 256000000, "retransmits": 2,
            }
        },
        {
            "sum": {
                "start": 1, "end": 2, "seconds": 1,
                "bytes": 31000000, "bits_per_second": 248000000, "retransmits": 5,
            }
        },
    ],
    "end": {
        "sum_sent": {"bytes": 63000000, "bits_per_second": 252000000},
        "sum_received": {"bytes": 62000000, "bits_per_second": 248000000},
    },
}

SAMPLE_TCP_BIDIR_JSON = {
    "intervals": [
        {
            "sum_sent": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 32000000, "bits_per_second": 256000000, "retransmits": 1,
            },
            "sum_received": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 30000000, "bits_per_second": 240000000,
            },
        },
    ],
}

SAMPLE_UDP_JSON = {
    "intervals": [
        {
            "sum": {
                "start": 0, "end": 1, "seconds": 1,
                "bytes": 32000000, "bits_per_second": 256000000,
                "lost_packets": 10, "packets": 1000, "lost_percent": 1.0, "jitter_ms": 0.5,
            }
        },
        {
            "sum": {
                "start": 1, "end": 2, "seconds": 1,
                "bytes": 30000000, "bits_per_second": 240000000,
                "lost_packets": 50, "packets": 1000, "lost_percent": 5.0, "jitter_ms": 1.2,
            }
        },
    ],
}


def test_parse_tcp_intervals():
    rows = parse_iperf_tcp_json(SAMPLE_TCP_JSON)
    assert len(rows) == 2
    assert rows[0]["bits_per_second"] == 256000000
    assert rows[0]["retransmits"] == 2
    assert rows[1]["retransmits"] == 5


def test_parse_tcp_bidir():
    """--bidir output uses sum_sent/sum_received instead of sum."""
    rows = parse_iperf_tcp_json(SAMPLE_TCP_BIDIR_JSON)
    assert len(rows) == 1
    assert rows[0]["bits_per_second"] == 256000000 + 240000000
    assert rows[0]["retransmits"] == 1


def test_parse_udp_intervals():
    rows = parse_iperf_udp_json(SAMPLE_UDP_JSON)
    assert len(rows) == 2
    assert rows[0]["lost_percent"] == 1.0
    assert rows[0]["jitter_ms"] == 0.5
    assert rows[1]["lost_packets"] == 50


def test_parse_tcp_empty():
    rows = parse_iperf_tcp_json({"intervals": []})
    assert rows == []


def test_parse_udp_empty():
    rows = parse_iperf_udp_json({"intervals": []})
    assert rows == []
