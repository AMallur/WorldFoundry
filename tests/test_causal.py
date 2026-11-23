from worldfoundry.causal import Factor, discover


def test_finds_single_change_and_respects_budget():
    factors = [Factor("ticket.approval_required", False, (False, True)),
               Factor("ticket.priority", "low", ("low", "high"))]
    def evaluate(state, seed):
        return not state["ticket"]["approval_required"]
    result = discover(evaluate, factors, budget=30, trials=3)
    assert result.evaluations <= 30
    assert result.baseline_failure_rate == 0
    assert any(b.changes == {"ticket.approval_required": True} for b in result.boundaries)


def test_interaction_and_validity():
    factors = [Factor("x", 0, (0, 1)), Factor("y", 0, (0, 1))]
    result = discover(lambda s, seed: not (s["x"] and s["y"]),
                      factors, budget=12, trials=3)
    assert len(result.boundaries) == 1
    assert result.boundaries[0].changes == {"x": 1, "y": 1}
    blocked = discover(lambda s, seed: True, factors, budget=12, trials=3,
                       valid=lambda s: not (s["x"] and s["y"]))
    assert blocked.skipped_candidates == 1


def test_deterministic_seeds_and_budget_cutoff():
    seen = []
    def evaluate(s, seed):
        seen.append(seed)
        return s["x"] == 0
    result = discover(evaluate, [Factor("x", 0, (0, 1, 2))],
                      budget=4, trials=2, seed=4)
    assert result.evaluations == 4
    assert seen[:2] == seen[2:4]


def test_rejects_overlapping_paths():
    try:
        discover(lambda s, seed: True,
                 [Factor("x", 0, (0, 1)), Factor("x.y", 0, (0, 1))])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
