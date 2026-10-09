# E28: persistent Supabase contact verification

Set CX2_CONTACT_EXPERIMENT_STORAGE=supabase with a fresh owned fixture URL and ordinary OUTREACH_ENABLED=false. The startup experiment now uses the server's SupabaseStore and existing cx2_outreach RPC. No schema migration is needed.

It refuses pending contacts or a visible attempt today, prepares and claims the fixture, verifies its claimed identity, posts and checks duplicates, saves the simulated requester reply, and reopens the configured storage adapter to verify status, comment URL, reply and next-message draft. The actual shared daily claim still applies; this test consumes that day's one attempt. Failed sending records are marked uncertain when possible and are never automatically retried.

The owned fixture is closed after testing. The resulting synthetic record is retained for inspection in the authenticated Company screen; it is not a customer, order, sale or payment. The same owner simulates both sides. Reset the experiment configuration after verification. The ordinary worker stays disabled.
