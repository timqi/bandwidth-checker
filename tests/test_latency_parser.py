from collectors.latency import parse_ping_line, parse_ping_summary


def test_parse_ping_reply():
    line = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=25.3 ms"
    result = parse_ping_line(line)
    assert result == {"icmp_seq": 1, "ttl": 64, "time_ms": 25.3}


def test_parse_ping_timeout():
    line = "Request timeout for icmp_seq 5"
    result = parse_ping_line(line)
    assert result is None


def test_parse_ping_summary():
    lines = [
        "--- 10.0.0.1 ping statistics ---",
        "10 packets transmitted, 9 received, 10% packet loss, time 9012ms",
        "rtt min/avg/max/mdev = 20.1/25.3/35.7/4.2 ms",
    ]
    result = parse_ping_summary(lines)
    assert result["packets_sent"] == 10
    assert result["packets_received"] == 9
    assert result["loss_percent"] == 10.0
    assert result["rtt_min"] == 20.1
    assert result["rtt_avg"] == 25.3
    assert result["rtt_max"] == 35.7


def test_parse_ping_line_garbage():
    result = parse_ping_line("PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.")
    assert result is None
