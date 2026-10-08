# Acceptance and delivery safety gates

New acceptance requires the existing three explicit declarations and a bounded content scan. The scan rejects sensitive column names, email addresses, recognizable credentials, formatted domestic phone numbers, private-key markers, spreadsheet-formula-like leading characters, and invalid control characters. It is deliberately conservative and can reject benign negative numeric values. It cannot identify every personal name, secret, sensitive fact, or downstream use, so passing is not a guarantee of safety or immunity.

The input scan version and input hash are bound into the quotation hash. Creation validates both declarations and evidence. Workers repeat input inspection and compare the hash, produce only supported deterministic transformations, verify the transformation, inspect the artifact, and persist input/artifact safety hashes in the result. No arbitrary code or external AI is used.

Download repeats artifact inspection and verifies both the safety hash and exact downloadable-byte hash. Receipt also requires matching safety evidence. Missing, outdated or mismatched evidence holds delivery, including existing orders created before these checks. The UI hides download and displays the hold; direct API calls cannot bypass it. Existing orders are not retroactively marked safe or automatically resubmitted. Failed paid production continues through the existing verified refund workflow.

Live sales remain closed under the operator refund-only liability requirement. This gate reduces known risks; it does not establish enforceability of liability exclusions. No database migration is required.
