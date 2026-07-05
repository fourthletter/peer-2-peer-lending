from src.storage import normalize_url


def test_normalize_url_strips_trailing_slash():
    a = normalize_url("https://Example.com/path/")
    b = normalize_url("https://example.com/path")
    assert a == b


def test_normalize_url_strips_fragment():
    a = normalize_url("https://example.com/a#section")
    b = normalize_url("https://example.com/a")
    assert a == b
