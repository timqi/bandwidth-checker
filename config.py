from dataclasses import dataclass


@dataclass
class TestConfig:
    remote_host: str
    remote_user: str
    ssh_key: str = ""
    iperf_base_port: int = 5201
    test_duration: int = 60          # seconds per individual test
    cooldown: int = 15               # seconds between tests
    phase2_duration: int = 2100      # 35 min
    phase3_duration: int = 600       # 10 min
    data_dir: str = "data"
    tcp_parallel_streams: int = 4    # -P flag for iperf3
    udp_target_rate: str = "5G"      # -b flag for iperf3 UDP

    def __post_init__(self):
        if not self.remote_host:
            raise ValueError("remote_host is required")
        if not self.remote_user:
            raise ValueError("remote_user is required")
