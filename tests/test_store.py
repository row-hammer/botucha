from botucha.store import Store, StoredMessage

C = -100


def msg(i, text="x", user=1, ts=None):
    return StoredMessage(chat_id=C, msg_id=i, user_id=user, name=f"u{user}", ts=ts or float(i), text=text)


def test_add_and_recent_order():
    s = Store(":memory:")
    for i in (1, 2, 3):
        s.add_message(msg(i, f"m{i}"))
    assert [m.text for m in s.recent_messages(C, 2)] == ["m2", "m3"]


def test_duplicate_message_ignored():
    s = Store(":memory:")
    assert s.add_message(msg(1)) is True
    assert s.add_message(msg(1)) is False
    assert len(s.recent_messages(C, 10)) == 1


def test_update_text():
    s = Store(":memory:")
    s.add_message(msg(1, "old"))
    s.update_message_text(C, 1, "new")
    assert s.recent_messages(C, 1)[0].text == "new"


def test_state_roundtrip():
    s = Store(":memory:")
    assert s.get_state("k", "d") == "d"
    s.set_state("k", "v")
    s.set_state("k", "v2")
    assert s.get_state("k") == "v2"


def test_member_upsert_updates_name():
    s = Store(":memory:")
    s.upsert_member(5, "Old", None)
    s.upsert_member(5, "New", "newnick")
    m = s.members()[5]
    assert (m.name, m.username) == ("New", "newnick")


def test_messages_after_and_last_rowid():
    s = Store(":memory:")
    s.add_message(msg(1))
    r = s.last_rowid(C)
    s.add_message(msg(2, "later"))
    after = s.messages_after(C, r)
    assert [m.text for _, m in after] == ["later"]
    assert s.last_rowid(C) == after[-1][0]
