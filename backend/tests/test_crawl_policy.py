from datetime import datetime

from crawlers.cbp import parse_listing_html, parse_published_datetime
from crawlers.cbp_fetch import resolve_crawl_plan
from crawlers.engine import filter_listing_date


def test_listing_date_window_keeps_recent_and_unknown_dates():
    cutoff = datetime(2026, 9, 15)
    items = [
        {"url": "recent", "published_at": "2026-10-01"},
        {"url": "old", "published_at": "2026-09-01"},
        {"url": "unknown", "published_at": None},
    ]

    kept, filtered, page_is_old = filter_listing_date(items, cutoff)

    assert [item["url"] for item in kept] == ["recent", "unknown"]
    assert filtered == 1
    assert page_is_old is False


def test_entirely_old_page_is_a_stop_signal():
    cutoff = datetime(2026, 9, 15)
    items = [
        {"published_at": "2026-09-01"},
        {"published_at": "2026-08-25"},
    ]

    kept, filtered, page_is_old = filter_listing_date(items, cutoff)

    assert kept == []
    assert filtered == 2
    assert page_is_old is True


def test_cbp_date_parser_accepts_listing_formats_and_unknowns():
    assert parse_published_datetime("2026-10-01") == datetime(2026, 10, 1)
    assert parse_published_datetime("Wed, 10/07/2026") == datetime(2026, 10, 7)
    assert parse_published_datetime("not a date") is None


def test_cbp_listing_prefers_visible_date_over_stale_datetime_attribute():
    html = '''
    <ul class="usa-collection">
      <li class="usa-collection__item">
        <div class="usa-collection__calendar-date"><time datetime="2020-09-30T12:00:00+01:00">
          <span class="usa-collection__calendar-date-month">Oct 14</span>
          <span class="usa-collection__calendar-date-day">2026</span>
        </time></div>
        <div class="usa-collection__heading"><a href="/newsroom/media-release/test">Cargo update</a></div>
      </li>
    </ul>
    '''

    item = parse_listing_html(html)[0]

    assert item["published_at"] == "2026-10-14"


def test_crawl_plan_uses_month_window_only_on_first_successful_run():
    now = datetime(2026, 10, 15)
    pages, cutoff, mode = resolve_crawl_plan(
        has_successful_task=False, requested_max_pages=None, initial_days=30, now=now
    )
    assert pages is None
    assert cutoff == datetime(2026, 9, 15)
    assert mode == "INITIAL_WINDOW"

    pages, cutoff, mode = resolve_crawl_plan(
        has_successful_task=True, requested_max_pages=None, initial_days=30, now=now
    )
    assert (pages, cutoff, mode) == (1, None, "INCREMENTAL_FIRST_PAGE")

    pages, cutoff, mode = resolve_crawl_plan(
        has_successful_task=False, requested_max_pages=2, initial_days=30, now=now
    )
    assert (pages, cutoff, mode) == (2, None, "MANUAL")
