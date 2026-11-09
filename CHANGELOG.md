# Changelog

## Unreleased

### Security

- With `AUTOOPS_AUTH_ENABLED=true`, every API route now requires credentials and the right permission; previously only creating and running workflows did.
- The API can no longer clear the approval requirement on restarts, rollbacks and other dangerous steps.
- Cross-origin requests are refused by default. Allow specific origins with `AUTOOPS_CORS_ORIGINS`.
- `AUTOOPS_CREATE_ADMIN` no longer creates `admin`/`admin`; it requires `AUTOOPS_ADMIN_PASSWORD`.
- Webhooks must have a signing secret and are verified before their payload is read. Secrets are no longer returned by the API.
- Text from goals, webhooks and LLM output is escaped in the web UI, Mermaid and Graphviz diagrams, and GitHub Actions exports.
- Every goal field, constraint and refinement request is screened for prompt injection, and injection patterns are stripped from past runs before they are quoted to the model.
- Logs now redact `sk-ant-` and `sk-proj-` keys, secrets in nested values and tracebacks, and values of fields such as `password`.
- `validate_url` rejects private and link-local addresses in all numeric forms; `validate_path` no longer accepts sibling directories sharing a prefix.
- Memory files and databases are created readable only by their owner.
- The Compose file publishes the web UI on localhost only and no longer publishes Redis.

### Fixed

- A failed step now stops the steps that depend on it. Tool failures were previously ignored, so later steps ran and `stop_on_failure` had no effect.
- Steps downstream of a denied or missing approval no longer run, and the interactive executor now honours approval gates.
- Edge conditions that cannot be evaluated are treated as not met instead of met.
- `POST /workflows` no longer fails when environment or priority is omitted, and workflow execution through the API works.
- `/memory/stats`, `/templates/search` and `/templates/categories` are reachable, and failed runs are counted.
- The auth, webhook and `/metrics` routes are served again, after being lost in earlier merges.
- `PlannerConfig.cache_config` works as documented.
- Planning fails rather than returning a workflow with remediation steps when remediation is disabled, or with more nodes than `max_nodes`.
- Template parameters other than `{{service}}` are substituted, and the YAML templates are included in the package.
- `autoops run` and `autoops memory show` display complete results, and goals containing `[` no longer crash the CLI.
- `secureMCP:jira` style tool references and the `analysis` tool name resolve, and dry runs report tools that do not exist.
- Datadog queries use real timestamps and accept minutes and days.
- A corrupt JSON memory file is kept as `memory.json.corrupt` instead of being overwritten, and saves are atomic.
- The Docker image builds.
- `__version__` matches the package version.

### Changed

- JWT handling uses PyJWT and password hashing uses bcrypt directly, replacing python-jose and passlib.
- `structlog` is now a runtime dependency, and the `web` extra includes everything the API imports.
