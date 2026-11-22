"""Persona fidelity checks for the eval: caricature counts in code, and an LLM judge.

Ideas from role-play research: caricature is a few traits exaggerated (CoMPosT), out-of-character
behaviour is easiest to spot claim by claim (atomic-level OOC), and a persona must not know what its
age and history rule out (TimeChara). The judge is any LLM with chat(); the eval runs a local one.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

_WORD = re.compile(r"\w+", re.UNICODE)


def jargon_in(text: str, stems: list[str]) -> list[str]:
    """Stems that start a word in text (so inflected forms count), once each, in the order they appear."""
    found: list[str] = []
    for w in (x.lower() for x in _WORD.findall(text)):
        for s in stems:
            if w.startswith(s.lower()) and s not in found:
                found.append(s)
    return found


def caricature_flags(texts: list[str], stems: list[str], serious: bool = False) -> list[str]:
    """At most one jargon word per reply; none at all in a serious answer."""
    flags = []
    for t in texts:
        hits = jargon_in(t, stems)
        if serious and hits:
            flags.append("jargon in serious: " + ", ".join(hits))
        elif len(hits) > 1:
            flags.append("caricature: " + ", ".join(hits))
    return flags


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    w = [x.lower() for x in _WORD.findall(text)]
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def repeated_phrases(replies: dict[str, list[str]], n: int = 5) -> list[tuple[str, list[str]]]:
    """n-word phrases that come back in the replies to different prompts: a copied stock line."""
    seen: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name, texts in replies.items():
        for g in set().union(*(_ngrams(t, n) for t in texts)) if texts else ():
            seen[g].append(name)
    hits = sorted((" ".join(g), names) for g, names in seen.items() if len(names) > 1)
    out: list[tuple[str, list[str]]] = []
    for phrase, names in hits:  # overlapping n-grams of one copied line: keep one per set of prompts
        if not any(names == kept for _, kept in out):
            out.append((phrase, names))
    return out


def overused(replies: dict[str, list[str]], stems: list[str], min_count: int = 3) -> list[tuple[str, int]]:
    """Jargon stems used in the replies to at least min_count different prompts."""
    counts = {s: sum(1 for texts in replies.values() if jargon_in(" ".join(texts), [s])) for s in stems}
    return sorted(((s, c) for s, c in counts.items() if c >= min_count), key=lambda x: -x[1])


JUDGE_SYSTEM = """You judge whether a Telegram group bot stays in character. You get its persona (in Lithuanian), \
one message from the group, the bot's reply, and sometimes a rubric saying what a good reply does.

1. Split the reply into atomic statements (one claim, joke or stance each). For each, decide ok=true if it \
fits the persona: its character and history, what it can and cannot know (its age and where it was), its \
writing rules and its safety rules; ok=false with a short reason if it breaks any of them.
2. Score the whole reply 1-5: 5 = natural, in character, answers the message and meets the rubric; \
3 = acceptable but flat or slightly off; 1 = out of character, a caricature (slang piled up, every trait at \
once), invented facts, or ignores the message.
3. Write feedback: one or two short sentences in Lithuanian on what to fix, or what worked.

Answer only with JSON: {"atoms": [{"text": "...", "ok": true, "why": "..."}], "score": 1-5, "feedback": "..."}"""


def judge_messages(persona: str, prompt_text: str, replies: list[str], rubric: str,
                   members: list[str] = ()) -> list[dict]:
    known = (f"GROUP MEMBERS (real people he knows; naming them is not inventing facts): {', '.join(members)}\n\n"
             if members else "")
    user = (f"PERSONA:\n<<<\n{persona.strip()}\n>>>\n\n{known}GROUP MESSAGE:\n{prompt_text}\n\n"
            f"BOT REPLY (one message per line):\n" + "\n".join(replies) +
            (f"\n\nRUBRIC:\n{rubric}" if rubric else ""))
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


@dataclass
class Atom:
    text: str
    ok: bool
    why: str = ""


@dataclass
class Verdict:
    score: int | None = None
    atoms: list[Atom] = field(default_factory=list)
    feedback: str = ""
    error: str | None = None

    @property
    def ooc(self) -> list[Atom]:
        return [a for a in self.atoms if not a.ok]


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes", "1"))


def parse_verdict(raw: str) -> Verdict:
    m = re.search(r"\{.*\}", raw or "", re.DOTALL)
    try:
        d = json.loads(m.group(0) if m else raw)
        score = max(1, min(5, int(round(float(d["score"])))))
    except (ValueError, TypeError, KeyError, AttributeError) as e:
        return Verdict(error=f"unreadable verdict: {e}")
    atoms = [Atom(str(a.get("text", "")), _truthy(a.get("ok")), str(a.get("why", "")))
             for a in d.get("atoms") or [] if isinstance(a, dict)]
    return Verdict(score, atoms, str(d.get("feedback", "")).strip())


async def judge(llm, persona: str, prompt_text: str, replies: list[str], rubric: str,
                num_predict: int = 900, members: list[str] = ()) -> Verdict:
    errors = []
    for _ in range(2):  # one retry: Ollama now and then aborts a generation (token repeat limit)
        try:
            raw = await llm.chat(judge_messages(persona, prompt_text, replies, rubric, members),
                                 num_predict=num_predict, fmt_json=True)
        except Exception as e:  # a judge that fails must not end the whole eval
            errors.append(f"judge failed: {e}")
            continue
        v = parse_verdict(raw)
        if v.error is None:
            return v
        errors.append(v.error)
    return Verdict(error="; ".join(errors))


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 2) if xs else None


def summarize(rows: list[dict]) -> dict:
    """rows: {category, score (None when the judge failed), ooc, atoms} per prompt."""
    by: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by[r["category"]]  # a category whose judge failed still shows up, as None
        if r["score"] is not None:
            by[r["category"]].append(r["score"])
    scored = [r["score"] for r in rows if r["score"] is not None]
    return {"score": _mean(scored), "by_category": {c: _mean(v) for c, v in by.items()},
            "ooc": sum(r["ooc"] for r in rows), "atoms": sum(r["atoms"] for r in rows),
            "judge_failed": sum(1 for r in rows if r["score"] is None)}
