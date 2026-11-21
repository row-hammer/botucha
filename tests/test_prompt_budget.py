"""The prompt and the answer together fit the model's context. Measured on this model: 2.74 characters per token
for the group's Lithuanian; the budget assumes fewer, so a full prompt still fits."""
from botucha.brain import (BUDGET_CHARS_PER_TOKEN, CHARS_PER_TOKEN, IMAGE_TOKENS, PromptContext, build_prompt,
                           prompt_budget_chars)
from botucha.store import StoredMessage
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)


def test_the_budget_leaves_room_for_the_answer_and_an_image():
    plain = prompt_budget_chars(32768, num_predict=150, image=False)
    with_image = prompt_budget_chars(32768, num_predict=150, image=True)
    serious = prompt_budget_chars(32768, num_predict=450, image=False)
    # at the measured ratio, a prompt this long plus its answer is inside the context
    assert plain / CHARS_PER_TOKEN + 150 <= 32768 * 0.95
    assert with_image == plain - IMAGE_TOKENS * BUDGET_CHARS_PER_TOKEN and serious < plain


def test_a_full_transcript_is_trimmed_to_the_budget():
    hist = [StoredMessage(C, i, 111, "Tadas", float(i), "zinute " + "x" * 3000) for i in range(40)]
    ctx = PromptContext("P", "S", {}, [], [], [], hist, 1)
    budget = prompt_budget_chars(32768, num_predict=150, image=False)
    total = sum(len(m["content"]) for m in build_prompt(ctx, max_chars=budget))
    assert total <= budget and total / CHARS_PER_TOKEN + 150 < 32768


async def test_the_reply_uses_the_budget_and_the_trace_estimates_tokens_at_the_measured_ratio(app):
    import json
    from botucha.trace import Tracer
    bot, store, llm, _ = await app(["labas"])
    bot.tracer = Tracer(store)
    for i in range(40):
        store.add_message(StoredMessage(C, 100 + i, 222, "Mantas", 9_000.0 + i, "x" * 3000))
    await bot.on_message(inc("botucha labas", msg_id=500, ts=9_100.0))
    await settle()
    sent = sum(len(m["content"]) for m in llm.calls[-1]["messages"])
    assert sent <= prompt_budget_chars(bot.cfg.model.num_ctx, num_predict=bot.cfg.model.num_predict, image=False)
    detail = json.loads(store.conn.execute("SELECT detail FROM trace_steps WHERE kind='prompt'").fetchone()[0])
    assert abs(detail["approx_tokens"] - sent / CHARS_PER_TOKEN) <= 1


def test_the_persona_may_use_at_most_half_of_the_prompt():
    from types import SimpleNamespace
    from botucha.webapi.routes_settings import persona_limit
    cfg = SimpleNamespace(model=SimpleNamespace(num_ctx=32768, num_predict=150))
    assert persona_limit(cfg) == prompt_budget_chars(32768, num_predict=150, image=False) // 2
