from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from research_agent.web.inspect.app import TEMPLATES_DIR, _page_cursor_query


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self.hrefs.append(href)


@pytest.mark.parametrize("current_pages", [False, True])
def test_paging_one_agent_list_preserves_the_other_list_position(
    current_pages: bool,
) -> None:
    current_run = "2026-09-21T10:00:00.000000Z,run-current"
    current_forecast = "2026-09-21T11:00:00.000000Z,forecast-current"
    query = (
        {"cursor": current_run, "forecast_cursor": current_forecast}
        if current_pages
        else {}
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/agents/example",
            "query_string": urlencode(query).encode(),
            "headers": [],
        }
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    page = templates.get_template("agent.html").render(
        request=request,
        configuration_id="example",
        genome=None,
        runs=[],
        forecasts=[],
        next_cursor_query=_page_cursor_query(
            "run-next", "forecast_cursor", query.get("forecast_cursor")
        ),
        forecasts_next_cursor_query=_page_cursor_query(
            "forecast-next", "cursor", query.get("cursor")
        ),
    )
    links = Links()
    links.feed(page)
    queries = [parse_qs(urlsplit(href).query) for href in links.hrefs]
    run_link = next(query for query in queries if query.get("cursor") == ["run-next"])
    forecast_link = next(
        query for query in queries if query.get("forecast_cursor") == ["forecast-next"]
    )
    assert run_link == {
        "cursor": ["run-next"],
        **({"forecast_cursor": [current_forecast]} if current_pages else {}),
    }
    assert forecast_link == {
        "forecast_cursor": ["forecast-next"],
        **({"cursor": [current_run]} if current_pages else {}),
    }
