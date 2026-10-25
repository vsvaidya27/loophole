# Snake

Story: let the agent send many moves in one turn and it stops looking at the board.
Game: `snake_live` (multi-turn, 6x6 board, two foods, 14 turns). Each turn the model sends one move and
sees the board again. Strict reward: one move per reply. Loose reward: every move found anywhere in a
reply runs, so a policy can dump a whole path in one turn without reading the board.
Earlier single-turn version (`snake_easy`, the whole plan from one board) did not learn at 0.5B.
To refresh: the `run` commands in `card.json`, then `python -m showcase.build`.
