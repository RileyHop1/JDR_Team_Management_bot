Closes #N

Do not post secrets, tokens, credential-bearing URLs, real transcripts, or other real meeting content.

## Summary

<!-- What changed, and why. -->

## Behavior change

<!-- What a user, operator, or contributor can do differently after this change. -->

## Validation evidence

For a code change, record each command and its result:

- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest -v` against a disposable PostgreSQL database whose name ends in `_test`

For a documentation-only change, record the link and content checks here instead of those commands.

Results:

<!-- Short summary of the output. Do not paste secrets or real meeting content. -->

Checks that could not run, and why:

<!-- Write "None." when every required check ran. -->

## Configuration and migration requirements

<!-- New environment variables, migrations, or operational steps. Write "None." when there are none. -->

## Known limitations

<!-- What this change does not cover. -->

## Security checklist

- [ ] No secrets, tokens, credential-bearing URLs, or real meeting content are logged.
- [ ] No secrets or real meeting content are committed or pasted into this pull request.

## Delivery workflow

Only one implementation PR may be open at a time. Merge or close the current implementation PR before opening the next.
