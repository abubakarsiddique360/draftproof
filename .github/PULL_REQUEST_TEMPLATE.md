## What changed

<!-- One paragraph. Link the issue if there is one. -->

## Why

<!-- The problem this solves. Include the failure mode if it is a bug fix. -->

## How to verify

```bash
make check
```

<!-- Add any manual steps: a run id, an event stream excerpt, an artifact diff. -->

## Checklist

- [ ] `make check` passes (lint, types, tests, web tests)
- [ ] New behaviour is covered by tests, including failure paths
- [ ] Documentation updated (`README.md`, `docs/`, `CHANGELOG.md`)
- [ ] No secrets, generated artifacts or unrelated formatting churn
- [ ] Security-sensitive changes (URL fetching, sanitisation, auth, storage paths) reviewed against `SECURITY.md`
