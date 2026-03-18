"""Phase 2: Sustained full-load until credit depletion."""


class DepletionDetector:
    """Detect network credit depletion from throughput samples."""

    def __init__(self, threshold_mbps: int = 300, window_sec: int = 10):
        self._threshold_bps = threshold_mbps * 1_000_000
        self._window = window_sec
        self._consecutive_below = 0
        self._detected = False

    def add_sample(self, bits_per_second: float) -> None:
        """Add a 1-second throughput sample."""
        if self._detected:
            return
        if bits_per_second < self._threshold_bps:
            self._consecutive_below += 1
        else:
            self._consecutive_below = 0
        if self._consecutive_below >= self._window:
            self._detected = True

    @property
    def is_depleted(self) -> bool:
        return self._detected
