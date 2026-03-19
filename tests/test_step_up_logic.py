from phases.step_up import _check_limitation


def test_check_limitation_detects_below_50pct():
    results = [{"protocol": "tcp", "iperf_rows": [{"bits_per_second": 200_000_000}]}]
    assert _check_limitation(results, 1000)  # 200 Mbps < 500 Mbps (50% of 1000)


def test_check_limitation_no_false_positive():
    results = [{"protocol": "tcp", "iperf_rows": [{"bits_per_second": 600_000_000}]}]
    assert not _check_limitation(results, 1000)  # 600 Mbps > 500 Mbps


def test_check_limitation_ignores_udp():
    results = [{"protocol": "udp", "iperf_rows": [{"bits_per_second": 100_000_000}]}]
    assert not _check_limitation(results, 1000)  # UDP is ignored


def test_check_limitation_empty_results():
    assert not _check_limitation([], 1000)


def test_check_limitation_no_rows():
    results = [{"protocol": "tcp", "iperf_rows": []}]
    assert not _check_limitation(results, 1000)
