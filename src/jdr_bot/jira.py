"""Read-only Jira Cloud search. This module must not create or edit issues."""

import json
from collections.abc import Mapping

import httpx

from jdr_bot.brief import issue_key_is_safe
from jdr_bot.brief_policy import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
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
            response = await self._client.get(
                url,
                params=params,
                auth=self._auth,
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException:
            raise BriefQueryError("timeout", transient=True) from None
        except httpx.TransportError:
            raise BriefQueryError("jira_unavailable", transient=True) from None
        body = response.content
        if response.status_code != 200:
            raise _status_error(response.status_code) from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise BriefQueryError("malformed_response", transient=False) from None
        try:
            document = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise BriefQueryError("malformed_response", transient=False) from None
        return parse_search_page(document)


def parse_search_page(document: object) -> JiraPage:
    """Validate one search payload. Extra fields are ignored, not rendered."""
    body = _mapping(document)
    raw_token = body.get("nextPageToken")
    if raw_token is not None and not isinstance(raw_token, str):
        raise BriefQueryError("malformed_response", transient=False)
    token = raw_token if isinstance(raw_token, str) and raw_token else None
    raw_last = body.get("isLast")
    if raw_last is None:
        is_last = token is None
    elif isinstance(raw_last, bool):
        is_last = raw_last
    else:
        raise BriefQueryError("malformed_response", transient=False)
    if is_last:
        token = None
    raw_issues = body.get("issues", [])
    if not isinstance(raw_issues, list):
        raise BriefQueryError("malformed_response", transient=False)
    issues = tuple(_parse_issue(item) for item in raw_issues)
    return JiraPage(issues=issues, next_page_token=token, is_last=is_last)


def _status_error(status: int) -> BriefQueryError:
    if status == 429:
        return BriefQueryError("rate_limited", transient=True)
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
            display = None
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
