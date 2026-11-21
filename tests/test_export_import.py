from pathlib import Path

from botucha.export_import import import_export, parse_export
from botucha.store import Store

FIX = Path(__file__).parent / "fixtures" / "export_small.json"


def test_parse_chat_id():
    chat_id, _ = parse_export(FIX)
    assert chat_id == -1001234567890


def test_entity_text_joined():
    _, msgs = parse_export(FIX)
    m = next(m for m in msgs if m.msg_id == 11)
    assert m.text == "ziurek https://example.com"
    assert m.user_id == 100000001 and m.ts == 1795111210.0


def test_photo_kept_with_empty_text():
    _, msgs = parse_export(FIX)
    assert next(m for m in msgs if m.msg_id == 12).text == ""


def test_service_skipped():
    _, msgs = parse_export(FIX)
    assert len(msgs) == 5 and 13 not in [m.msg_id for m in msgs]


def test_reply_to_parsed():
    _, msgs = parse_export(FIX)
    assert next(m for m in msgs if m.msg_id == 14).reply_to == 10


def test_import_is_idempotent():
    s = Store(":memory:")
    assert import_export(s, FIX) == 5
    assert import_export(s, FIX) == 0
    assert s.members()[222].name == "mantas"


def test_a_private_chat_export_gets_the_users_own_positive_id():
    from botucha.export_import import _chat_id
    assert _chat_id({"id": 4242, "type": "personal_chat"}) == 4242
    assert _chat_id({"id": 1234567890, "type": "private_supergroup"}) == -1001234567890
