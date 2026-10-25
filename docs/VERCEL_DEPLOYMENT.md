# Deploying the dashboard on Vercel

## UI deployment

Import `vsvaidya27/loophole` into Vercel. Use the repository root as Root Directory (leave it unset), Framework Preset **Other**, and Node.js **22.x**. The root `vercel.json` supplies install/build commands and the `dashboard/dist` output directory. Select `rishab/graph-transfer-demo` for a preview before merging PR #10.

Keep the repository root available during builds: the leaderboard exporter reads committed `results/` evidence outside `dashboard/`. There is no root npm package to install; the commands explicitly target `dashboard/`.

All five React tabs, the integrated pipeline demo (`demo.html`), the saved transfer report, showcase assets, video/audio and legacy replay HTML are built together. Navigation uses hashes, so no SPA catch-all rewrite is needed. The live graph connects directly to the existing public SpacetimeDB WebSocket service.

Optional build variables, when pointing at a different public graph:

- `VITE_SPACETIMEDB_HOST`: public WebSocket host.
- `VITE_SPACETIMEDB_DB`: database name.

The current defaults use the existing service. Never put Anthropic, Moss or database writer credentials into `VITE_*` variables; they become browser assets. Neither the UI build nor replaying saved evidence requires model credentials.

## What a static deployment does not run

The **Live Hub replay** scoring button POSTs to `/api/hub-demo/*`. The Rule transfer tab now embeds the saved pipeline presentation and needs no Python worker; it does not offer fresh sandbox replay. Vite proxies these paths to `127.0.0.1:8788` only in local development. Vercel does not run Vite's development proxy, and a remote browser cannot use the laptop's loopback service.

Until a remote replay worker is connected, the saved transfer evidence and showcase remain viewable, but fresh replay calls will fail and must not be described as fresh validation.

For full remote replay, host the Python worker on a dedicated Linux service with its environment dependencies, frozen evidence/cache and **bubblewrap** support. The current localhost server needs a deployment adapter with explicit trusted-origin validation, HTTPS ingress, authentication/rate limiting and request concurrency limits. Keep the generated-code OS sandbox and network restrictions intact. It cannot be deployed unchanged as a static asset or a Vercel Python function.

Once that service exists, proxy only `/api/hub-demo/:path*` to its HTTPS endpoint using a Vercel external rewrite. Account for request duration limits: transfer replay currently allows up to 180 seconds. An asynchronous job/poll API is preferable if the hosting proxy cannot reliably hold requests that long. Verify recorded-score and transfer responses, timeouts and unavailable-worker errors on the deployed preview before calling the entire pipeline live.

No deployment or new publicly accessible worker was created by this PR. Remaining setup: connect the Vercel project; then provision/connect the replay worker if judges need fresh sandbox checks remotely. The UI can be published independently with saved results clearly labeled.

## Local build

```sh
npm ci --prefix dashboard --no-audit --no-fund
npm run build --prefix dashboard
```

## References

- [Vercel project configuration](https://vercel.com/docs/project-configuration)
- [External rewrites](https://vercel.com/docs/routing/rewrites)
- [Monorepo build access](https://vercel.com/docs/monorepos/monorepo-faq)
- [Vercel limits](https://vercel.com/docs/limits)
