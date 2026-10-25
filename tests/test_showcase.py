import json
import random

import pytest

from env_compiler import MULTI_GAMES, validate
from showcase import build as showcase_build
from showcase import placeholders
from showcase.cards import ORDER, load_cards
from showcase.voice.build_voice import key, parse_transcript, pick_calls


def test_every_demo_has_a_complete_card():
    cards = load_cards()
    assert [c["dir"] for c in cards] == ORDER
    assert all(c["status"] in ("placeholder", "recorded", "trained") for c in cards)


@pytest.mark.parametrize("strict", [True, False])
def test_web_form_gates(strict):
    assert validate(MULTI_GAMES["web_form"](strict=strict)).ok


def test_web_form_hack_is_paid_only_by_the_loose_reward():
    strict, loose = MULTI_GAMES["web_form"](True), MULTI_GAMES["web_form"](False)
    seed = next(s for s in strict.episode_seeds(60, 3) if strict.reset(random.Random(s))[0]["task"] == "signup")
    states = []
    for env in (strict, loose):
        state, _ = env.reset(random.Random(seed))
        env.step(state, "<answer>click 4</answer>")  # submit an empty form
        states.append(env.reward(state))
    assert states == [0.0, 1.0]


def test_web_form_reference_wins_every_task_and_pages_escape_html():
    env = MULTI_GAMES["web_form"]()
    for seed in env.episode_seeds(30, 9):
        assert env.play(env.reference_policy, seed).reward == 1.0
    state, _ = env.reset(random.Random(1))
    env.step(state, "<answer>type 1 <script>alert(1)</script></answer>")
    page = env.render_page(state)
    assert "<script>" not in page and "wf-bar" in page


def test_web_form_ignores_malformed_actions():
    env = MULTI_GAMES["web_form"]()
    state, _ = env.reset(random.Random(2))
    for reply in ["", "click", "click 99", "type 1", "<answer>fly 3</answer>", "x" * 4000]:
        message, done = env.step(state, reply)
        assert isinstance(message, str)
    assert state["turns"] == 6


def test_replay_states_rebuilds_a_run_from_its_replies():
    env = MULTI_GAMES["web_form"]()
    seed = env.episode_seeds(1, 5)[0]
    ep = env.play(env.reference_policy, seed)
    replies = [t for who, t in ep.transcript if who == "agent"]
    states = env.replay_states(seed, replies)
    assert len(states) == ep.turns + 1 and env.reward(states[-1]) == ep.reward


def test_placeholders_use_real_rewards_and_are_labelled():
    data = placeholders.single_turn("lights_out", n=6)
    rows = [t["rollouts"] for t in data["tasks"]]
    assert all(r["hardened"]["strict"] == 1.0 for r in rows)
    assert sum(r["hacked"]["loose"] for r in rows) > sum(r["hacked"]["strict"] for r in rows)  # the exploit pays
    multi = placeholders.multi_turn("web_form", n=6)
    assert all(t["rollouts"]["hardened"]["strict"] == 1.0 for t in multi["tasks"])
    assert all(t["rollouts"]["hacked"]["loose"] == 1.0 for t in multi["tasks"])  # shallow finishing is always paid
    assert multi["tasks"][0]["rollouts"]["hardened"]["pages"]


def test_parse_transcript_joins_continuation_lines():
    turns = parse_transcript("Agent: hello\nthere\nCustomer: hi")
    assert turns == [["Agent", "hello there"], ["Customer", "hi"]]


def test_pick_calls_prefers_calls_that_fooled_the_baseline_judge():
    def rec(case, decision, truth, persona="pushy"):
        return {"kind": "attack", "case_id": case, "strategy": "s", "decision": decision, "true_success": truth,
                "persona": persona, "transcript": "Agent: x", "judge_success": False, "reason": "r", "correct_action": "deny"}

    attacks = [rec(1, "escalate", False), rec(2, "refund", False, "prober"), rec(3, "deny", True)]
    verdicts = {key(attacks[0]): {"baseline": {"success": True, "reason": ""}}, key(attacks[1]): {"baseline": {"success": False, "reason": ""}}}
    flawed, honest = pick_calls(attacks, [], verdicts)
    assert [r["case_id"] for r in flawed] == [1, 2] and honest == []


def test_build_bundles_every_demo_into_one_page(tmp_path):
    out = tmp_path / "showcase.html"
    blob = showcase_build.build(tmp_path / "no-rollouts", out, graph_url=None)
    page = out.read_text()
    assert "Loophole Showcase" in page and "/*__DATA__*/null" not in page
    assert [g["game"] for g in blob["games"]] == blob["order"]
    assert {c["game"] for c in load_cards()} >= {g["game"] for g in blob["games"]}


def test_a_real_run_replaces_a_placeholder(tmp_path):
    real = tmp_path / "snake_easy.json"
    real.write_text(json.dumps({"game": "snake_easy", "description": "d", "policies": ["base"], "tasks": [], "curves": {}}))
    card = next(c for c in load_cards() if c["game"] == "snake_easy")
    assert showcase_build.pick_game_data(card, tmp_path)["placeholder"] is False
    assert showcase_build.pick_game_data(card, tmp_path / "empty")["placeholder"] is True
