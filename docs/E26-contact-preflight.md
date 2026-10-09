# E26: read-only external contact preflight

The authenticated Company screen has a “送信せずに接続を検査” button. Its POST `/api/company/outreach/check` performs only GitHub GETs: sender identity and up to five allowlisted repository metadata reads. It never claims a draft, posts a comment or changes configuration. It works with sending disabled, and reports missing configuration, identity mismatch, inaccessible/archived repositories, authentication rejection and network failures without exposing tokens or response bodies.

Read access does not prove Issues write scope. Fine-grained tokens may have Issues write without Contents write; repository `permissions.push` must not be used as proof of token scopes. The operator must explicitly grant Issues read/write on selected permitted repositories. Production `send` still rechecks permission marker, candidate scope and identity before posting.

Use a dedicated fine-grained personal token restricted to selected repositories, with Issues read/write and required metadata read; do not grant Contents write for this feature. Set `GITHUB_OUTREACH_TOKEN`, matching `GITHUB_OUTREACH_LOGIN` and `OUTREACH_GITHUB_REPOS` in Render. Keep `OUTREACH_ENABLED=false` until the read-only check and permitted source review are complete. Never paste the token into a customer page or chat.

No schema migration or paid service change is required. Render free suspension still pauses its worker. A successful preflight is not a test of real comment delivery or a claim that automatic outreach is running.
