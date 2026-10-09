# E27: isolated Render contact transport experiment

`CX2_CONTACT_EXPERIMENT_URL` enables one startup experiment against an untouched Issue in the owned private company-x2 repository. It requires Render, an exact allowlist consisting of that repository, an exact fixture title and marker, and matching authenticated sender/issue author. It uses the actual Render GitHub credential and production sender identity checks. The ordinary outreach flag remains false.

The experiment prepares a temporary SQLite contact, sends the scope inquiry, repeats the send to check marker deduplication, posts a simulated requester reply from the same account, stores that reply and a follow-up draft, checks the daily claim, and closes the Issue. A sanitized report is emitted to Render logs. This verifies Render credentials and transport, not the production Supabase outbox. No real customer, contract or payment is involved.

Remove the experiment URL after verification. An already-closed fixture is skipped on restart. A fixture with preexisting comments is refused. This is a manually provisioned test fixture; it is not a recurring job.
