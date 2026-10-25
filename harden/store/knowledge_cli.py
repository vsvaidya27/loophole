"""Inspect Moss retrieval without LLM calls or database writes: python -m harden.store.knowledge_cli --help."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path

from .retrieval import KnowledgeSnapshot, SQLiteKnowledgeSource
from .moss_retrieval import MossRetriever, load_hosted_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-id', required=True)
    parser.add_argument('--reward-source', type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('-k', type=int, default=5)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--snapshot', type=Path)
    source.add_argument('--sqlite', type=Path)
    args = parser.parse_args()
    if args.snapshot:
        knowledge = KnowledgeSnapshot.from_dict(json.loads(args.snapshot.read_text()))
    elif args.sqlite:
        knowledge = SQLiteKnowledgeSource(args.sqlite).load()
    else:
        knowledge = load_hosted_snapshot()
    retriever = MossRetriever(knowledge)
    matches = retriever.retrieve(args.reward_source.read_text(), args.task, args.k,
                                                target_env_id=args.target_id)
    print(json.dumps({'source': knowledge.source, 'diagnostics': knowledge.diagnostics,
                      'retrieval': retriever.receipt, 'matches': [asdict(match) for match in matches]}, indent=2))


if __name__ == '__main__':
    main()
