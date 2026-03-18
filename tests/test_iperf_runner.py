from config import TestConfig
from collectors.iperf import IperfRunner


def _cfg():
    return TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")


def test_tcp_egress_command():
    r = IperfRunner(_cfg(), "tcp", "egress", 256, 5201, duration=60)
    cmd = r.build_command()
    assert "iperf3" in cmd
    assert "-c" in cmd and "10.0.0.1" in cmd
    assert "-p" in cmd and "5201" in cmd
    assert "-t" in cmd and "60" in cmd
    assert "-J" in cmd
    assert "-R" not in cmd
    assert "--bidir" not in cmd
    assert "-u" not in cmd


def test_tcp_ingress_uses_reverse():
    r = IperfRunner(_cfg(), "tcp", "ingress", 256, 5201)
    cmd = r.build_command()
    assert "-R" in cmd
    assert "--bidir" not in cmd


def test_tcp_bidir():
    r = IperfRunner(_cfg(), "tcp", "bidir", 256, 5201)
    cmd = r.build_command()
    assert "--bidir" in cmd
    assert "-R" not in cmd


def test_udp_flags():
    r = IperfRunner(_cfg(), "udp", "egress", 500, 5201)
    cmd = r.build_command()
    assert "-u" in cmd
    assert "-b" in cmd
    assert "500M" in cmd


def test_udp_small_packet():
    r = IperfRunner(_cfg(), "udp", "egress", 256, 5201, small_packet=True)
    cmd = r.build_command()
    assert "-l" in cmd
    assert "512" in cmd


def test_tcp_high_bandwidth_uses_parallel():
    r = IperfRunner(_cfg(), "tcp", "bidir", 1000, 5201)
    cmd = r.build_command()
    assert "-P" in cmd
    assert "4" in cmd


def test_tcp_low_bandwidth_no_parallel():
    r = IperfRunner(_cfg(), "tcp", "egress", 256, 5201)
    cmd = r.build_command()
    assert "-P" not in cmd
