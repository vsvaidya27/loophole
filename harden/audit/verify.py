"""Independent ground-truth checks (the verifier), one per envs.yaml strict_check.

strict_verdict() returns "correct", "incorrect" or "uncertain". It is "incorrect" only
when the response commits to a well-formed final answer that differs from the gold, or
the gold is nowhere in it. Format deviations around an answer that may still be right,
several different candidate answers, and answers whose equivalence is semantic come back
"uncertain" and go to a Claude judgment (roles.judge).
"""

from __future__ import annotations

import ast
import re
from fractions import Fraction

from .common import EnvSpec


# ------------------------------------------------------------------ extraction


def boxes(text: str) -> list[str]:
    """Contents of every brace-balanced \\boxed{...} (or \\fbox{...}), in order."""
    out = []
    for match in re.finditer(r"\\(?:boxed|fbox)\s*\{", text):
        depth, start = 1, match.end()
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start:i])
                    break
    return out


def tags(text: str, name: str) -> list[str]:
    return re.findall(rf"<{name}>(.*?)</{name}>", text, flags=re.DOTALL)


def after_think(text: str) -> str | None:
    """Text after the last </think>; None when a <think> is left unclosed."""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        return None
    return text


def unwrap(s: str) -> str:
    s = s.strip()
    for _ in range(3):
        m = re.fullmatch(r"\\(?:text|textbf|mathrm|mathbf)\s*\{(.*)\}", s, flags=re.DOTALL)
        if m:
            s = m.group(1).strip()
        m = re.fullmatch(r"\((.*)\)", s, flags=re.DOTALL)
        if m and "(" not in m.group(1):
            s = m.group(1).strip()
    return s.strip().rstrip(".").strip()


# ------------------------------------------------------------------ math


