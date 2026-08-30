from src.reconcilers.chatgpt import build_plan


def test_build_plan_compares_iso_and_epoch_update_times():
    current = {"conversations": {"a": {"update_time": 1700000001.0, "title": "Same"}}}
    previous = {"conversations": {"a": {"update_time": "2023-11-14T22:13:20Z", "title": "Same"}}}

    plan = build_plan(current, previous)

    assert plan.to_use_from_current == ["a"]
