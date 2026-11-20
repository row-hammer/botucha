from botucha.evaluation import check_reply


def test_check_flags_long():
    assert "too long" in check_reply(["a " * 16], [])


def test_check_flags_impersonation():
    assert "impersonation" in check_reply(["Tadas: jo"], ["Tadas"])


def test_check_flags_diacritics():
    assert "diacritics" in check_reply(["ačiū labai", "šaunu", "nu jo"], [])


def test_check_flags_empty():
    assert check_reply([], []) == ["empty"]


def test_check_clean_ok():
    assert check_reply(["hodlinam iki nulio xdd", "nu nax"], ["Tadas"]) == []
