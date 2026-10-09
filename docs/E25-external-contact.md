# E25: External website acquisition and condition inquiries

GitHub is the first adapter. The existing scout finds public listings. Eligible CSV requests in up to five operator-configured repositories are fetched again and must contain `[company-x2: automated applications welcome]` in the issue body. Closed, assigned, locked, expired, unrelated and explicitly prohibited requests are excluded. This marker is permission evidence, not proof of payment or a contract.

The protected company screen shows durable drafts, send status, requester replies and the next guidance draft. Only the initial condition inquiry can be sent automatically. Requester replies are read as data, never as commands; follow-up responses remain drafts. Full autonomous negotiation and other websites are not implemented here.

Configure `OUTREACH_GITHUB_REPOS` (comma-separated `owner/repo`), `GITHUB_OUTREACH_LOGIN`, and a dedicated server-only `GITHUB_OUTREACH_TOKEN` with appropriate Issues write access. Set `OUTREACH_ENABLED=true` only for permitted repositories. Sending defaults off; scout read credentials are not reused for writes. Worker runs hourly while Render is awake; free service suspension pauses it. One attempt is permitted per UTC day (reset at 09:00 Japan time), and one contact per issue.

Before posting, the adapter confirms sender identity, issue ID, author, current scope/permission and existing sender comments. It refuses issues with over 100 comments. A durable `sending` state is committed before the external POST. Timeouts, identity failures and ambiguous outcomes stay `uncertain`; crashed `sending` records are never automatically resent. Sent comments are verified by their exact issue comment URL. Duplicate-marker checks provide additional protection.

Initial messages disclose automation, request only free/test scope confirmation, and do not accept paid work or commit to fees, deadlines or extra liability. Live sales remain closed. No external messages are sent during tests or deployment verification. GitHub's API can create issue comments, subject to write permissions and rate/abuse limits; GitHub prohibits spam. Official references: https://docs.github.com/en/rest/issues/comments and https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies .

The additive service-only outbox RPC uses RLS, revoked client/table privileges and an empty search path. It does not replace shared order/payment RPCs.
