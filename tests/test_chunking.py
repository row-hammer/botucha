from botucha.chunking import build_chunks, render_line
from botucha.store import StoredMessage


def m(i, ts, text="x", name="mantas"):
    return StoredMessage(chat_id=-1, msg_id=i, user_id=1, name=name, ts=ts, text=text)


def test_gap_splits():
    chunks = build_chunks([m(1, 0), m(2, 31 * 60)])
    assert len(chunks) == 2


def test_max_messages():
    chunks = build_chunks([m(i, i * 60) for i in range(16)])
    assert [c.last_msg_id - c.first_msg_id + 1 for c in chunks] == [15, 1]


def test_max_chars():
    msgs = [m(i, i, "a" * 100) for i in range(14)]
    chunks = build_chunks(msgs)
    assert len(chunks) > 1
    assert all(len(c.text) <= 1200 for c in chunks)


def test_single_long_line_kept():
    chunks = build_chunks([m(1, 0, "b" * 2000)])
    assert len(chunks) == 1 and len(chunks[0].text) > 1200


def test_text_format():
    chunks = build_chunks([m(1, 0, "nua na xdd", "mantas"), m(2, 5, "jo", "Tadas")])
    assert chunks[0].text == "mantas: nua na xdd\nDegeni: jo"
    assert (chunks[0].start_ts, chunks[0].end_ts) == (0, 5)


def test_media_placeholder():
    assert render_line(m(1, 0, "")) == "mantas: [media]"
