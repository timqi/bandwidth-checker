import os
import tempfile
from report.generator import generate_step_up_report


def test_generate_step_up_report_creates_html():
    step_up_results = [
        {
            "label": "50M_tcp_egress",
            "iperf_rows": [{"bits_per_second": 50000000, "retransmits": 0}],
            "avg_rtt": 25.0,
            "ping_samples": 60,
            "ss_aggregate": {"rtt_ms": 25.0, "cwnd": 10, "retrans_total": 0},
        },
        {
            "label": "256M_tcp_egress",
            "iperf_rows": [{"bits_per_second": 256000000, "retransmits": 5}],
            "avg_rtt": 30.0,
            "ping_samples": 60,
            "ss_aggregate": {"rtt_ms": 30.0, "cwnd": 8, "retrans_total": 5},
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_step_up_report(step_up_results, tmpdir)
        assert os.path.exists(path)
        assert path.endswith(".html")
        with open(path) as f:
            html = f.read()
        assert "50M_tcp_egress" in html
        assert "256M_tcp_egress" in html
        assert "<table" in html
