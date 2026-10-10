# E36: owned external loop verification

GitHub Actions experiment run 38051833267 passed on 2026-10-10 against private fixture Issue #39 (closed after testing). Real GitHub posts: scope inquiry, same-account simulated structured consent, fixture-only intake invitation, simulated consent withdrawal. Duplicate initial inquiry did not add a comment.

The coordinator's source-bound grant was consumed by an isolated HTTP server with temporary SQLite. Synthetic CSV `id / 001 / 001` produced one data row; the downloaded BOM-bearing UTF-8 bytes matched the stored SHA-256, and receipt was recorded. Submission could not replace the GitHub source URL. A withdrawn consent then blocked new intake with HTTP 400.

The installation token cannot call `/user`; the created Issue's author supplied fixture identity. This verifies GitHub transport, not Render's dedicated PAT. The posted fixture invitation uses a localhost placeholder, cannot authorize public Render intake, and is explicitly marked as an experiment. A virtual-day advance in isolated SQLite exercised the initial/follow-up flow without changing production daily quotas. This is not a real customer or paid order.

Regression checks verify uncertain invitation POST results are not retried in the next hour, expired grants cannot be posted, and a consent change seen during final revalidation is saved before holding the invitation. No manual recovery is allowed to imply a successful send.

Supabase Cron job 1 (`15 * * * *`) ran successfully at 11:15 and 12:15 UTC on 2026-10-10; HTTP responses 2 and 3 were 200 with no timeout/error. The 12:15 application cycle completed successfully and sent zero messages. Both HTTP wake responses reported the same-hour replay guard; the 12:15 application record confirms that hour completed successfully. Ordinary external sends, paid acceptance and automatic price changes remain disabled/gated. Cost assumptions, seller disclosure and liability conditions remain production blockers.
