# E24: Evidence-based support automation

The server reviews at most ten eligible inquiries every thirty seconds while Render is awake. Processing continues on the server without the user's PC. Free Render suspension pauses the worker; this is not a continuously running scheduler.

Only exact allowlisted FAQ questions receive automatic replies. Free text is never sent to an external model, and cannot trigger financial or legal promises. Seller disclosure, receipt requests and general refund messages await individual review.

Verified order owners can report problems as in E23. With current complete safety provenance, a mismatch between the saved artifact and its hashes, or artifact/service metadata, confirms a storage/delivery defect. The case remains held and paid orders become eligible for the existing full-refund worker. Provider evidence determines refund completion. No payment provider API is called by the support reviewer itself.

Missing, malformed or old proof stays uncertain. Matching hashes establish file integrity, not the correctness of a disputed transformation. Source CSVs are deleted after processing, so semantic objections remain held for individual review. No case hold is released automatically.

Audit records retain rule version, outcome, reason and timestamp. The commit compares the current order status, plan, result, case state and operator reply under transaction locks; stale checks cannot overwrite manual decisions. Duplicate workers commit once. Queues select oldest eligible inquiries and skip recorded reviews so uncertain tickets do not starve later ones.

The additional database RPC is service-only, uses an empty search path, and adds an RLS-protected private audit table. Existing shared RPC definitions are unchanged. Public access to audit records still requires the inquiry's confirmation key. Live sales remain closed.
