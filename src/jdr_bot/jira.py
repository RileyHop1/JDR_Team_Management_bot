"""Read-only Jira Cloud search. This module must not create or edit issues."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

from jdr_bot.brief import ASSIGNEE_NAME_UNAVAILABLE, issue_key_is_safe
from jdr_bot.brief_policy import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_RETRY_AFTER_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)
from jdr_bot.ports import BriefQueryError, JiraIssue, JiraPage, JiraSearchRequest


class HttpJiraReader:
    """GET ``/rest/api/3/search/jql`` only. Credentials stay on this object."""

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url
        self._auth = httpx.BasicAuth(email, api_token)
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.AsyncClient(
                timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
                follow_redirects=False,
            )
        )

    async def aclose(self) -> None:
        """Close the client this reader created. A shared test client stays open."""
        if self._owns_client:
            await self._client.aclose()

    async def search(self, request: JiraSearchRequest) -> JiraPage:
        """Read one search page. The token and response body are not logged."""
        params = {
            "jql": request.jql,
            "maxResults": str(request.max_results),
            "fields": ",".join(request.fields),
        }
        if request.next_page_token:
            params["nextPageToken"] = request.next_page_token
        url = f"{self._base_url}/rest/api/3/search/jql"
        try:
            async with self._client.stream(
                "GET",
                url,
                params=params,
                auth=self._auth,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status_code != 200:
                    retry_after = None
                    if response.status_code == 429:
                        retry_after = _bounded_retry_after(response.headers.get("Retry-After"))
                    raise _status_error(response.status_code, retry_after) from None
                body = await _read_capped(response)
        except BriefQueryError:
            raise
        except httpx.TimeoutException:
            raise BriefQueryError("timeout", transient=True) from None
        except httpx.TransportError:
            raise BriefQueryError("jira_unavailable", transient=True) from None
        try:
            document = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BriefQueryError("malformed_response", transient=False) from None
        return parse_search_page(document)


def parse_search_page(document: object) -> JiraPage:
    """Validate one search payload. Extra fields are ignored, not rendered."""
    body = _mapping(document)
    if "issues" not in body:
        raise BriefQueryError("malformed_response", transient=False)
    token = _page_token(body.get("nextPageToken"))
    raw_last = body.get("isLast")
    if raw_last is None:
        is_last = token is None
    elif isinstance(raw_last, bool):
        is_last = raw_last
    else:
        raise BriefQueryError("malformed_response", transient=False)
    if is_last:
        token = None
    raw_issues = body["issues"]
    if not isinstance(raw_issues, list):
        raise BriefQueryError("malformed_response", transient=False)
    issues = tuple(_parse_issue(item) for item in raw_issues)
    return JiraPage(issues=issues, next_page_token=token, is_last=is_last)


def _status_error(status: int, retry_after: timedelta | None = None) -> BriefQueryError:
    if status == 429:
        return BriefQueryError("rate_limited", transient=True, retry_after=retry_after)
    if status in (401, 403):
        return BriefQueryError("access_denied", transient=False)
    if status == 400:
        return BriefQueryError("query_rejected", transient=False)
    if status == 404:
        return BriefQueryError("jira_not_found", transient=False)
    if status == 408:
        return BriefQueryError("timeout", transient=True)
    if status >= 500:
        return BriefQueryError("jira_unavailable", transient=True)
    return BriefQueryError("jira_http", transient=False)


def _page_token(raw_token: object) -> str | None:
    """Return a page token. A blank token is missing, not a token to send."""
    if raw_token is None:
        return None
    if not isinstance(raw_token, str):
        raise BriefQueryError("malformed_response", transient=False)
    token = raw_token.strip()
    if not token:
        return None
    return token


def _bounded_retry_after(header: str | None) -> timedelta | None:
    """Honor Retry-After up to the configured cap. The header text is not logged."""
    if header is None:
        return None
    text = header.strip()
    if not text:
        return None
    seconds = _retry_after_seconds(text)
    if seconds is None or seconds <= 0:
        return None
    if seconds > MAX_RETRY_AFTER_SECONDS:
        seconds = float(MAX_RETRY_AFTER_SECONDS)
    return timedelta(seconds=seconds)


def _retry_after_seconds(text: str) -> float | None:
    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    else:
        if seconds != seconds:
            return None
        return seconds
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - datetime.now(UTC)).total_seconds()


async def _read_capped(response: httpx.Response) -> bytes:
    """Read the body until the cap. A larger declared or streamed body is rejected."""
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            advertised = int(declared)
        except ValueError:
            advertised = -1
        if advertised > MAX_RESPONSE_BYTES:
            raise BriefQueryError("malformed_response", transient=False)
    total = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise BriefQueryError("malformed_response", transient=False)
        chunks.append(chunk)
    return b"".join(chunks)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise BriefQueryError("malformed_response", transient=False)
    copied: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise BriefQueryError("malformed_response", transient=False)
        copied[key] = _json_value(item)
    return copied


def _json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict | list):
        return value
    raise BriefQueryError("malformed_response", transient=False)


def _parse_issue(value: object) -> JiraIssue:
    item = _mapping(value)
    key = item.get("key")
    if not isinstance(key, str) or not issue_key_is_safe(key):
        raise BriefQueryError("malformed_response", transient=False)
    fields = _mapping(item.get("fields"))
    summary = fields.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise BriefQueryError("malformed_response", transient=False)
    status = _mapping(fields.get("status"))
    status_name = status.get("name")
    if not isinstance(status_name, str) or not status_name.strip():
        raise BriefQueryError("malformed_response", transient=False)
    assignee_raw = fields.get("assignee")
    display: str | None
    if assignee_raw is None:
        display = None
    else:
        assignee = _mapping(assignee_raw)
        name = assignee.get("displayName")
        if name is None:
            display = ASSIGNEE_NAME_UNAVAILABLE
        elif isinstance(name, str) and name.strip():
            display = name
        else:
            raise BriefQueryError("malformed_response", transient=False)
    return JiraIssue(
        key=key,
        summary=summary,
        status_name=status_name,
        assignee_display_name=display,
    )
