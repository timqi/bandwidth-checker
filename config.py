from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class TestConfig:
    remote_host: str
    remote_user: str
    ssh_key: str = ""
    iperf_base_port: int = 5201
    test_duration: int = 60          # seconds per individual test
    cooldown: int = 15               # seconds between tests
    phase2_timeout: int = 2100       # 35 min hard cap
    phase3_duration: int = 600       # 10 min
    depletion_threshold_mbps: int = 300
    depletion_window_sec: int = 10
    data_dir: str = "data"
    tcp_parallel_streams: int = 4    # -P flag for iperf3
    udp_target_rate: str = "5G"      # -b flag for iperf3 UDP

    def __post_init__(self):
        if not self.remote_host:
            raise ValueError("remote_host is required")
        if not self.remote_user:
            raise ValueError("remote_user is required")

    @property
    def step_up_levels(self) -> List[Dict[str, Any]]:
        return [
            {
                "bandwidth_mbps": 50,
                "tcp_directions": ["egress"],
                "udp_directions": ["egress"],
            },
            {
                "bandwidth_mbps": 128,
                "tcp_directions": ["egress"],
                "udp_directions": ["egress"],
            },
            {
                "bandwidth_mbps": 256,
                "tcp_directions": ["egress", "ingress", "bidir"],
                "udp_directions": ["egress", "ingress", "bidir"],
                "small_packet_udp": True,
            },
            {
                "bandwidth_mbps": 512,
                "tcp_directions": ["egress", "bidir"],
                "udp_directions": ["egress", "bidir"],
            },
            {
                "bandwidth_mbps": 1000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
            {
                "bandwidth_mbps": 2000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
            {
                "bandwidth_mbps": 5000,
                "tcp_directions": ["bidir"],
                "udp_directions": ["bidir"],
            },
        ]
