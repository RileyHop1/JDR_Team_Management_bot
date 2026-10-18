"""Paginate a read-only Jira query into a brief document."""

from jdr_bot.brief import BriefDocument, BriefIssueView, BriefSchedule
from jdr_bot.brief_policy import MAX_ISSUES, MAX_PAGES, PAGE_SIZE, SEARCH_FIELDS
from jdr_bot.ports import BriefQueryError, JiraReader, JiraSearchRequest


class BriefService:
    """Collect matching issues. An empty page is a successful empty brief."""

    def __init__(
        self,
        reader: JiraReader,
        schedule: BriefSchedule,
        *,
        page_size: int = PAGE_SIZE,
        max_pages: int = MAX_PAGES,
        max_issues: int = MAX_ISSUES,
    ) -> None:
        self._reader = reader
        self._schedule = schedule
        self._page_size = page_size
        self._max_pages = max_pages
        self._max_issues = max_issues

    async def collect(self) -> BriefDocument:
        """Read pages until the query ends or the configured cap is reached.

        Raises BriefQueryError. Does not turn a failed query into an empty list.
        """
        collected: list[BriefIssueView] = []
        token: str | None = None
        seen: set[str] = set()
        truncated = False
        pages_read = 0
        while pages_read < self._max_pages:
            page = await self._reader.search(
                JiraSearchRequest(
                    jql=self._schedule.jql,
                    next_page_token=token,
                    max_results=self._page_size,
                    fields=SEARCH_FIELDS,
                )
            )
            pages_read += 1
            for issue in page.issues:
                if len(collected) >= self._max_issues:
                    truncated = True
                    break
                collected.append(
                    BriefIssueView(
                        key=issue.key,
                        summary=issue.summary,
                        status_name=issue.status_name,
                        assignee_display_name=issue.assignee_display_name,
                    )
                )
            if truncated or page.is_last or page.next_page_token is None:
                break
            if page.next_page_token in seen:
                raise BriefQueryError("malformed_response", transient=False)
            seen.add(page.next_page_token)
            token = page.next_page_token
        else:
            # The page cap was reached with a further page still advertised.
            truncated = True
        return BriefDocument(
            project_key=self._schedule.project_key,
            browse_base_url=self._schedule.browse_base_url,
            status_names=self._schedule.status_names,
            issues=tuple(collected),
            truncated=truncated,
        )
