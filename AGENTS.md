# Nix V0 agent guide

## Read first

Before changing this repository, read in full:

1. `docs/ARCHITECTURE.md`
2. `docs/IMPLEMENTATION_PLAN.md`
3. every accepted ADR in `docs/decisions/`
4. the relevant entries in `docs/UPSTREAM.md`

Work only on the next explicitly requested slice. Do not build later-slice infrastructure early.

## Non-negotiable contracts

- Paperclip is the only authoritative work graph.
- Telegram is for conversation, questions, grilling, and decisions.
- Todoist contains only concrete actions that Lior must personally execute. Never put clarification questions there.
- Substantive work handed between persistent employees must be represented in Paperclip.
- Agents may create and execute subordinate work inside an approved project or goal. A new top-level project or goal requires Lior's approval.
- Durable company knowledge and roadmaps live in `nix-brain` and change through pull requests. Live task state does not.
- External communication, meaningful spend, destructive production action, and major irreversible decisions require approval until policy explicitly changes.
- Exhaust reasonable autonomous alternatives before escalating to Lior.
- The employee closest to a consequential ambiguity asks Lior in that employee's Telegram context.
- Brainkeeper may flag or propose fixes for stale/conflicting knowledge; it must not silently choose between semantic contradictions.

## Implementation rules

- Compose supported upstream tools. Do not create an agent runtime, task manager, knowledge database, package manager, dashboard, or generic plugin layer.
- Use Paperclip's built-in adapters and official MCP/API surfaces before writing integration code.
- Keep harness and model choices in configuration. Do not encode business policy in provider-specific prompts or APIs.
- Verify fast-moving upstream documentation and the selected release immediately before implementing a slice. Update `docs/UPSTREAM.md` when assumptions change.
- Pin deployable versions; do not deploy floating `latest` tags.
- Prefer one small, observable end-to-end path over an isolated installation.
- Preserve upstream data models. Add the thinnest adapter only when no supported upstream surface satisfies an accepted slice.

## State and secrets

- Git contains redacted configuration, scripts, tests, and documentation.
- Databases, volumes, sessions, queues, clones, and logs are runtime state and stay outside Git.
- Tokens, keys, cookies, credential exports, and encryption keys are secrets and never enter Git, issue text, prompts, or logs.
- Commit `.env.example` files with names and explanations only. Runtime secret files must be outside the checkout and mode `0600`.
- A stateful slice is not done until backup and restore behavior is documented and tested proportionately.

## Done means

- Every acceptance criterion for the slice is evidenced.
- Automated tests pass without weakening them.
- The documented manual end-to-end check has been performed.
- Logs identify the request/work/run across system boundaries without exposing secrets.
- Failure behavior is visible and retry-safe where practical.
- Documentation and the upstream compatibility snapshot match what was actually deployed.
