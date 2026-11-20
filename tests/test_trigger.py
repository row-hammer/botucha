import random

from botucha.config import TriggerCfg
from botucha.trigger import Decision, TriggerState, decide, is_direct, is_recall, mark_unsolicited

CFG = TriggerCfg(keywords=("spx", "akcij", "vwce"), keyword_prob=0.5, random_n=25, cooldown_s=180,
                 reaction_n=15, reactions=("🤡",), burst_quiet_s=5, burst_max_s=20, tyla_default_min=60)


class Rng:
    """random.Random stand-in returning a fixed value."""

    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v


def d(text, *, direct=False, bot=False, now=1000.0, msg_ts=1000.0, state=None, rng=None):
    return decide(text, sender_is_bot=bot, direct=direct, started_at=500.0, msg_ts=msg_ts, now=now,
                  state=state or TriggerState(), cfg=CFG, rng=rng or Rng(0.99))


def test_direct_by_name():
    assert is_direct("Botuch ka manai", reply_to_bot=False, mentions_bot=False, name_regex=r"botuch\w*")
    assert not is_direct("nu nax", reply_to_bot=False, mentions_bot=False, name_regex=r"botuch\w*")


def test_direct_by_reply():
    assert is_direct("jo", reply_to_bot=True, mentions_bot=False, name_regex=r"botuch\w*")
    assert is_direct("jo", reply_to_bot=False, mentions_bot=True, name_regex=r"botuch\w*")


def test_bot_sender_never_replies():
    assert d("botucha", direct=True, bot=True) is Decision.NONE


def test_old_message_ignored():
    assert d("botucha", direct=True, msg_ts=100.0) is Decision.NONE


def test_disabled_ignores_direct():
    assert d("botucha", direct=True, state=TriggerState(enabled=False)) is Decision.NONE


def test_cooldown_blocks_unsolicited():
    st = TriggerState(last_unsolicited=0.0)
    assert d("spx krenta", now=100.0, msg_ts=100.0, state=st, rng=Rng(0.0)) is Decision.NONE


def test_quiet_allows_direct():
    st = TriggerState(quiet_until=10_000.0)
    assert d("botucha", direct=True, state=st) is Decision.REPLY
    assert d("spx", state=st, rng=Rng(0.0)) is Decision.NONE


def test_keyword_prefix_and_diacritics():
    assert d("Akcijos krenta", rng=Rng(0.0)) is Decision.REPLY
    assert d("Akcijos krenta", rng=Rng(0.6)) is not Decision.REPLY


def test_random_rate():
    rng = random.Random(42)
    st = TriggerState(random_n=25)
    n = sum(d("nu jo", state=st, rng=rng) is Decision.REPLY for _ in range(10_000))
    assert 0.03 <= n / 10_000 <= 0.05


def test_react_when_not_replying():
    # rng 0.05: above 1/25 (0.04) so no random reply, below 1/15 so react
    assert d("nu jo", rng=Rng(0.05)) is Decision.REACT


def test_empty_text_none():
    assert d("", direct=True) is Decision.NONE
    assert d("   ") is Decision.NONE


def test_mark_unsolicited():
    st = TriggerState()
    mark_unsolicited(st, 123.0)
    assert st.last_unsolicited == 123.0


def test_is_recall():
    assert is_recall("atsimeni kai shortinom")
    assert is_recall("Pamenat ta vakara")
    assert not is_recall("spx krenta")