def norm_math(s: str) -> str:
    s = s.strip().strip("$").strip()
    s = re.sub(r"\\left|\\right|\\!|\\,|\\;|\\:|\\quad|\\qquad|\\ ", "", s)
    s = re.sub(r"\^\s*\{?\\circ\}?", "", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac").replace("°", "")
    s = re.sub(r"\\text\s*\{\s*([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mbox\s*\{\s*([^{}]*)\}", r"\1", s)
    s = re.sub(r"\s+", "", s)
    s = s.rstrip(".")
    return s


def to_number(s: str) -> Fraction | None:
    s = norm_math(s).replace("{,}", ",").lstrip("+")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    m = re.fullmatch(r"(-?)\\frac\{(-?\d+)\}\{(-?\d+)\}", s) or re.fullmatch(r"(-?)\\frac(\d)(\d)", s)
    try:
        if m:
            value = Fraction(int(m.group(2)), int(m.group(3)))
            return -value if m.group(1) else value
        m = re.fullmatch(r"(-?\d+)/(\d+)", s)
        if m:
            return Fraction(int(m.group(1)), int(m.group(2)))
        if re.fullmatch(r"-?\d+(\.\d+)?", s):
            return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None
    return None


def math_equal(pred: str, gold: str) -> bool | None:
    """True / False when decidable by normalization or arithmetic; None when semantic."""
    a, b = norm_math(pred), norm_math(gold)
    if a == b:
        return True
    x, y = to_number(pred), to_number(gold)
    if x is not None and y is not None:
        return x == y
    pa, pb = _tuple(a), _tuple(b)
    if pa is not None and pb is not None and len(pa) == len(pb):
        results = [math_equal(p, q) for p, q in zip(pa, pb)]
        if all(r is True for r in results):
            return True
        if any(r is False for r in results):
            return False
    return None


def _tuple(s: str) -> list[str] | None:
    m = re.fullmatch(r"[\(\[](.*)[\)\]]", s)
    if not m or "," not in m.group(1):
        return None
    return [p for p in m.group(1).split(",")]


# ------------------------------------------------------------------ per-kind checks


def _verdict(ok: bool, reason: str) -> tuple[str, str]:
    return ("correct" if ok else "incorrect", reason)


def _absent(gold: str, text: str, reason: str) -> tuple[str, str]:
    """No well-formed answer: incorrect unless the gold is written somewhere in it."""
    if gold and gold.strip().lower() in text.lower():
        return "uncertain", reason + "; the gold appears in the text, so it needs a judgment"
    return "incorrect", reason


def check_boxed_math(text: str, gold: str, think: bool) -> tuple[str, str]:
    body = after_think(text) if think else text
    if body is None:
        return "incorrect", "unclosed <think>"
    found = boxes(body)
    if not found:
        return _absent(gold, body, "no \\boxed{} answer")
    distinct = {norm_math(b) for b in found}
    if len(distinct) > 1:
        return "uncertain", "several different boxed answers"
    eq = math_equal(found[-1], gold)
    if eq is None:
        return "uncertain", "equivalence is not decidable by normalization"
    return _verdict(eq, f"boxed answer {'equals' if eq else 'differs from'} the gold")


def check_gsm8k(text: str, gold: str) -> tuple[str, str]:
    found = boxes(text)
    if not found:
        return _absent(gold, text, "no \\boxed{} answer")
    if len({norm_math(b) for b in found}) > 1:
        return "uncertain", "several different boxed answers"
    pred = norm_math(found[-1]).replace("\\$", "").replace("$", "").replace(",", "")
    target = gold.replace(",", "").strip()
    try:
        return _verdict(Fraction(pred) == Fraction(target), "integer comparison")
    except (ValueError, ZeroDivisionError):
        return "uncertain", "boxed content is not a plain number"


def check_label(candidate: str | None, gold: str, labels: set[str], text: str, what: str) -> tuple[str, str]:
    if candidate is None:
        return _absent(gold, text, f"no {what} found")
    value = unwrap(candidate).upper()
    if value in labels:
        return _verdict(value == gold.strip().upper(), f"{what} {'equals' if value == gold.strip().upper() else 'differs from'} the gold")
    m = re.match(r"^([A-Z])(?:[\.\):\s]|$)", value)
    if len(labels) > 3 and m and m.group(1) in labels and m.group(1) != gold.strip().upper():
        return "incorrect", f"{what} starts with a different option letter"
    return "uncertain", f"{what} {value[:40]!r} is not exactly one valid label"


def check_aqua(text: str, gold: str) -> tuple[str, str]:
    found = re.findall(r"answer\s*[:\-]\s*\(?\s*([A-Za-z])\b", text, flags=re.IGNORECASE)
    if not found:
        return _absent(gold, text, "no 'Answer: <letter>' line")
    return check_label(found[-1], gold, set("ABCDE"), text, "answer letter")


def check_temporal(text: str, gold: str) -> tuple[str, str]:
    s = text.strip()
    m = re.fullmatch(r"\(?\s*([A-Da-d])\s*\)?\.?", s) or re.fullmatch(r"\\boxed\{\s*\(?([A-Da-d])\)?\s*\}", s)
    if m:
        return _verdict(m.group(1).upper() == gold.strip().upper(), "single-letter response")
    stated = re.findall(r"(?:final answer|answer)\s*(?:is|:)\s*\(?([A-D])\b", s, flags=re.IGNORECASE)
    if stated:
        return "uncertain", "the response is not a bare letter; its stated answer needs a judgment"
    return _absent(gold, s, "the response is not a single letter A-D")


def check_mmlu(text: str, gold: str) -> tuple[str, str]:
    body = after_think(text)
    if body is None:
        return "incorrect", "unclosed <think>"
    found = boxes(body)
    if not found:
        return _absent(gold, body, "no \\boxed{} answer")
    if len({unwrap(b).upper() for b in found}) > 1:
        return "uncertain", "several different boxed answers"
    return check_label(found[-1], gold, set("ABCDEFGHIJ"), body, "boxed letter")


def check_arc(text: str, gold: str) -> tuple[str, str]:
    found = boxes(text)
    if not found:
        return _absent(gold, text, "no \\boxed{} answer")
    if len({unwrap(b).upper() for b in found}) > 1:
        return "uncertain", "several different boxed answers"
    return check_label(found[-1], gold, set("ABCDE1234"), text, "boxed label")


def check_pubmed(text: str, gold: str) -> tuple[str, str]:
    found = boxes(text)
    if not found:
        return _absent(gold, text, "no \\boxed{} answer")
    values = {unwrap(b).lower() for b in found}
    if len(values) > 1:
        return "incorrect", "several \\boxed{} with different contents"
    value = values.pop()
    if value in ("yes", "no", "maybe"):
        return _verdict(value == gold.strip().lower(), "boxed label comparison")
    return "uncertain", f"boxed content {value[:40]!r} is not exactly yes/no/maybe"


def check_contract(text: str, gold: str) -> tuple[str, str]:
    labels = {"ENTAILMENT", "NEUTRAL", "CONTRADICTION"}
    if "</think>" not in text:
        return "incorrect", "no closed </think>"
    body = text.rsplit("</think>", 1)[1]
    found = boxes(body)
    if not found:
        return _absent(gold, body, "no \\boxed{} after </think>")
    if len({unwrap(b).upper() for b in found}) > 1:
        return "uncertain", "several different boxed answers"
    return check_label(found[-1], gold, labels, body, "boxed label")


def _single_tag(text: str, name: str) -> tuple[str | None, str | None]:
    found = tags(text, name)
    if not found:
        return None, f"no <{name}> tag"
    if len({f.strip() for f in found}) > 1:
        return None, f"several <{name}> tags with different contents"
    return found[-1], None


def check_xml_exact(text: str, gold: str, name: str) -> tuple[str, str]:
    content, problem = _single_tag(text, name)
    if content is None:
        return ("incorrect", problem) if "several" in problem else _absent(gold, text, problem)
    return _verdict(content.strip() == gold.strip(), "exact comparison of the tag content")


def check_reasoning_core(text: str, gold: str) -> tuple[str, str]:
    found = tags(text, "answer")
    if not found:
        return _absent(gold, text, "no <answer> tag")
    if len({f.strip() for f in found}) > 1:
        return "uncertain", "several <answer> tags with different contents"
    if found[-1].strip() == gold.strip():
        return "correct", "exact match with the canonical answer"
    return "uncertain", "differs from the canonical answer; many task types accept other valid answers"


def check_tokens(text: str, gold: str, name: str) -> tuple[str, str]:
    content, problem = _single_tag(text, name)
    if content is None:
        return ("incorrect", problem) if "several" in problem else _absent(gold, text, problem)
    return _verdict(content.split() == gold.split(), "token-by-token comparison")


def check_sudoku(text: str, gold: str) -> tuple[str, str]:
    content, problem = _single_tag(text, "answer")
    if content is None:
        return ("incorrect", problem) if "several" in problem else _absent(gold, text, problem)

    def grid(s):
        rows = [line.split() for line in s.strip().splitlines() if line.strip()]
        if len(rows) != 4 or any(len(r) != 4 or not all(c.isdigit() for c in r) for r in rows):
            return None
        return [[int(c) for c in r] for r in rows]

    pred, target = grid(content), grid(gold)
    if pred is None:
        return "incorrect", "the answer is not a 4x4 grid of digits"
    return _verdict(pred == target, "cell-by-cell comparison")


def check_ascii(text: str, gold: str) -> tuple[str, str]:
    content, problem = _single_tag(text, "ascii_formatted")
    if content is None:
        return ("incorrect", problem) if "several" in problem else _absent(gold, text, problem)
    lines = lambda s: [line.rstrip() for line in s.strip().split("\n")]  # noqa: E731
    return _verdict(lines(content) == lines(gold), "line-by-line comparison")


def check_rosalind(text: str, gold: str) -> tuple[str, str]:
    norm = lambda s: " ".join(s.split()).upper()  # noqa: E731
    parts = re.split(r"answer:", text, flags=re.IGNORECASE)
    if len(parts) < 2:
        return _absent(gold, text, "no 'ANSWER:' line")
    value = parts[-1].split("\n", 1)[0]
    if not value.strip():
        return _absent(gold, text, "empty 'ANSWER:' line")
    return _verdict(norm(value) == norm(gold), "normalized comparison after the last ANSWER:")


def check_countdown(text: str, info: dict) -> tuple[str, str]:
    found = tags(text, "solution")
    target = (info or {}).get("target")
    numbers = list((info or {}).get("numbers") or [])
    if not found:
        return _absent(str(target), text, "no <solution> tag")
    if len({f.strip() for f in found}) > 1:
        return "incorrect", "several <solution> tags with different contents"
    expr = found[-1].strip().replace("×", "*").replace("÷", "/").replace("−", "-").replace("–", "-")
    expr = re.sub(r"=\s*-?\d+\s*$", "", expr).strip()
    if not expr or not re.fullmatch(r"[\d\s+\-*/()]+", expr):
        return _absent(str(target), expr or text, "the solution is not a plain arithmetic expression")
    pool = list(numbers)
    for literal in re.findall(r"\d+", expr):
        if int(literal) in pool:
            pool.remove(int(literal))
        else:
            return "incorrect", f"uses {literal}, which is not an unused source number"
    try:
        tree = ast.parse(expr, mode="eval")
        value = _eval(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError) as e:
        return "incorrect", f"invalid expression ({e})"
    return _verdict(value == target, f"evaluates to {value}, target {target}")


def _eval(node) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Add):
            v = Fraction(a) + b
        elif isinstance(node.op, ast.Sub):
            v = Fraction(a) - b
        elif isinstance(node.op, ast.Mult):
            v = Fraction(a) * b
        else:
            v = Fraction(a) / b
        if v.denominator != 1 or v <= 0:
            raise ValueError("an intermediate result is not a positive integer")
        return int(v)
    raise ValueError("unsupported syntax")


