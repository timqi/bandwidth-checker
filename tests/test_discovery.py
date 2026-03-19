from discovery import generate_step_up_levels


def test_generate_levels_from_ceiling():
    """Levels are percentages of burst ceiling."""
    levels = generate_step_up_levels(10000)
    bws = [l["bandwidth_mbps"] for l in levels]
    assert bws == [2000, 5000, 8000, 9000, 10000, 12000, 15000, 20000]


def test_generate_levels_small_ceiling():
    """Works with small ceiling values."""
    levels = generate_step_up_levels(500)
    bws = [l["bandwidth_mbps"] for l in levels]
    assert bws == [100, 250, 400, 450, 500, 600, 750, 1000]


def test_level_directions():
    """Lower levels test egress+ingress, higher levels test bidir."""
    levels = generate_step_up_levels(10000)
    # First level (20%) — egress + ingress
    assert levels[0]["tcp_directions"] == ["egress", "ingress"]
    assert levels[0]["udp_directions"] == ["egress", "ingress"]
    # Middle levels (50%+) — add bidir
    assert "bidir" in levels[1]["tcp_directions"]
    # Top levels (100%+) — bidir only
    assert levels[4]["tcp_directions"] == ["bidir"]


def test_level_rounding():
    """Bandwidth values are rounded to integers."""
    levels = generate_step_up_levels(1234)
    for l in levels:
        assert isinstance(l["bandwidth_mbps"], int)


def test_zero_ceiling_returns_empty():
    """Zero ceiling returns empty list."""
    assert generate_step_up_levels(0) == []


def test_negative_ceiling_returns_empty():
    assert generate_step_up_levels(-100) == []


def test_small_ceiling_deduplicates():
    """Very small ceiling doesn't produce duplicate bandwidth values."""
    levels = generate_step_up_levels(3)
    bws = [l["bandwidth_mbps"] for l in levels]
    assert len(bws) == len(set(bws)), f"Duplicate values found: {bws}"


def test_small_packet_udp_at_50pct():
    """The 50% level includes small_packet_udp flag."""
    levels = generate_step_up_levels(10000)
    level_50pct = [l for l in levels if l["bandwidth_mbps"] == 5000][0]
    assert level_50pct.get("small_packet_udp") is True
    # Other levels should not have it
    other_levels = [l for l in levels if l["bandwidth_mbps"] != 5000]
    for l in other_levels:
        assert "small_packet_udp" not in l or not l["small_packet_udp"]
