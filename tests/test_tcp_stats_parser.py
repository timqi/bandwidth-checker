from collectors.tcp_stats import parse_ss_output


def test_parse_ss_single_socket():
    # Real ss -tin output format
    ss_output = """ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43210
\t cubic wscale:7,7 rto:204 rtt:25.5/3.2 ato:40 mss:1448 pmtu:9001 rcvmss:1448 advmss:8949 cwnd:10 bytes_sent:1234567 bytes_received:7654321 segs_out:1000 segs_in:900 data_segs_out:800 data_segs_in:700 send 4.5Mbps pacing_rate 9.0Mbps delivery_rate 4.2Mbps delivered:800 busy:5000ms retrans:0/5 reordering:3"""
    results = parse_ss_output(ss_output)
    assert len(results) == 1
    assert results[0]["rtt_ms"] == 25.5
    assert results[0]["rttvar_ms"] == 3.2
    assert results[0]["cwnd"] == 10
    assert results[0]["retrans_total"] == 5
    assert results[0]["local_port"] == 5201


def test_parse_ss_multiple_sockets():
    ss_output = """ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43210
\t cubic rtt:25.5/3.2 cwnd:10 retrans:0/5
ESTAB 0 0 10.0.0.1:5201 10.0.0.2:43211
\t cubic rtt:30.1/4.0 cwnd:8 retrans:1/10"""
    results = parse_ss_output(ss_output)
    assert len(results) == 2
    assert results[0]["rtt_ms"] == 25.5
    assert results[1]["rtt_ms"] == 30.1


def test_parse_ss_empty():
    results = parse_ss_output("")
    assert results == []
