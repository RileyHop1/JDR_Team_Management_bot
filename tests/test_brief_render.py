"""Brief text: mentions, empty results, truncation, and chunking."""

from datetime import date

from jdr_bot.brief import (
    EMPTY_BRIEF_LINE,
    BriefDocument,
    BriefIssueView,
    clean_issue_text,
    render_brief,
    render_failure,
)

DAY = date(2026, 6, 1)


def document(issues: tuple[BriefIssueView, ...], **overrides: object) -> BriefDocument:
    status_names = overrides.get("status_names", ("In Progress",))
    truncated = overrides.get("truncated", False)
    return BriefDocument(
        project_key="JDR",
        browse_base_url="https://example.atlassian.net",
        status_names=status_names if isinstance(status_names, tuple) else None,
        issues=issues,
        truncated=bool(truncated),
    )


def test_render_includes_key_title_assignee_status_and_url():
    text = "\n".join(
        render_brief(
            document(
                (
                    BriefIssueView("JDR-1", "Ship the brief", "In Progress", "Ada Lovelace"),
                    BriefIssueView("JDR-2", "Write tests", "Review", None),
                )
            ),
            local_date=DAY,
            timezone_name="UTC",
        )
    )
    assert "JDR-1: Ship the brief | Ada Lovelace | In Progress" in text
    assert "https://example.atlassian.net/browse/JDR-1" in text
    assert "JDR-2: Write tests | unassigned | Review" in text
    assert "https://example.atlassian.net/browse/JDR-2" in text
    assert "blocker" not in text.lower()
    assert "progress report" not in text.lower()


def test_empty_result_is_distinct_from_query_failure():
    empty = "\n".join(render_brief(document(()), local_date=DAY, timezone_name="UTC"))
    failed = "\n".join(
        render_failure(project_key="JDR", local_date=DAY, timezone_name="UTC", category="timeout")
    )
    assert EMPTY_BRIEF_LINE in empty
    assert "could not be loaded" not in empty
    assert "could not be loaded (timeout)" in failed
    assert EMPTY_BRIEF_LINE not in failed
    assert "JDR-1" not in failed


def test_custom_query_is_not_echoed():
    text = "\n".join(
        render_brief(
            document((), status_names=None),
            local_date=DAY,
            timezone_name="America/Los_Angeles",
        )
    )
    assert "Using the configured Jira query." in text
    assert "hidden-query-text" not in text
    assert "Statuses:" not in text


def test_mentions_are_broken_and_long_output_is_split():
    summary = "Hello @everyone <@123> <#456> and\n@here"
    cleaned = clean_issue_text(summary, 200)
    assert "@everyone" not in cleaned
    assert "@here" not in cleaned
    assert "<@123>" not in cleaned
    assert "<#456>" not in cleaned
    issues = tuple(
        BriefIssueView(f"JDR-{index}", f"Task {index} @everyone", "In Progress", "@here")
        for index in range(1, 5)
    )
    parts = render_brief(document(issues), local_date=DAY, timezone_name="UTC", limit=80)
    assert len(parts) > 1
    assert all(len(part) <= 80 for part in parts)
    combined = "\n".join(parts)
    assert "JDR-1" in combined and "JDR-4" in combined
    assert "@everyone" not in combined
    assert "(continued)" in combined
    truncated = "\n".join(
        render_brief(document(issues[:1], truncated=True), local_date=DAY, timezone_name="UTC")
    )
    assert "Showing the first 1 matching issues." in truncated
