Refs #N

<!-- Use `Refs #N` when a live check or team confirmation is still outstanding and the issue must stay open. Change this line to `Closes #N` only when this pull request fully completes the issue and every acceptance criterion is done. -->

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
- [ ] `TEST_DATABASE_URL=postgresql+psycopg://jdr:jdr@localhost:5432/jdr_test uv run pytest -v`

`TEST_DATABASE_URL` selects the database. Point it at a disposable PostgreSQL database whose name ends in `_test`. CI uses `postgresql+psycopg://jdr:jdr@localhost:5432/jdr_test`. Report the skipped count. A run that skips the PostgreSQL tests does not satisfy this check.

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
