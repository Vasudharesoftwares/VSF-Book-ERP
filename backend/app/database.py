import sqlite3
from contextlib import contextmanager
from .config import TENANT_DATABASES

class TenantDatabaseError(Exception):
    pass

def resolve_tenant_database(tenant_code):
    path = TENANT_DATABASES.get((tenant_code or "").strip().upper())
    if path is None:
        raise TenantDatabaseError("Unknown bookstore client.")
    if not path.is_file():
        raise TenantDatabaseError("Client database unavailable.")
    return path

@contextmanager
def tenant_connection(tenant_code):
    # Only call after server-side authentication has authorised this tenant.
    connection = sqlite3.connect(resolve_tenant_database(tenant_code), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=15000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

def record_audit_event(connection, tenant_id, user_id, action,
                        entity_type, entity_id=None, details=None):
    connection.execute(
        "INSERT INTO audit_logs "
        "(tenant_id,user_id,action,entity_type,entity_id,details) "
        "VALUES (?,?,?,?,?,?)",
        (tenant_id,user_id,action,entity_type,
         str(entity_id) if entity_id is not None else None,details)
    )
