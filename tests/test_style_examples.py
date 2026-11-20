from botucha.store import StoredMessage
from botucha.style import select_examples


def m(i, text):
    return StoredMessage(chat_id=-1, msg_id=i, user_id=1, name="mantas", ts=float(i), text=text)


def test_select_examples_count_and_order():
    msgs = [m(i, f"zinute {i}") for i in range(300)]
    out = select_examples(msgs, n=60)
    assert len(out) == 60
    nums = [int(line.split()[-1]) for line in out]
    assert nums == sorted(nums) and nums[0] == 0 and nums[-1] > 250


def test_skips_empty_and_long():
    msgs = [m(1, ""), m(2, "x" * 201), m(3, "nua\nna xdd")]
    assert select_examples(msgs, n=60) == ["mantas: nua na xdd"]
