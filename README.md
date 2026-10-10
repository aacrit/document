# Document

Live at [`document.voidvision.org`](https://document.voidvision.org).

Built and governed by the [Agentique](https://github.com/aacrit/agentique) plugin.
See `CLAUDE.md` for product law and `CHARTER.md` for scope.

## Develop

```sh
npm install
npm run dev       # vite + wrangler dev
npm run gate      # typecheck, tests, and lint suite - must be green before merge
npx wrangler d1 migrations apply document --local   # local D1 schema, once
npm run build && npx wrangler dev --local           # the built site plus the Worker
npm run contract -- --url http://localhost:8787   # served-page contract, local
```

Against localhost, contract checks marked `requires: deployed` (the rate-limit
burst) report SKIP; they must PASS against the preview before a release.

## Deploy

There is no deploy workflow in this repo. Production deploys run locally
through the Agentique plugin's `/release` skill, which cuts a `release/*` tag
from green `main` and deploys that exact commit. Rollback means re-pointing
the tag to a previous release and redeploying it the same way.

## Stack

Vite static frontend + one Cloudflare Worker + D1, on Workers Static Assets.
Static files never invoke the Worker; the Worker runs only for its own routes,
behind a per-client rate limit, with day ceilings on every D1 write. Security
headers and the CSP come from `scripts/lib/csp.mjs`. Fonts are self-hosted.
See `wrangler.jsonc`, `budget.yaml`, and `contract.yaml`.

## Telemetry

`/e` counts named events (see `contract.yaml`'s `events.allowed`) as daily
aggregate totals, no identifiers, no cookies, no local storage. No
third-party analytics script (including Cloudflare Web Analytics) is added
by default, and per-request logs are off. The kill criteria in `CHARTER.md`
count `contract.yaml`'s success_event, the product's core action. See
`web/privacy.html`; `tests/privacy-page.test.ts` keeps each of its claims
true.
