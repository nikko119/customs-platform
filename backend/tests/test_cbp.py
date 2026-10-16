from pathlib import Path
from crawlers.cbp import parse_article_html, parse_listing_html, filter_listing, normalize_url, parse_pagination_html, load_history, save_history, matches_keywords
from crawlers.engine import filter_titles

ROOT = Path(__file__).parent / "fixtures"
def test_article_parser():
    article = parse_article_html((ROOT / "cbp_article.html").read_text(), "https://www.cbp.gov/newsroom/media-releases/seized-cargo")
    assert article.title == "CBP seizes cargo shipment"
    assert "seized a package" in article.content
    assert "Follow CBP" not in article.content
    assert "human interest stories" not in article.content
    assert "footer information" not in article.content
    assert article.images[0].original_url.endswith("/files/cargo.jpg")
    assert article.content_hash

def test_listing_filter_and_dedupe():
    items = parse_listing_html((ROOT / "cbp_listing.html").read_text())
    assert len(items) == 2
    selected, filtered = filter_listing(items, ["seize"], limit=1)
    assert len(selected) == 1 and filtered == 1
    all_matches, all_filtered = filter_listing(items, ["seize"])
    assert len(all_matches) == 1 and all_filtered == 1
    assert normalize_url("https://www.cbp.gov/newsroom/media-releases/seized-cargo/").endswith("seized-cargo")

def test_pagination_and_history(tmp_path):
    html = '<nav class="usa-pagination"><a aria-current="page" href="?page=0">1</a><a href="?page=1">2</a></nav>'
    assert parse_pagination_html(html)[0].endswith("?page=1")
    path = tmp_path / "history.json"
    save_history(path, {"https://example.test/a": {"content_hash": "abc"}})
    assert load_history(path)["https://example.test/a"]["content_hash"] == "abc"

def test_body_keyword_filter():
    assert matches_keywords("The cargo shipment contained imported parcels.", ["cargo", "import"])
    assert not matches_keywords("A hiring ceremony was held at the academy.", ["cargo", "import"])
    assert matches_keywords("Any article passes when no terms are configured.", [])


def test_generic_title_filter_is_site_independent():
    items = [{"title": "Cargo notice", "url": "/cargo"}, {"title": "Recruiting notice", "url": "/jobs"}]
    selected, filtered = filter_titles(items, ("cargo",), limit=10)
    assert [item["url"] for item in selected] == ["/cargo"]
    assert filtered == 1
