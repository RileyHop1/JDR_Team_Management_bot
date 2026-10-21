# Code standards

These rules are the review baseline. Ruff formatting and lint, strict mypy for production modules, and pytest run in CI; see `docs/DEVELOPMENT.md` for exact commands.

## Readability and structure

- Prefer straightforward code over clever expressions, implicit behavior, and unnecessary abstractions.
- Give modules, functions, and variables names that describe their domain meaning. Avoid unexplained abbreviations, numbered variables, and generic names such as `data` when a precise name is available.
- Give each function one clear responsibility. Split code when it mixes validation, business decisions, persistence, and network operations. Do not split merely to satisfy an arbitrary line limit.
- Keep nesting shallow with guard clauses. Replace repeated domain logic with a shared function; do not build a generic framework for a single use case.
- Explain non-obvious constraints and reasons in comments. Remove commented-out code, stale comments, debugging prints, and unused imports.
- Document public interfaces, side effects, units, and error conditions. Keep implementation details out of user-facing messages.
- Use explicit imports; avoid wildcard imports, circular dependencies, and import-time network calls or service startup.

## Python baseline

- Target Python 3.12 until an architecture decision changes it. Use four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants.
- Format consistently with Ruff; use a 100-character target line length. Let the formatter control layout rather than hand-aligning code.
- Annotate production function signatures and meaningful data structures. Validate untrusted payloads at integration boundaries; convert them to typed domain models.
- Configure mypy strict checks for new production modules. Do not use `Any`, `cast`, `# type: ignore`, or lint suppressions to hide design problems. Any justified exception needs a narrow scope and a reason.
- Use dataclasses or validated models for structured state, enums for finite states, and explicit return types rather than positional tuples with unclear meanings.
- Avoid mutable default arguments, hidden global state, and duplicated configuration constants.

## Boundaries and asynchronous work

- Keep Discord, Jira, storage, scheduling, and transcription behind explicit interfaces. Business rules must be testable without live services.
- Pass dependencies explicitly. Do not create clients throughout the code or use a service locator to hide dependencies.
- Never block the event loop with synchronous HTTP, file processing, or CPU-heavy transcription. Use supported async clients or bounded worker execution.
- Own background tasks: track them, propagate cancellation, release resources, and await shutdown. Do not launch untracked fire-and-forget work.
- Bound queues, payload sizes, recording duration, and concurrent work. Set network timeouts and limited retries with backoff; honor provider rate limits.
- Store UTC-aware timestamps and use IANA time zones for user schedules. Test daylight saving transitions. Never use naive local timestamps for persistent scheduling.

## Correctness and failure handling

- Validate configuration at startup and fail with actionable errors that do not reveal secrets.
- Catch specific exceptions at boundaries. Never swallow errors or return success after a failed operation. Preserve the original cause when translating errors.
- Retry only transient failures and safe operations. Use durable job identities and duplicate checks; do not assume exactly-once delivery across a database and Discord.
- Use parameterized database queries, transactions for related state changes, and reviewed migrations. Never concatenate user input into SQL or shell commands.
- Enforce authorization on the server side for every management command, including guild and channel scope.
- Log structured operational context such as job IDs and error categories. Never log tokens, raw audio, transcript text, or unnecessary personal data.

## Tests and quality gates

- Cover business rules with deterministic unit tests; inject clocks and external clients instead of using sleeps or live credentials.
- Add integration tests for storage and provider adapters, including pagination, timeouts, rate limits, denied permissions, malformed responses, and restart recovery where relevant.
- Test observable outcomes and regression cases. A test that repeats the production algorithm is weak evidence.
- Use synthetic or redacted fixtures with no real meeting content. Keep live-service checks opt-in and isolated to test resources.
- CI already runs formatting, lint, static typing, and tests before merge. Exact commands are in the README and in `docs/DEVELOPMENT.md`.
- Treat coverage as a diagnostic, not a substitute for assertions. Do not disable checks, weaken assertions, or add blanket exclusions to get a green build.

## Review and maintainability

Every feature must include relevant tests, updated documentation, and clear failure behavior. Reviewers should request changes for confusing names, mixed responsibilities, hidden side effects, insecure handling, and unexplained complexity. Prefer the smallest design that meets the requirements and remains easy for the next teammate to change.
