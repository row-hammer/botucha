"""Two people calling him in one burst each get their own reply, on their own message. One reply on the last
message sent the first person's answer as a reply to the second person."""
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)


async def test_two_people_in_one_burst_each_get_a_reply_to_their_own_message(app):
    bot, _, llm, out = await app(["tadui atsakymas", "mantui atsakymas"])
    await bot.on_message(inc("botucha kas naujo", msg_id=1))
    await bot.on_message(inc("botucha ka veiki", msg_id=2, user=222, name="Mantas", username="mantas"))
    await settle()
    assert [(t, r) for _, t, r in out.sent] == [("tadui atsakymas", 1), ("mantui atsakymas", 2)]


async def test_the_second_reply_sees_the_first_one(app):
    bot, _, llm, out = await app(["tadui atsakymas", "mantui atsakymas"])
    await bot.on_message(inc("botucha kas naujo", msg_id=1))
    await bot.on_message(inc("botucha ka veiki", msg_id=2, user=222, name="Mantas", username="mantas"))
    await settle()
    last_prompt = llm.calls[-1]["messages"][1]["content"]
    assert "tadui atsakymas" in last_prompt  # so he does not answer Tadas twice


async def test_one_person_writing_twice_still_gets_one_reply(app):
    bot, _, _, out = await app(["vienas atsakymas"])
    await bot.on_message(inc("botucha klausimas", msg_id=1))
    await bot.on_message(inc("botucha dar viena mintis", msg_id=2))
    await settle()
    assert [(t, r) for _, t, r in out.sent] == [("vienas atsakymas", 2)]
