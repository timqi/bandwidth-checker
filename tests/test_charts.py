import os
import tempfile
from report.charts import generate_step_up_charts


def test_generate_step_up_charts_creates_files():
    """Test that chart generation creates PNG files from sample data."""
    tcp_data = [
        {"level_mbps": 50, "bits_per_second": 50000000, "retransmits": 0, "direction": "egress"},
        {"level_mbps": 256, "bits_per_second": 256000000, "retransmits": 5, "direction": "egress"},
        {"level_mbps": 1000, "bits_per_second": 900000000, "retransmits": 20, "direction": "bidir"},
    ]
    udp_data = [
        {"level_mbps": 50, "lost_percent": 0, "jitter_ms": 0.1, "direction": "egress"},
        {"level_mbps": 256, "lost_percent": 1.5, "jitter_ms": 0.8, "direction": "egress"},
        {"level_mbps": 1000, "lost_percent": 10, "jitter_ms": 2.5, "direction": "bidir"},
    ]
    ping_data = [
        {"level_mbps": 50, "rtt_avg": 25.0},
        {"level_mbps": 256, "rtt_avg": 28.0},
        {"level_mbps": 1000, "rtt_avg": 45.0},
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = generate_step_up_charts(tcp_data, udp_data, ping_data, tmpdir)
        assert len(paths) == 5
        for p in paths:
            assert os.path.exists(p)
            assert p.endswith(".png")
