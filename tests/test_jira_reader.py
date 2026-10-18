"""HTTP adapter mapping. No live Jira calls."""

from datetime import UTC, datetime, timedelta
from email.utils import formatdate

import httpx
import pytest

from jdr_bot.brief import ASSIGNEE_NAME_UNAVAILABLE
from jdr_bot.brief_policy import MAX_RESPONSE_BYTES, MAX_RETRY_AFTER_SECONDS
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


def test_a_body_without_an_issues_array_is_a_failure():
    for payload in ({"errorMessages": ["nope"]}, {}, {"isLast": True}, {"issues": None}):
        with pytest.raises(BriefQueryError) as error:
            parse_search_page(payload)
        assert error.value.category == "malformed_response"
        assert error.value.transient is False
        assert "nope" not in str(error.value)


def test_blank_page_token_is_ignored_and_a_hidden_name_is_not_unassigned():
    page = parse_search_page(
        {
            "isLast": False,
            "nextPageToken": " \t ",
            "issues": [
                {
                    "key": "JDR-7",
                    "fields": {
                        "summary": "Ship the brief",
                        "status": {"name": "In Progress"},
                        "assignee": {"accountId": "abc"},
                    },
                },
                {
                    "key": "JDR-8",
                    "fields": {
                        "summary": "Write tests",
                        "status": {"name": "Review"},
                        "assignee": {},
                    },
                },
            ],
        }
    )
    assert page.is_last is False
    assert page.next_page_token is None
    assert page.issues[0].assignee_display_name == ASSIGNEE_NAME_UNAVAILABLE
    assert page.issues[1].assignee_display_name == ASSIGNEE_NAME_UNAVAILABLE
    assert page.issues[0].assignee_display_name != "unassigned"


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


class _CountingTransport(httpx.AsyncBaseTransport):
    """Yield fixed chunks and record how many bytes the client actually pulled."""

    def __init__(
        self, status: int, pieces: tuple[bytes, ...], headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.pieces = pieces
        self.headers = headers or {}
        self.pulled = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        del request
        owner = self

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for piece in owner.pieces:
                    owner.pulled += len(piece)
                    yield piece

            async def aclose(self) -> None:
                return None

        return httpx.Response(self.status, headers=self.headers, stream=Stream())


async def test_retry_after_is_honored_bounded_and_the_body_is_not_read():
    secret = b'{"errorMessages":["secret-issue-title"]}'
    counted = _CountingTransport(429, (secret,), headers={"Retry-After": "120"})
    async with httpx.AsyncClient(transport=counted) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as error:
            await reader.search(request())
    assert error.value.category == "rate_limited"
    assert error.value.transient is True
    assert error.value.retry_after == timedelta(seconds=120)
    assert counted.pulled == 0
    assert "secret-issue-title" not in str(error.value)

    capped = _CountingTransport(429, (secret,), headers={"Retry-After": "999999"})
    async with httpx.AsyncClient(transport=capped) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as capped_error:
            await reader.search(request())
    assert capped_error.value.retry_after == timedelta(seconds=MAX_RETRY_AFTER_SECONDS)
    assert capped.pulled == 0

    ignored = _CountingTransport(429, (secret,), headers={"Retry-After": "not-a-delay"})
    async with httpx.AsyncClient(transport=ignored) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as ignored_error:
            await reader.search(request())
    assert ignored_error.value.retry_after is None

    future = datetime.now(UTC) + timedelta(seconds=90)
    dated = _CountingTransport(
        429, (secret,), headers={"Retry-After": formatdate(future.timestamp(), usegmt=True)}
    )
    async with httpx.AsyncClient(transport=dated) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as dated_error:
            await reader.search(request())
    delay = dated_error.value.retry_after
    assert delay is not None
    assert 60 <= delay.total_seconds() <= 90


async def test_response_cap_is_enforced_while_streaming():
    chunk = b"x" * 64_000
    pieces = tuple(chunk for _ in range((MAX_RESPONSE_BYTES // len(chunk)) + 3))
    transport = _CountingTransport(200, pieces)
    async with httpx.AsyncClient(transport=transport) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as error:
            await reader.search(request())
    assert error.value.category == "malformed_response"
    assert error.value.transient is False
    assert transport.pulled < len(chunk) * len(pieces)
    assert transport.pulled <= MAX_RESPONSE_BYTES + len(chunk)

    declared = _CountingTransport(
        200,
        (b'{"issues":[]}',),
        headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)},
    )
    async with httpx.AsyncClient(transport=declared) as client:
        reader = HttpJiraReader(
            base_url="https://example.atlassian.net",
            email="person@example.com",
            api_token="synthetic-jira-token",
            client=client,
        )
        with pytest.raises(BriefQueryError) as declared_error:
            await reader.search(request())
    assert declared_error.value.category == "malformed_response"
    assert declared.pulled == 0
