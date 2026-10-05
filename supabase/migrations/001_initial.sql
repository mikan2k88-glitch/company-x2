-- Apply manually after selecting a dedicated project or isolated schema.
create schema if not exists company_x2;
create table company_x2.jobs (
 id uuid primary key default gen_random_uuid(),
 source text not null,
 external_id text not null,
 customer_ref text,
 service_key text not null,
 state text not null default 'discovered' check (state in
 ('discovered','qualified','agreed','authorized','produced','verified','delivered','paid','cancelled')),
 price_jpy bigint not null default 0 check (price_jpy >= 0),
 cost_limit_jpy bigint not null default 0 check (cost_limit_jpy >= 0),
 version integer not null default 0,
 created_at timestamptz not null default now(),
 unique(source, external_id)
);
create table company_x2.events (
 id bigint generated always as identity primary key,
 job_id uuid not null references company_x2.jobs(id),
 operation_key text not null unique,
 event_type text not null,
 evidence jsonb not null,
 created_at timestamptz not null default now()
);
create table company_x2.artifacts (
 id uuid primary key default gen_random_uuid(),
 job_id uuid not null references company_x2.jobs(id),
 storage_path text not null,
 sha256 text not null,
 created_at timestamptz not null default now()
);
alter table company_x2.jobs enable row level security;
alter table company_x2.events enable row level security;
alter table company_x2.artifacts enable row level security;
-- No public policies. Server persistence adapter and transactional RPC are pending.

