# E37: free operating trial

Enable FREE_TRIAL_ENABLED with timezone-aware FREE_TRIAL_START and FREE_TRIAL_END spanning at most 14 days. Public intake accepts three reserved orders per UTC day, two per browser owner token, 50KB and 1,000 rows. Multiple tokens do not prove distinct people. Reservations survive restarts; ambiguous saves consume slots. The process lock supports the existing single-instance/single-process service only.

New plans and new orders stop outside the window. Existing customers can renew access after the window, resume an idempotent order and download/record receipt. Safety and support holds still apply. Three or more completed orders with a failure rate at least 30% pause new intake until the operating cause is addressed. No automatic retry or unlocking bypasses that hold.

The private /api/company/free-trial report selects only public-intake order IDs internally. Its output contains no IDs, owner tokens, CSV, artifact content, error strings or support messages. Metadata includes service, phase, and time from first processing-start event to first ready event; averages are elapsed times for successfully prepared artifacts, not CPU benchmarks. Processing failures remain separate from unreceived artifacts.

Hourly autonomy runs persist the aggregate and development suggestions. Reports guide reproduction with synthetic CSV and targeted regression tests; customer CSV is not copied into development fixtures or used for model training. Operational order storage remains necessary for processing and delivery as described on the public page. Experiments in isolated databases are not included.

Public CSV transformation calls no paid AI API. Admin request classification remains separately bounded by application reservations (monthly USD 5, daily USD 0.25); these are estimated reservations, not the provider's account billing limit. Hosting/resource consumption remains. Ordinary outreach and real payments stay disabled. No public marketing messages are sent by this release.
