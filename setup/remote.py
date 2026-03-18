"""Remote iperf3 server management via SSH."""
import subprocess
import sys
from typing import Optional

from config import TestConfig


def _ssh_cmd(cfg: TestConfig) -> list:
    """Build base SSH command."""
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
    if cfg.ssh_key:
        cmd.extend(["-i", cfg.ssh_key])
    cmd.append(f"{cfg.remote_user}@{cfg.remote_host}")
    return cmd


def run_ssh(cfg: TestConfig, remote_cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a command on the remote host via SSH."""
    cmd = _ssh_cmd(cfg) + [remote_cmd]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def check_ssh(cfg: TestConfig) -> bool:
    """Verify SSH connectivity."""
    try:
        result = run_ssh(cfg, "echo ok", timeout=10)
        return result.returncode == 0 and "ok" in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def check_iperf3(cfg: TestConfig) -> bool:
    """Verify iperf3 is installed on remote."""
    try:
        result = run_ssh(cfg, "iperf3 --version", timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def kill_remote_iperf3(cfg: TestConfig) -> None:
    """Kill any existing iperf3 processes on remote."""
    run_ssh(cfg, "pkill -f iperf3 || true", timeout=10)


def start_remote_iperf3(cfg: TestConfig, port: int) -> bool:
    """Start iperf3 server on remote at given port."""
    run_ssh(cfg, f"nohup iperf3 -s -p {port} > /dev/null 2>&1 &", timeout=10)
    import time
    time.sleep(1)  # Give it a moment to start
    # Verify it's running
    result = run_ssh(cfg, f"ss -tln | grep :{port}", timeout=10)
    return result.returncode == 0


def setup_remote_servers(cfg: TestConfig, ports: Optional[list] = None) -> bool:
    """Full remote setup: kill stale, start fresh servers, verify reachability."""
    if ports is None:
        ports = [cfg.iperf_base_port, cfg.iperf_base_port + 1]

    print("Pre-flight: checking SSH connectivity...", flush=True)
    if not check_ssh(cfg):
        print("ERROR: Cannot SSH to remote host", file=sys.stderr)
        return False

    print("Pre-flight: checking iperf3 on remote...", flush=True)
    if not check_iperf3(cfg):
        print("ERROR: iperf3 not found on remote", file=sys.stderr)
        return False

    print("Pre-flight: killing stale iperf3 processes...", flush=True)
    kill_remote_iperf3(cfg)

    for port in ports:
        print(f"Pre-flight: starting iperf3 server on port {port}...", flush=True)
        if not start_remote_iperf3(cfg, port):
            print(f"ERROR: Failed to start iperf3 on port {port}", file=sys.stderr)
            return False

    # Verify ports are reachable through security group (actual iperf3 handshake)
    print("Pre-flight: verifying port reachability (iperf3 handshake)...", flush=True)
    for port in ports:
        try:
            result = subprocess.run(
                ["iperf3", "-c", cfg.remote_host, "-p", str(port), "-t", "1"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                print(f"ERROR: Cannot reach iperf3 on port {port} — check security group", file=sys.stderr)
                return False
        except subprocess.TimeoutExpired:
            print(f"ERROR: iperf3 handshake timeout on port {port} — check security group", file=sys.stderr)
            return False

    print("Pre-flight: all checks passed.", flush=True)
    return True


def burst_credit_probe(cfg: TestConfig) -> Optional[float]:
    """Run a 30-second TCP test to check current burst credit state.

    Returns average throughput in Mbps, or None on failure.
    """
    import json
    cmd = [
        "iperf3", "-c", cfg.remote_host,
        "-p", str(cfg.iperf_base_port),
        "-t", "30", "-J",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        bps = data["end"]["sum_received"]["bits_per_second"]
        return bps / 1_000_000
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
        return None
