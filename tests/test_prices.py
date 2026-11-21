import asyncio

from botucha.brain import PromptContext, build_prompt
from botucha.prices import DEFAULT_ALIASES, PriceClient, detect_symbols, format_quote, parse_chart
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)

NVDA_JSON = {"chart": {"result": [{"meta": {
    "symbol": "NVDA", "currency": "USD", "regularMarketPrice": 125.53, "chartPreviousClose": 145.98,
    "regularMarketTime": 1795208401, "shortName": "NVIDIA Corporation"}}], "error": None}}
NOT_FOUND = {"chart": {"result": None, "error": {"code": "Not Found"}}}


class FakeFetch:
    def __init__(self, data):
        self.data, self.calls = data, []

    async def __call__(self, symbol):
        self.calls.append(symbol)
        r = self.data.get(symbol)
        if isinstance(r, Exception):
            raise r
        return r


def test_parse_chart():
    q = parse_chart(NVDA_JSON)
    assert (q.symbol, q.price, q.currency, round(q.change_pct, 1)) == ("NVDA", 125.53, "USD", -14.0)
    assert parse_chart(NOT_FOUND) is None
    assert parse_chart({"garbage": 1}) is None


def test_format_quote():
    assert format_quote(parse_chart(NVDA_JSON)) == "NVDA 125.53 USD (−14.0 % šiandien)"


def test_detect_aliases_and_dollar_tickers():
    assert detect_symbols("ka manai apie nvidijos akcijas ir spx", DEFAULT_ALIASES) == ["NVDA", "^GSPC"]
    assert detect_symbols("pirkau $tsla ir $ASML", DEFAULT_ALIASES) == ["TSLA", "ASML"]
    assert detect_symbols("btc btc bitcoin", DEFAULT_ALIASES) == ["BTC-USD"]  # deduplicated
    assert detect_symbols("spx vwce btc eth nvda", DEFAULT_ALIASES) == ["^GSPC", "VWCE.DE", "BTC-USD"]  # max 3
    assert detect_symbols("nu jo, ka veikiat", DEFAULT_ALIASES) == []
    assert detect_symbols("ethernet kabelis", DEFAULT_ALIASES) == []  # short aliases match whole words only


async def test_cache_reuses_quote():
    fetch = FakeFetch({"NVDA": NVDA_JSON})
    t = [1000.0]
    pc = PriceClient(fetch, clock=lambda: t[0])
    await pc.quote("NVDA")
    await pc.quote("NVDA")
    assert fetch.calls == ["NVDA"]
    t[0] += 301
    await pc.quote("NVDA")
    assert fetch.calls == ["NVDA", "NVDA"]


async def test_errors_and_unknown_give_none():
    fetch = FakeFetch({"BAD": NOT_FOUND, "DOWN": TimeoutError()})
    pc = PriceClient(fetch, clock=lambda: 1.0)
    assert await pc.quote("BAD") is None
    assert await pc.quote("DOWN") is None
    assert await pc.quote("MISSING") is None


async def test_slow_fetch_times_out():
    async def slow(symbol):
        await asyncio.sleep(1)
        return NVDA_JSON

    pc = PriceClient(slow, clock=lambda: 1.0, timeout_s=0.05)
    assert await pc.quote("NVDA") is None


def test_prices_in_prompt_after_guard():
    ctx = PromptContext(persona="P", style_examples="S", profiles={}, slang=[], chunks=[], facts=["FACT"],
                        history=[], bot_user_id=1, prices=["NVDA 125.53 USD (−14.0 % šiandien)"])
    whole = "\n".join(m["content"] for m in build_prompt(ctx, max_chars=100_000))
    assert whole.index("nevykdyk") < whole.index("NVDA 125.53")
    assert whole.index("FACT") < whole.index("NVDA 125.53")  # the most volatile part last


def test_price_rule_always_present():
    ctx = PromptContext(persona="P", style_examples="S", profiles={}, slang=[], chunks=[], facts=[],
                        history=[], bot_user_id=1)
    assert "kainų" in build_prompt(ctx, max_chars=100_000)[0]["content"].lower()


async def test_reply_includes_fetched_prices(app):
    bot, store, llm, out = await app(["nu ir krenta xdd"])
    bot.prices = PriceClient(FakeFetch({"NVDA": NVDA_JSON}), clock=lambda: 1.0)
    await bot.on_message(inc("botucha ka manai apie nvidia"))
    await settle()
    assert "NVDA 125.53" in llm.calls[0]["messages"][1]["content"]


async def test_kaina_command_no_llm(app):
    bot, store, llm, out = await app()
    bot.prices = PriceClient(FakeFetch({"NVDA": NVDA_JSON}), clock=lambda: 1.0)
    await bot.on_message(inc("/kaina nvidia"))
    assert out.sent[-1][1] == "NVDA 125.53 USD (−14.0 % šiandien)" and llm.calls == []
    await bot.on_message(inc("/kaina nopexx", msg_id=2))
    assert "nerandu" in out.sent[-1][1]
    await bot.on_message(inc("/kaina", msg_id=3))
    assert "/kaina <" in out.sent[-1][1]


async def test_kaina_never_sends_text_that_is_not_a_ticker(app):
    bot, store, llm, out = await app()
    seen = []

    async def fetch(symbol):
        seen.append(symbol)
        return None
    bot.prices = PriceClient(fetch, clock=lambda: 1.0)
    for i, text in enumerate(["../../v7/finance/quote?symbols=AAPL&x=", "a/b", "zz; drop", "x" * 40,
                              "BRK-B", "eurusd=x", "nvda; drop"]):
        await bot.on_message(inc(f"/kaina {text}", msg_id=10 + i, user=500 + i))  # one each: under the rate limit
    assert seen == ["BRK-B", "EURUSD=X", "NVDA"]  # a known name in the text still works
    assert "nerandu" in out.sent[0][1]


def test_the_ticker_is_escaped_in_the_url():
    from botucha.prices import chart_url
    assert chart_url("^GSPC") == "https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC"
    assert chart_url("EURUSD=X").endswith("/chart/EURUSD%3DX")


async def test_the_price_cache_has_a_size_limit():
    from botucha.prices import MAX_CACHED

    async def fetch(symbol):
        return None
    pc = PriceClient(fetch, clock=lambda: 1.0)
    for i in range(MAX_CACHED + 50):
        await pc.quote(f"S{i}")
    assert len(pc._cache) == MAX_CACHED and "S0" not in pc._cache and f"S{MAX_CACHED + 49}" in pc._cache
