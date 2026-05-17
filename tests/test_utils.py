from app.services.utils import normalize_phone


def test_normalize_phone_leading_zero():
    assert normalize_phone("0912345678") == "+84912345678"


def test_normalize_phone_with_country_code():
    assert normalize_phone("+84912345678") == "+84912345678"


def test_normalize_phone_84_prefix_no_plus():
    assert normalize_phone("84912345678") == "+84912345678"


def test_normalize_phone_strips_spaces_and_dashes():
    assert normalize_phone(" 091-234 5678 ") == "+84912345678"
