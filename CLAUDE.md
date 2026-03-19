# Bandwidth Checker

AWS EC2 bandwidth testing tool. Measures burst ceiling, credit depletion, and throttling behavior.

## Quick Reference

```bash
uv sync                                          # install deps
uv run python -m pytest tests/ -v                # run tests (45 tests)
uv run python run_test.py --host IP --no-ssh     # run test (remote iperf3 must be running)
uv run python run_test.py --host IP --no-ssh --ceiling 12500  # skip auto-discovery
```

## Architecture

```
run_test.py          Entry point, CLI args, signal handling, phase orchestration
config.py            TestConfig dataclass
discovery.py         Auto-discover burst ceiling, generate step-up levels
cleanup.py           Global cleanup registry for SIGINT/SIGTERM

collectors/
  iperf.py           IperfRunner class + iperf3 JSON parser + CSV writer
  latency.py         LatencyCollector (background ping)
  tcp_stats.py       TcpStatsCollector (background ss -tin polling)

phases/
  step_up.py         Phase 1: step-up pressure test with early-stop
  sustained.py       Phase 2: sustained full-load for fixed duration
  throttled.py       Phase 3: throttled state observation + mini step-up

setup/
  remote.py          SSH helpers, remote iperf3 server management

report/
  charts.py          matplotlib PNG chart generation
  generator.py       HTML report generation + CSV-based depletion detection
```

## Key Design Decisions

- **Auto-discovery**: 10s unbounded TCP test finds burst ceiling; step-up levels are 20/50/80/90/100/120/150/200% of ceiling
- **No real-time depletion detection**: Phase 2 runs fixed duration; depletion is detected post-hoc from CSV data using backward scan
- **Early stop in Phase 1**: If TCP throughput < 50% of target for 2 consecutive levels, stop
- **Cleanup registry**: All phases register IperfRunners and collectors so SIGINT kills them
- **CSV append mode**: Data persists incrementally; auto-timestamped data dirs prevent mixing runs
- **Two iperf3 ports**: 5201 for TCP, 5202 for UDP (iperf3 is single-threaded per server)
- **`--no-ssh` mode**: Skips SSH-based remote setup; user manually starts iperf3 servers

## Testing

Tests are pure unit tests — no iperf3/network needed. They test parsers, config, discovery logic, depletion analysis, and chart generation.

```bash
uv run python -m pytest tests/ -v    # all tests
uv run python -m pytest tests/test_discovery.py -v  # specific file
```

## Dependencies

- Python 3.10+
- matplotlib (charts)
- pytest (testing)
- iperf3 (system binary, not a Python package)
