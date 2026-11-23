"""GIFs: he sees one still frame (Telegram's preview of the animation), and knows it is only one frame."""
from datetime import datetime, timezone

from aiogram.types import Animation, Chat, Message, PhotoSize, User

from botucha.__main__ import to_incoming
from botucha.images import (DESCRIBE_PROMPT, GIF_DESCRIBE_PROMPT, GIF_GUARD, IMAGE_GUARD, caption_of, described_text,
                            description_of, image_text, retag)
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)
from tests.test_images import vbot

ME = User(id=999, is_bot=True, first_name="Botucha", username="botucha_bot")
TADAS = User(id=111, is_bot=False, first_name="Tadas", username="tadas")
T = datetime(2026, 11, 20, 20, 0, tzinfo=timezone.utc)


def animation(thumbnail=True):
    thumb = PhotoSize(file_id="THUMB", file_unique_id="t", width=320, height=180) if thumbnail else None
    return Animation(file_id="ANIM", file_unique_id="a", width=480, height=270, duration=3, thumbnail=thumb)


def message(**kw):
    return Message(**{"message_id": 5, "date": T, "chat": Chat(id=C, type="supergroup"), "from_user": TADAS, **kw})


# ---- the Telegram adapter -------------------------------------------------------------------------------
def test_a_gif_arrives_as_its_preview_frame():
    m = to_incoming(message(animation=animation(), caption="xd"), ME, edited=False)
    assert (m.image_file_id, m.gif, m.text) == ("THUMB", True, "xd")


def test_a_gif_without_a_preview_frame_is_still_known_as_a_gif():
    m = to_incoming(message(animation=animation(thumbnail=False)), ME, edited=False)
    assert (m.image_file_id, m.gif, m.text) == (None, True, "")


def test_a_photo_is_not_a_gif():
    m = to_incoming(message(photo=[PhotoSize(file_id="P", file_unique_id="p", width=800, height=600)]), ME, edited=False)
    assert (m.image_file_id, m.gif) == ("P", False)


# ---- how it is stored as text -----------------------------------------------------------------------------
def test_gif_tags():
    assert image_text("", gif=True) == "[gif]" and image_text("xd", gif=True) == "[gif] xd"
    assert caption_of("[gif] xd") == "xd" and caption_of("[gif: šokantis katinas] xd") == "xd"
    assert description_of("[gif: šokantis katinas] xd") == "šokantis katinas" and description_of("[gif] xd") is None
    assert described_text("šokantis katinas", "xd", gif=True) == "[gif: šokantis katinas] xd"
    assert retag("[gif: šokantis katinas] xd", "xdd") == "[gif: šokantis katinas] xdd"
    assert retag("[gif] xd", "xdd") == "[gif] xdd"
    assert retag("[nuotrauka] xd", "xdd") == "[nuotrauka] xdd"  # photos keep their own tag


# ---- the bot ---------------------------------------------------------------------------------------------
async def test_he_looks_at_a_gifs_frame_knowing_it_is_one_frame_and_remembers_it(app):
    bot, store, llm, out = await vbot(app, ["nu ir šoka", "Šokantis katinas."])
    out.images["THUMB"] = b"FRAME"
    await bot.on_message(inc("botucha žiūrėk", image_file_id="THUMB", gif=True))
    await settle()
    assert [t for _, t, _ in out.sent] == ["nu ir šoka"]
    reply, describe = llm.calls
    assert reply["images"] == [b"FRAME"]
    prompt = reply["messages"][1]["content"]
    assert GIF_GUARD in prompt and IMAGE_GUARD not in prompt  # told it sees a single frame of an animation
    assert describe["messages"][1]["content"] == GIF_DESCRIBE_PROMPT != DESCRIBE_PROMPT
    assert store.get_message(C, 1).text == "[gif: Šokantis katinas.] botucha žiūrėk"


async def test_a_gif_without_a_caption_is_stored_and_a_mention_answers_it(app):
    bot, store, llm, out = await vbot(app, ["matau"])
    out.images["THUMB"] = b"FRAME"
    await bot.on_message(inc("", mentions_bot=True, image_file_id="THUMB", gif=True))
    await settle()
    m = store.get_message(C, 1)
    assert m.text.startswith("[gif") and m.image_file_id == "THUMB" and out.sent


async def test_a_gif_without_a_frame_is_answered_from_text_alone(app):
    bot, store, llm, out = await vbot(app, ["xd"])
    await bot.on_message(inc("botucha žiūrėk", gif=True))
    await settle()
    assert store.get_message(C, 1).text == "[gif] botucha žiūrėk"
    assert out.fetched == [] and llm.calls[0].get("images") is None and out.sent


async def test_a_caption_edit_keeps_the_gif_and_its_description(app):
    bot, store, llm, out = await vbot(app, ["nu ir šoka", "Šokantis katinas."])
    out.images["THUMB"] = b"FRAME"
    await bot.on_message(inc("botucha žiūrėk", image_file_id="THUMB", gif=True))
    await settle()
    await bot.on_message(inc("botucha žiūrėkit", image_file_id="THUMB", gif=True, edited=True))
    assert store.get_message(C, 1).text == "[gif: Šokantis katinas.] botucha žiūrėkit"


async def test_a_gif_description_is_not_group_vocabulary(app):
    bot, store, llm, out = await vbot(app, ["gražu", "Akiniuotas katinukas šoka."])
    out.images["THUMB"] = b"FRAME"
    await bot.on_message(inc("botucha žiūrėk", image_file_id="THUMB", gif=True))
    await settle()
    words = bot.vocabulary()
    assert "akiniuotas" not in words and "žiūrėk" in words
