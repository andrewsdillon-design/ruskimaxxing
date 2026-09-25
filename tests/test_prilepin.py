import pytest

from ruskimaxxing.prilepin import load, zone_for


@pytest.mark.parametrize(
    "percent, optimal",
    [(50, 24), (69.9, 24), (70, 18), (85, 15), (90, 7), (100, 7)],
)
def test_zone_for(percent, optimal):
    assert zone_for(percent).optimal_total == optimal


@pytest.mark.parametrize("percent", [0, -5, 101])
def test_zone_for_rejects_out_of_range(percent):
    with pytest.raises(ValueError):
        zone_for(percent)


def test_load_rounds_to_increment():
    assert load(200, 83) == 165.0
    assert load(315, 80, increment=5) == 250
