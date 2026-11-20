from datetime import datetime, timezone

from aiogram.types import Chat, Message, MessageEntity, User

from botucha.__main__ import load_env, to_incoming

ME = User(id=999, is_bot=True, first_name="Botucha", username="botucha_bot")
DEG = User(id=111, is_bot=False, first_name="Tadas", username="tadas")
CHAT = Chat(id=-1001234567890, type="supergroup")
T = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def msg(**kw):
    base = dict(message_id=5, date=T, chat=CHAT, from_user=DEG)
    return Message(**{**base, **kw})


def test_plain_text():
    inc = to_incoming(msg(text="nu jo"), ME, edited=False)
    assert (inc.chat_id, inc.user_id, inc.name, inc.text, inc.ts) == (CHAT.id, 111, "Tadas", "nu jo", T.timestamp())
    assert not inc.mentions_bot and not inc.reply_to_bot


def test_caption_used_when_no_text():
    inc = to_incoming(msg(caption="ziurek", photo=[]), ME, edited=False)
    assert inc.text == "ziurek"


def test_no_text_is_empty():
    assert to_incoming(msg(), ME, edited=False).text == ""


def test_mention_detected():
    m = msg(text="@botucha_bot ka manai", entities=[MessageEntity(type="mention", offset=0, length=12)])
    assert to_incoming(m, ME, edited=False).mentions_bot


def test_reply_to_bot_detected():
    parent = msg(message_id=4, from_user=ME, text="hodlinam")
    inc = to_incoming(msg(text="jo", reply_to_message=parent), ME, edited=False)
    assert inc.reply_to_bot and inc.reply_to == 4


def test_load_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# c\nBOTUCHA_TOKEN = abc\nOTHER='x'\n")
    assert load_env(p) == {"BOTUCHA_TOKEN": "abc", "OTHER": "x"}
