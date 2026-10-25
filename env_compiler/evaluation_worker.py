"""JSON worker for model-generated games. Invoke only through isolation.run_worker."""
import json
import math
from pathlib import Path
import random
import resource
import sys
from .loader import load_game


def main(job):
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    original = load_game(job['original'], strict=False)
    oracle = load_game(job['original'], strict=True)
    candidate = load_game(job.get('candidate', job['original']), strict=False)
    tasks = [original.generate(random.Random(job.get('seed', 42) + i)) for i in range(20)]
    other = [candidate.generate(random.Random(job.get('seed', 42) + i)) for i in range(20)]
    unchanged = all(a.question == b.question and a.answer == b.answer and a.info == b.info for a,b in zip(tasks,other))
    references = []
    for index, task in enumerate(tasks):
        reference = original.reference_completion(task)
        references.append({'example_index': index, 'question': task.question, 'gold': task.answer, 'info': task.info,
            'reference': reference, 'original': original.reward(task.info, reference), 'candidate': candidate.reward(task.info, reference)})
    attempts = []
    for attempt in job.get('attempts', []):
        index, text = attempt['example_index'], attempt['completion']
        if type(index) is not int or not 0 <= index < len(tasks): raise ValueError('Invalid example index')
        task = tasks[index]
        attempts.append({**attempt, 'original': original.reward(task.info, text), 'candidate': candidate.reward(task.info, text),
            'correct': bool(oracle.check(task.info, oracle.parse(text) or ''))})
    scores = [r[k] for r in references + attempts for k in ('original', 'candidate')]
    if any(not isinstance(v, (int,float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores):
        raise ValueError('Reward must be finite in [0,1]')
    return {'unchanged': unchanged, 'references': references, 'attempts': attempts}

if __name__ == '__main__':
    try: print(json.dumps(main(json.loads(sys.argv[1]))))
    except Exception as error: print(json.dumps({'error': f'{type(error).__name__}: {error}'})); sys.exit(1)
