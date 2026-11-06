PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tenants (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    tenant_code TEXT NOT NULL UNIQUE,
    business_name TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment IN ('template','demo','production')),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE branches (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    branch_code TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    address TEXT,
    gstin TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, branch_code),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    role_name TEXT NOT NULL,
    description TEXT,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, role_name),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    branch_id INTEGER,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, email),
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (tenant_id, branch_id) REFERENCES branches(tenant_id, id)
);

CREATE TABLE user_roles (
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, user_id, role_id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id),
    FOREIGN KEY (tenant_id, role_id) REFERENCES roles(tenant_id, id)
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id),
    FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id)
);

INSERT INTO schema_migrations (version) VALUES ('001_initial_foundation');
