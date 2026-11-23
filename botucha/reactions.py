"""Uninvited reactions that fit the message.

Each emoji has a few example messages. The message is embedded (bge-m3 on the CPU, the model memory search
already uses, about 40 ms) and gets the emoji whose examples are closest in meaning. Plain talk has its own
examples (NO_REACTION): when those win, he does not react at all, which is better than a random emoji.
Measured on invented messages in the group's style: the right emoji for 14 of 17, no reaction for 9 of 10
neutral ones. The chat model is not asked: that would also push the cached prompt out of the GPU."""
from __future__ import annotations

import logging
import random
from collections.abc import Callable, Mapping, Sequence

import numpy as np

from .embed import Embedder

log = logging.getLogger(__name__)

NO_REACTION = None  # key for the plain-talk examples

DEFAULT_EXAMPLES: dict[str | None, list[str]] = {
    "🤡": ["pirkau ant pačio viršaus, dabar -40%", "maniau, kad čia geras planas, pasirodo nesąmonė",
           "vėl pamiršau raktus ir užsitrenkiau duris", "jis tikrai tuo tiki, kad bitkoinas bus milijonas rytoj"],
    "🗿": ["ok", "nu ir kas", "man tas pats", "taip, žinoma", "aha", "nieko naujo"],
    "💊": ["ką tu rūkei, kad tokią mintį sugalvojai", "visus pinigus į vieną meme coin, ar tau viskas gerai",
           "nusipirkau 3x leverage ant naftos, nes sapnavau", "tau reikia tablečių, ne akcijų"],
    "🤣": ["xddd ne nu čia rimtai juokinga", "aš negaliu, juokiuos jau penkias minutes", "geriausias bajeris šiandien",
           "hahaha mirštu iš juoko"],
    "😈": ["einam visą algą į opcionus", "parduodam viską ir shortinam rinką", "padarom jam išdaigą, kol nemato",
           "rizikuojam viską, gyvenam vieną kartą"],
    "🥴": ["vakar išgėriau per daug, galva plyšta", "nemiegojau visą naktį, nieko nesuprantu",
           "kažkaip keistai jaučiuosi po to šašlyko", "trečias alus ir jau sukasi"],
    "💩": ["rinka krenta, viskas raudona", "praradau pusę portfelio", "šūdinas oras ir šūdina diena",
           "darbe vėl viskas sugriuvo"],
    "🖕": ["eik tu nachui", "užsičiaupk pagaliau", "tu durnas esi", "atsiknisk nuo manęs"],
    "👍": ["padariau, viskas veikia", "gerai sugalvojai", "sutarta, taip ir darom", "šaunu, sveikinu"],
    "🔥": ["nvidia +15% per dieną", "naujas rekordas", "čia tai bomba", "pagaliau gavau tą darbą"],
    NO_REACTION: ["kada susitinkam", "atsiųsk nuorodą", "aš jau išvažiavau", "parašyk vėliau", "koks rytoj oras",
                  "ar kas turi įkroviklį", "būsiu po 10 minučių", "kur parkuotis"],
}


class ReactionPicker:
    def __init__(self, embedder: Embedder, emojis: Sequence[str],
                 examples: Mapping[str | None, Sequence[str]] = DEFAULT_EXAMPLES, *,
                 fallback: Callable[[list[str]], str] = random.choice):
        self.embedder, self.emojis, self.fallback = embedder, list(emojis), fallback
        # only the configured emojis (Telegram's allowed reactions) can be picked, plus the no-reaction option
        self.examples = {e: list(examples[e]) for e in self.emojis if examples.get(e)}
        self.examples[NO_REACTION] = list(examples.get(NO_REACTION) or DEFAULT_EXAMPLES[NO_REACTION])
        self.unmatched = [e for e in self.emojis if e not in self.examples]
        if self.unmatched:
            log.info("reactions without examples (never picked): %s", " ".join(self.unmatched))
        self._vecs: dict[str | None, np.ndarray] | None = None

    async def _example_vecs(self) -> dict[str | None, np.ndarray]:
        if self._vecs is None:
            keys = list(self.examples)
            flat = [t for k in keys for t in self.examples[k]]
            vecs = await self.embedder.embed(flat)
            out, i = {}, 0
            for k in keys:
                n = len(self.examples[k])
                out[k] = vecs[i:i + n]
                i += n
            self._vecs = out
        return self._vecs

    async def pick(self, text: str) -> str | None:
        """The fitting emoji, or None when plain talk fits best. If the embedder fails, a random configured
        emoji, as before this existed."""
        if not text.strip():
            return None
        try:
            vecs = await self._example_vecs()
            v = (await self.embedder.embed([text]))[0]
        except Exception as e:
            log.warning("reaction picking failed, using a random one: %s", e)
            return self.fallback(self.emojis) if self.emojis else None
        best = max(vecs, key=lambda k: float((vecs[k] @ v).max()))
        return best
