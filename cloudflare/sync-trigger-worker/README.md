# cc-sync-trigger

Cloudflare cron Worker that dispatches `.github/workflows/sync-easystore-customers-hubspot.yml`
(EasyStore → HubSpot CRM sync, including variant inventory counts) for `prod` and `dev`.

- Schedule: `0 * * * *` (hourly, on the hour).
- Auth: the GitHub repository secret `SYNC_TRIGGER_GITHUB_TOKEN` is pushed to the Worker
  as a secret by `.github/workflows/deploy-cloudflare-sync-trigger-worker.yml`.
  Use a fine-grained PAT scoped to this repository with **Actions: Read and write**.
- Each environment is dispatched independently; one failure does not block the other and
  fails the cron invocation so it shows in Cloudflare observability.
- Test locally: `npm run dev` then `curl "http://localhost:8787/cdn-cgi/handler/scheduled"`.
