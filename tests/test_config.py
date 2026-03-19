from config import TestConfig


def test_default_config():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.remote_host == "10.0.0.1"
    assert cfg.iperf_base_port == 5201
    assert cfg.test_duration == 60
    assert cfg.cooldown == 15
    assert cfg.phase2_duration == 2100  # 35 min
    assert cfg.phase3_duration == 600  # 10 min


def test_config_validation_missing_host():
    try:
        TestConfig(remote_host="", remote_user="ec2-user")
        assert False, "Should have raised"
    except ValueError:
        pass


def test_config_data_dir():
    cfg = TestConfig(remote_host="10.0.0.1", remote_user="ec2-user")
    assert cfg.data_dir == "data"
