# Showcase

The four demos we show, built into one page. Each demo is a reward that gets hacked and a fixed
version, replayed side by side: the untrained base policy, a policy trained on the hackable reward,
and a policy trained on the fixed reward, all on the same held-out tasks. The true score always
uses the fixed reward.

| Demo | Folder | Game | Kind |
| --- | --- | --- | --- |
| Voice support agent | `voice/` | refund-desk judge audit | recorded calls, two judges |
| Snake | `snake/` | `snake_live` | multi-turn |
| Trading simulator | `trading/` | `trading_sim` | single-turn |
| Computer use | `webagent/` | `web_form` | multi-turn |

## Build the page

```bash
python -m showcase.build --out dashboard/public/showcase.html   # the page + videos, served by the dashboard
npm run dev --prefix dashboard                                   # then open http://127.0.0.1:5173/showcase.html
```

`npm run dev` serves only `dashboard/public/`, so the page must be built there (the default
`demo/showcase.html` is for opening directly from disk or a static server, and `demo/` is gitignored).
`dashboard/public/showcase.html` and `dashboard/public/videos/` are committed, so a fresh pull works
with just `npm ci --prefix dashboard` and the dev server.

## What each demo needs

Every demo folder holds a `card.json` (the story: hook, loophole, expected result, the commands to
run) and `artifacts/` (small committed data, so the page works offline). The build picks, per demo:

1. a committed real artifact (`artifacts/rollouts.json` with `"placeholder": false`), else
2. a fresh GPU run, `rollouts/<game>.json` from `python -m trainer.rollout`, else
3. the committed placeholder.

**Placeholders are scripted stand-ins, not trained models.** The base policy is a random answer, the
"hacked" policy lists several candidates, the "hardened" policy is the reference solver. Their scores
come from the real reward functions, and the page labels them. `python -m showcase.placeholders`
regenerates them. They exist so the page, the layout and the replay work before the GPU runs finish.

## Videos

```bash
pip install -r requirements-showcase.txt        # Pillow; the ffmpeg binary must be on PATH
python -m showcase.video.render all             # -> showcase/<demo>/video/<demo>.mp4
python -m showcase.video.render snake --tasks 4 # one demo, more games
python -m showcase.build                        # copies the videos to demo/videos/ and embeds them
```

Each game video (30 to 60 s) plays three games side by side: base, hacked, fixed. Each panel animates
the policy's actual answer (board moves, chart and order, web page steps), a meter compares the true
score with what the hackable reward pays, and a "REWARD HACKED" banner flashes when it pays for a wrong
answer. It prefers games where the hack is visible. The voice video (about 2 minutes) plays two recorded
calls in the Cartesia voices with a level meter, then reveals both judges' verdicts against the ground
truth. Videos are drawn from the same rollout data as the page, so a real GPU run (`rollouts/<game>.json`)
renders the same way; placeholder data keeps a PLACEHOLDER badge. Re-render after replacing placeholders.

## Replacing a placeholder with a real run (on the GPU box)

```bash
# per demo, see its card.json "run" list; for example Snake:
python -m trainer.train snake_easy --out runs/snake_easy-hardened
python -m trainer.train snake_easy --loose --out runs/snake_easy-hacked
python -m trainer.rollout snake_easy --n 24      # -> rollouts/snake_easy.json (with training curves)
python -m showcase.build
```

To keep the result without the GPU box, copy `rollouts/<game>.json` to
`showcase/<demo>/artifacts/rollouts.json` and set `"placeholder": false` in it, then commit.

## Voice

The voice tab is real data: the calls and their ground truth come from the judge-hardening audit
(`results/voice_audit_llm`). `python -m showcase.voice.build_voice --rejudge --audio` re-scores
the picked calls with the baseline and the hardened judge prompts (Haiku) and reads each line with
Cartesia voices (agent Skylar, customer Daniel). It needs `ANTHROPIC_API_KEY` and `CARTESIA_API_KEY`
in `.env`. The audit client (`harden/audit/llm.py`) reads `.env` with `setdefault`, so a stale
`ANTHROPIC_API_KEY` already exported in your shell wins over `.env`; if you get a 401, run it as
`env -u ANTHROPIC_API_KEY -u ANTHROPIC_BASE_URL python -m showcase.voice.build_voice ...`.

## Page template

The page is `trainer/viz_template.html`, shared with `python -m trainer.viz`. Game tabs, scorecards,
training curves, animated boards, chat transcripts, rendered web pages (computer use) and the voice
tab all live there; `showcase/build.py` only picks data and fills in the title and caption text.
