from app.services.search_repository import normalize_search_text


def test_normalize_search_text():
    assert normalize_search_text("Blade.Runner: 1982!") == "blade runner 1982"
