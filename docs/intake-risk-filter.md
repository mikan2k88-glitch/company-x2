# Intake risk filter

Three declarations are required for new quote and creation HTTP requests: sensitive_data, critical_use, extra_liability. Values are yes/no/unknown. Only three no answers permit the limited supported scope; yes rejects and unknown or missing information stops intake. This is self-report screening, not detection of undisclosed data or legal clearance. The version, declaration values and notice are stored in the plan and included in its hash. Changing or omitting answers invalidates the quote.

New live sales remain unconditionally disabled because the operator currently requires no liability beyond refunds, which this system cannot guarantee. Environment flags and passing declarations cannot unlock live Checkout. Existing payment evidence, production, delivery and refunds remain available for existing orders. Do not silently reopen sales when changing configuration.

No database migration or external AI call is needed. Public and operator intake pages both start with unanswered selections. API validation applies before public quota reservation and order creation. Legacy direct sandbox fixtures can build an informational plan without declarations; HTTP acceptance cannot.

The filter does not establish enforceability of contractual waivers. Consumer law and other mandatory duties remain applicable. No raw customer CSV cells are sent to an external model for this screening.
