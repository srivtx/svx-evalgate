# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.1.x   | yes       |
| 1.0.x   | security fixes only |
| < 1.0   | no        |

## Reporting a vulnerability

Report privately to the repository maintainers via GitHub's
**Report a vulnerability** flow on the Security tab. Please do not open a
public issue for anything security-relevant.

Include what you can of: the EvalGate version (`evalgate version`), the
config and command involved, and a reproduction. We aim to respond within
72 hours.

## Scope notes

EvalGate is a CI-local tool with a deliberately small attack surface:

- It executes the eval command you configured, in your runner, with your
  checkout — the same trust boundary your existing test step already has.
  `command` in the config is code by definition; treat config files as
  code and review them in PRs like code.
- It reads/writes only within the working directory (baseline, report)
  plus the GitHub API surface it posts to (step summary, PR comment) using
  the token GitHub injects into the action.
- It has zero runtime dependencies and makes no outbound network calls of
  its own; the only network activity beyond your own eval command is the
  optional PR comment, which uses the provided `GITHUB_TOKEN` and is
  disabled outside CI.

Out of scope: vulnerabilities in your eval command itself, in your CI
runner, or in dependencies you install for your suite.