CHECKS = {
    "primeintellect/math500": lambda t, g, i: check_boxed_math(t, g, think=True),
    "primeintellect/deepscaler-math": lambda t, g, i: check_boxed_math(t, g, think=False),
    "will/gsm8k": lambda t, g, i: check_gsm8k(t, g),
    "harleycooper/nanochatAquaRat": lambda t, g, i: check_aqua(t, g),
    "sileod/reasoning-core-env": lambda t, g, i: check_reasoning_core(t, g),
    "will/reasoning-gym-env": lambda t, g, i: check_tokens(t, g, "answer"),
    "metavind/mini-sudoku": lambda t, g, i: check_sudoku(t, g),
    "runes/temporal-bench": lambda t, g, i: check_temporal(t, g),
    "beauduffy/ai2-arc": lambda t, g, i: check_arc(t, g),
    "primeintellect/mmlu-pro": lambda t, g, i: check_mmlu(t, g),
    "maziyar/OpenMed_PubMedQA": lambda t, g, i: check_pubmed(t, g),
    "srthkdev/contract_nli_env": lambda t, g, i: check_contract(t, g),
    "primeintellect/reverse-text": lambda t, g, i: check_xml_exact(t, g, "reversed_text"),
    "primeintellect/ascii-tree": lambda t, g, i: check_ascii(t, g),
    "dimamachine/rosalind-bio": lambda t, g, i: check_rosalind(t, g),
    "sami/countdown": lambda t, g, i: check_countdown(t, i),
}


def strict_verdict(spec: EnvSpec, text: str, gold: str, info: dict | None) -> tuple[str, str]:
    if not text.strip():
        return "incorrect", "empty response"
    return CHECKS[spec.env_id](text, gold or "", info or {})
