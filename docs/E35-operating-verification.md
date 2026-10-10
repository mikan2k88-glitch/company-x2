# E35: operating diagnosis and signed intake verification

The private `/api/company/autonomy` endpoint reports freshness, failed or long-running cycles, source retrieval failures and uncertain invitation sends. A fresh successful run does not prove the scheduler initiated it. Supabase Cron is configured at minute 15 hourly; its own job history is the evidence for natural scheduled execution.

Non-numeric, negative or non-finite cost settings stop paid acceptance and external sends. Missing cost assumptions still stop paid acceptance; the existing free verification exception remains. Exchange rate and fee assumptions are operator inputs, not fetched or presented as current market rates. Existing absolute-liability sales hold remains.

The HTTP integration fixture signs a source-bound free intake grant, creates a plan and order, processes synthetic CSV, downloads and verifies its hash and records receipt. It verifies the stored source cannot be replaced by a submitted URL and customer intake grants cannot read operating diagnostics. It does not represent a real customer's consent or paid order.

Resume: resolve indicated configuration or connectivity problems, then allow the next hour to run. Same-hour execution is idempotent. Sending/uncertain invitations are never automatically retried. No price change, outbound enablement or paid acceptance is performed by this milestone.
