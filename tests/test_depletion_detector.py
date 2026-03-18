from phases.sustained import DepletionDetector


def test_not_depleted_above_threshold():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(15):
        d.add_sample(350_000_000)  # 350 Mbps in bps
    assert not d.is_depleted


def test_depleted_below_threshold():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(10):
        d.add_sample(250_000_000)  # 250 Mbps
    assert d.is_depleted


def test_not_depleted_short_window():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(9):  # only 9 samples, need 10
        d.add_sample(250_000_000)
    assert not d.is_depleted


def test_recovery_resets():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(8):
        d.add_sample(250_000_000)
    d.add_sample(500_000_000)  # spike above threshold
    for _ in range(5):
        d.add_sample(250_000_000)
    assert not d.is_depleted  # window reset by the spike


def test_stays_depleted_once_detected():
    d = DepletionDetector(threshold_mbps=300, window_sec=10)
    for _ in range(10):
        d.add_sample(250_000_000)
    assert d.is_depleted
    d.add_sample(500_000_000)  # spike doesn't undo depletion
    assert d.is_depleted
