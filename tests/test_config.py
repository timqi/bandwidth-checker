from config import TestConfig


def test_default_config():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.remote_host == "10.0.0.1"
    assert cfg.iperf_base_port == 5201
    assert cfg.test_duration == 60
    assert cfg.cooldown == 15
    assert cfg.phase2_timeout == 2100  # 35 min
    assert cfg.phase3_duration == 600  # 10 min
    assert cfg.depletion_threshold_mbps == 300
    assert cfg.depletion_window_sec == 10


def test_config_validation_missing_host():
    try:
        TestConfig(remote_host="", remote_user="ec2-user")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_config_data_dir():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.data_dir == "data"


def test_step_up_levels():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    levels = cfg.step_up_levels
    assert levels[0]["bandwidth_mbps"] == 50
    assert levels[-1]["bandwidth_mbps"] == 5000
    # 256 Mbps level should have all directions
    level_256 = [l for l in levels if l["bandwidth_mbps"] == 256][0]
    assert "egress" in level_256["tcp_directions"]
    assert "ingress" in level_256["tcp_directions"]
    assert "bidir" in level_256["tcp_directions"]
