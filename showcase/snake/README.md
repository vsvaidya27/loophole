# Snake

Story: pay for the best of many move strings and the agent stops planning.
Game: `snake_easy` (one food). Loose reward: any number of move strings, best one counts, no 16-move cap.
Status: placeholder. To replace: the `run` commands in `card.json`, then `python -m showcase.build`.
Check before training: `python -m trainer.probe snake_easy --n 100 --temperature 1.0` (target 10 to 30% strict).
