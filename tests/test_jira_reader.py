"""HTTP adapter mapping. No live Jira calls."""

import httpx
import pytest

from jdr_bot.jira import HttpJiraReader, parse_search_page
from jdr_bot.ports import BriefQueryError, JiraSearchRequest


def request() -> JiraSearchRequest:
    return JiraSearchRequest(
        jql='project = "JDR" AND summary ~ "hidden-query-text"',
        next_page_token=None,
        max_results=50,
        fields=("summary", "status", "assignee"),
    )


def issue_body(key: str = "JDR-1", summary: str = "Ship the brief") -> dict[str, object]:
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": "do not render this secret description",
            "status": {"name": "In Progress"},
            "assignee": {"displayName": "Ada Lovelace", "emailAddress": "ada@example.com"},
        },
    }


async def test_search_is_get_only_and_parses_one_page():
    seen: list[httpx.Request] = []

    def handler(incoming: httpx.Request) -> httpx.Response:
        seen.append(incoming)
        return httpx.Response(
            200,
            json={
                "isLast": False,
                "nextPageToken": "page-2",
                "issues": [issue_body()],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        page = await reader.search(request())
        await reader.aclose()
    assert page.is_last is False
    assert page.next_page_token == "page-2"
    assert page.issues[0].key == "JDR-1"
    assert page.issues[0].assignee_display_name == "Ada Lovelace"
    assert len(seen) == 1
    sent = seen[0]
    assert sent.method == "GET"
    assert sent.url.path == "/rest/api/3/search/jql"
    assert "synthetic-jira-token" not in str(sent.url)
    assert sent.url.params["fields"] == "summary,status,assignee"
    assert "description" not in sent.url.params["fields"]
    assert sent.headers["authorization"].startswith("Basic ")


@pytest.mark.parametrize(
    ("status", "category", "transient"),
    [
        (429, "rate_limited", True),
        (403, "access_denied", False),
        (401, "access_denied", False),
        (400, "query_rejected", False),
        (503, "jira_unavailable", True),
    ],
)
async def test_status_errors_hide_the_response_body(status: int, category: str, transient: bool):
    def handler(incoming: httpx.Request) -> httpx.Response:
        del incoming
        return httpx.Response(status, text='{"errorMessages":["secret-issue-title"]}')

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as error:
            await reader.search(request())
    assert error.value.category == category
    assert error.value.transient is transient
    assert error.value.__cause__ is None
    assert "secret-issue-title" not in str(error.value)
    assert "synthetic-jira-token" not in str(error.value)


async def test_timeout_and_malformed_json_are_classified():
    def timeout(incoming: httpx.Request) -> httpx.Response:
        del incoming
        raise httpx.ReadTimeout("timed out")

    transport = httpx.MockTransport(timeout)
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as error:
            await reader.search(request())
    assert error.value.category == "timeout"
    assert error.value.transient is True
    assert error.value.__cause__ is None

    def malformed(incoming: httpx.Request) -> httpx.Response:
        del incoming
        return httpx.Response(200, text="not-json secret-issue-title")

    transport = httpx.MockTransport(malformed)
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as malformed_error:
            await reader.search(request())
    assert malformed_error.value.category == "malformed_response"
    assert "secret-issue-title" not in str(malformed_error.value)


def test_parser_rejects_incomplete_issues_and_accepts_unassigned():
    page = parse_search_page(
        {
            "issues": [
                {
                    "key": "JDR-4",
                    "fields": {"summary": "Write tests", "status": {"name": "Review"}},
                }
            ]
        }
    )
    assert page.is_last is True
    assert page.issues[0].assignee_display_name is None
    with pytest.raises(BriefQueryError) as error:
        parse_search_page({"issues": [{"key": "not a key", "fields": {}}]})
    assert error.value.category == "malformed_response"
    with pytest.raises(BriefQueryError):
        parse_search_page(
            {
                "issues": [
                    {
                        "key": "JDR-1",
                        "fields": {"summary": "   ", "status": {"name": "In Progress"}},
                    }
                ]
            }
        )
