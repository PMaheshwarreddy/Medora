-- Medora knowledge database (separate Supabase project, MEDORA_KNOWLEDGE_DATABASE_URL).
-- Every fact row carries source_id, so a source can be reloaded or removed on its own,
-- and any dose or passage can be traced back to its file and page.
-- Safe to run again: everything is "if not exists".

create extension if not exists vector;
create extension if not exists pg_trgm;

create table if not exists kb_sources (
    id serial primary key,
    key text unique not null,              -- e.g. icmr-stw-2019-vol1
    title text not null,
    publisher text not null,
    edition text not null default '',
    kind text not null,                    -- guideline | formulary | essential_list | drug_label | patient_info | vocabulary | codes
    tier smallint not null,                -- 1 Indian govt, 2 WHO / NLM, 3 foreign reference, 4 vocabulary
    licence text not null,
    licence_note text not null default '',
    -- Reports may only use sources marked true (permission or an open licence).
    production_allowed boolean not null default false,
    files jsonb not null default '[]',     -- [{name, sha256, bytes}]
    status text not null default 'new',    -- new | loading | loaded | failed
    stats jsonb not null default '{}',
    loaded_at timestamptz
);

create table if not exists kb_runs (
    id serial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null default 'running', -- running | loaded | failed
    stats jsonb not null default '{}',
    error text not null default ''
);

-- One row per PDF page: what was read and whether it passed the checks.
create table if not exists kb_pages (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int not null,
    page_kind text not null,               -- workflow | monograph | table | front_matter | other
    title text not null default '',
    markdown text not null default '',
    checks jsonb not null default '{}',    -- coverage, unknown numbers, ...
    status text not null,                  -- ok | quarantined | skipped
    unique (source_id, page)
);

create table if not exists kb_conditions (
    id serial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    doid text unique not null,
    name text not null,
    normalized text not null,
    definition text not null default '',
    parents text[] not null default '{}',
    icd10cm text[] not null default '{}',
    icd11 text[] not null default '{}',
    mesh text[] not null default '{}',
    umls text[] not null default '{}'
);
create index if not exists kb_conditions_norm on kb_conditions (normalized);

-- Names for conditions, symptoms and drugs, from every vocabulary.
create table if not exists kb_terms (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    kind text not null,                    -- condition | symptom | drug
    concept text not null,                 -- DOID:xxx, HP:xxx, SYMP:xxx, MESH:Dxxx, UMLS:Cxxx
    term text not null,
    normalized text not null,
    preferred boolean not null default false,
    umls text not null default '',
    condition_id int references kb_conditions(id) on delete set null
);
create index if not exists kb_terms_norm on kb_terms (normalized);
create index if not exists kb_terms_concept on kb_terms (concept);
create index if not exists kb_terms_trgm on kb_terms using gin (normalized gin_trgm_ops);

create table if not exists kb_codes (
    system text not null,                  -- ICD-10-CM | ICD-11
    code text not null,
    title text not null,
    parent text not null default '',
    billable boolean not null default false,
    source_id int not null references kb_sources(id) on delete cascade,
    primary key (system, code)
);

create table if not exists kb_drugs (
    id serial primary key,
    name text not null,
    normalized text unique not null,
    sources text[] not null default '{}',
    drug_class text not null default '',
    schedule text not null default '',
    pregnancy_category text not null default '',
    nfi_page int,
    nlem jsonb,                            -- {code, levels, forms[]}
    who_eml jsonb                          -- {section, forms[]}
);

-- Brand -> composition (Hugging Face medicine sets, later).
create table if not exists kb_drug_products (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    brand text not null,
    normalized text not null,
    composition jsonb not null,            -- [{drug, strength}]
    form text not null default '',
    manufacturer text not null default ''
);
create index if not exists kb_drug_products_norm on kb_drug_products (normalized);

-- Passages for retrieval. The vector is MedCPT Article Encoder output.
create table if not exists kb_chunks (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int,
    section text not null default '',      -- suspect | red_flags | treatment | dosing | contraindications | summary ...
    topic text not null default '',        -- the condition or drug the passage is about
    breadcrumb text not null,
    body text not null,
    tokens int not null,
    content_hash text not null,
    condition_id int references kb_conditions(id) on delete set null,
    drug_id int references kb_drugs(id) on delete set null,
    embedding halfvec(768),
    tsv tsvector generated always as (to_tsvector('english', breadcrumb || ' ' || body)) stored,
    unique (source_id, content_hash)
);
create index if not exists kb_chunks_tsv on kb_chunks using gin (tsv);
create index if not exists kb_chunks_topic on kb_chunks (topic);

create table if not exists kb_doses (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int,
    drug text not null,
    drug_id int references kb_drugs(id) on delete set null,
    indication text not null default '',
    condition_id int references kb_conditions(id) on delete set null,
    population text not null default 'any', -- adult | child | neonate | any
    dose text not null,
    route text not null default '',
    frequency text not null default '',
    duration text not null default '',
    chunk_hash text not null default '',
    conflict boolean not null default false
);
create index if not exists kb_doses_drug on kb_doses (drug_id);

create table if not exists kb_drug_safety (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int,
    drug text not null,
    drug_id int references kb_drugs(id) on delete set null,
    kind text not null,                    -- contraindication | interaction | pregnancy | children | precaution | adverse | warning | overdose
    body text not null
);
create index if not exists kb_drug_safety_drug on kb_drug_safety (drug_id);

create table if not exists kb_red_flags (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int,
    topic text not null,
    condition_id int references kb_conditions(id) on delete set null,
    sign text not null,
    action text not null default ''
);

create table if not exists kb_patient_topics (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    title text not null,
    normalized text not null,
    also_called text[] not null default '{}',
    summary text not null,
    url text not null default '',
    condition_id int references kb_conditions(id) on delete set null
);

-- Everything a check refused, with the reason. Nothing is dropped silently.
create table if not exists kb_quarantine (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    page int,
    item jsonb not null,
    reason text not null,
    created_at timestamptz not null default now()
);

-- Brand details (Hugging Face medicine sets): what the label says it is for, its price and substitutes.
alter table kb_drug_products add column if not exists uses text not null default '';
alter table kb_drug_products add column if not exists side_effects text not null default '';
alter table kb_drug_products add column if not exists pack text not null default '';
alter table kb_drug_products add column if not exists price_inr numeric;
alter table kb_drug_products add column if not exists substitutes text[] not null default '{}';
alter table kb_drug_products add column if not exists composition_key text not null default '';
alter table kb_drug_products add column if not exists drug_id int references kb_drugs(id) on delete set null;
create index if not exists kb_drug_products_key on kb_drug_products (composition_key);

-- Disease -> symptom lists from community datasets (testing only until evaluated).
create table if not exists kb_disease_symptoms (
    id bigserial primary key,
    source_id int not null references kb_sources(id) on delete cascade,
    disease text not null,
    normalized text not null,
    condition_id int references kb_conditions(id) on delete set null,
    symptom text not null,
    symptom_normalized text not null,
    symptom_concept text not null default ''
);
create index if not exists kb_disease_symptoms_norm on kb_disease_symptoms (normalized);
create index if not exists kb_disease_symptoms_symptom on kb_disease_symptoms (symptom_normalized);
