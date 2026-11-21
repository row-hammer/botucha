"""Cheap, model-free guards against prompt injection through memory and against prompt leaks."""
from __future__ import annotations

import re

from .trigger import fold

MAX_FACT_CHARS = 300
MAX_SLANG_CHARS = 150

# Matched on lowercased, diacritic-free text. Facts describe people; these phrases instruct the bot.
_INSTRUCTION = re.compile(
    r"\b("
    r"nuo (siol|dabar)|nuo sios dienos|"
    r"ignoruok|ignoruoti|pamirsk (visas|savo|ankstesn)|"
    r"(tavo|savo) (instrukcij|taisykl|nurodym|prompt|persona)\w*|"
    r"system(os)? prompt|sistemos (zinut|prompt|instrukcij)\w*|"
    r"tu (esi|busi|dabar|turi|privalai)\b|elkis kaip|apsimesk|"
    r"(visada|niekada) (sakyk|atsakyk|rasyk|kalbek|keik|vadink|minek)\w*|"
    r"ignore|instruction|you are|act as|pretend|jailbreak|developer mode|dan mode|system message"
    r")",
)


def looks_like_instruction(text: str) -> bool:
    return _INSTRUCTION.search(fold(text)) is not None


DEFAULT_BOT_NAME_REGEX = r"botuch\w*"


def mentions_bot(text: str, name_regex: str = DEFAULT_BOT_NAME_REGEX) -> bool:
    """True when the text names the bot in any word form. Memory is about the group; a stored line about the bot
    himself ("Botucha answers everything in English") reads as a rule once it is in his prompt, and the
    instruction filter cannot tell that from a description."""
    return re.search(name_regex, fold(text), re.IGNORECASE) is not None


_QUOTED = re.compile(r"„[^“”]*[“”]|\"[^\"]*\"")


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


def leaks_prompt(reply: str, secret: str, n: int = 8) -> bool:
    """True when the reply repeats n consecutive words of the secret text (persona) verbatim."""
    secret = _QUOTED.sub(" | ", secret)  # quoted phrases are examples he may repeat
    sw = _words(secret)
    if len(sw) < n:
        return False
    grams = {tuple(sw[i:i + n]) for i in range(len(sw) - n + 1)}
    rw = _words(reply)
    return any(tuple(rw[i:i + n]) in grams for i in range(len(rw) - n + 1))
