"""Pagination policy. The fake reader stands in for Jira."""

import pytest

from jdr_bot.brief_policy import SEARCH_FIELDS
from jdr_bot.brief_service import BriefService
from jdr_bot.ports import BriefQueryError, JiraIssue, JiraPage
from tests.brief_fakes import FakeJira, utc_schedule


def issue(key: str) -> JiraIssue:
    return JiraIssue(key, f"Task {key}", "In Progress", "Ada Lovelace")


async def test_pages_are_concatenated_in_order_and_stop_at_the_end():
    reader = FakeJira(
        pages=[
            JiraPage(issues=(issue("JDR-1"),), next_page_token="page-2", is_last=False),
            JiraPage(issues=(issue("JDR-2"),), next_page_token=None, is_last=True),
        ]
    )
    document = await BriefService(reader, utc_schedule(), page_size=1).collect()
    assert [item.key for item in document.issues] == ["JDR-1", "JDR-2"]
    assert document.truncated is False
    assert [request.next_page_token for request in reader.requests] == [None, "page-2"]
    assert reader.requests[0].fields == SEARCH_FIELDS
    assert "description" not in reader.requests[0].fields


async def test_page_cap_marks_the_brief_truncated():
    reader = FakeJira(
        pages=[
            JiraPage(issues=(issue("JDR-1"),), next_page_token="page-2", is_last=False),
            JiraPage(issues=(issue("JDR-2"),), next_page_token="page-3", is_last=False),
            JiraPage(issues=(issue("JDR-3"),), next_page_token=None, is_last=True),
        ]
    )
    document = await BriefService(reader, utc_schedule(), page_size=1, max_pages=2).collect()
    assert [item.key for item in document.issues] == ["JDR-1", "JDR-2"]
    assert document.truncated is True
    assert len(reader.requests) == 2


async def test_issue_cap_stops_before_later_pages():
    reader = FakeJira(
        pages=[
            JiraPage(
                issues=(issue("JDR-1"), issue("JDR-2")),
                next_page_token="page-2",
                is_last=False,
            ),
            JiraPage(issues=(issue("JDR-3"),), next_page_token=None, is_last=True),
        ]
    )
    document = await BriefService(reader, utc_schedule(), max_issues=1).collect()
    assert [item.key for item in document.issues] == ["JDR-1"]
    assert document.truncated is True
    assert len(reader.requests) == 1


async def test_repeated_page_token_is_a_query_failure():
    reader = FakeJira(
        pages=[JiraPage(issues=(issue("JDR-1"),), next_page_token="again", is_last=False)]
    )
    with pytest.raises(BriefQueryError) as error:
        await BriefService(reader, utc_schedule(), max_pages=3).collect()
    assert error.value.category == "malformed_response"
    assert error.value.transient is False


async def test_not_last_without_a_token_is_truncated_and_a_blank_token_is_not_sent():
    missing = FakeJira(
        pages=[JiraPage(issues=(issue("JDR-1"),), next_page_token=None, is_last=False)]
    )
    document = await BriefService(missing, utc_schedule(), max_pages=3).collect()
    assert [item.key for item in document.issues] == ["JDR-1"]
    assert document.truncated is True
    assert len(missing.requests) == 1

    blank = FakeJira(
        pages=[JiraPage(issues=(issue("JDR-2"),), next_page_token="  ", is_last=False)]
    )
    blank_document = await BriefService(blank, utc_schedule(), max_pages=3).collect()
    assert blank_document.truncated is True
    assert [item.next_page_token for item in blank.requests] == [None]


async def test_empty_page_is_not_a_failure():
    reader = FakeJira(pages=[JiraPage(issues=(), next_page_token=None, is_last=True)])
    document = await BriefService(reader, utc_schedule()).collect()
    assert document.issues == ()
    assert document.truncated is False


async def test_query_error_is_not_rewritten_as_an_empty_list():
    reader = FakeJira(errors=[BriefQueryError("access_denied", transient=False)])
    with pytest.raises(BriefQueryError) as error:
        await BriefService(reader, utc_schedule()).collect()
    assert error.value.category == "access_denied"
    assert reader.requests[0].jql.startswith('project = "JDR"')
