import pytest
from gameplay import flow_field as mod

CASES = [
    ("cell", 'm.grid_cell(5.5, 1) == 5'),
    ("layer", 'm.cost_layer("bridge") == 1'),
    ("neighbor", 'm.neighbor_count(True) == 8'),
    ("rebuild", 'm.rebuild_needed(True, False) is True'),
    ("buffer", 'm.double_buffer(1, 2) == 2'),
    ("narrow", 'm.narrow_avoid(3, 0.5) == approx(2.5)'),
    ("multi", 'm.multigrid((1, 2), 3) == (1, 2, 3)'),
    ("unreachable", 'm.unreachable(999, 100) is True'),
    ("portal", 'm.portal_link(1, 2) is True'),
    ("switch", 'm.target_switch(1, 2, ["a"]) == []'),
    ("origin", 'm.origin_rebase((10.0, 10.0), (2.0, 3.0)) == approx((8.0, 7.0))'),
    ("sync", 'm.event_sync(5, 5) is True'),
    ("dir", 'm.flow_dir(-3, 2) == (-1, 1)'),
    ("bridge", 'm.bridge_cost(False) == 999'),
    ("crowd", 'm.crowd_limit(10, 8) == 8')
]

@pytest.mark.parametrize("name,expr", CASES, ids=[c[0] for c in CASES])
def test_contract(name, expr):
    assert eval(expr, {"m": mod, "approx": pytest.approx})
