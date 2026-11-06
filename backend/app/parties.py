from typing import Optional, Literal
import sqlite3
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from .database import tenant_connection, resolve_tenant_database, TenantDatabaseError

router = APIRouter(prefix="/api/v1", tags=["Customers and Suppliers"])

class PartyCreate(BaseModel):
    party_type: Literal["customer", "supplier", "both"]
    name: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance: float = 0
    credit_limit: float = 0
    notes: Optional[str] = None

class PartyUpdate(BaseModel):
    party_type: Optional[Literal["customer", "supplier", "both"]] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    phone: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    opening_balance: Optional[float] = None
    credit_limit: Optional[float] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None

def party_tenant(code):
    try:
        code = (code or "").strip().upper()
        resolve_tenant_database(code)
        return code
    except TenantDatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/parties")
def list_parties(
    party_type: Optional[Literal["customer", "supplier", "both"]] = Query(None),
    search: str = "",
    limit: int = Query(500, ge=1, le=1000),
    x_tenant_code: Optional[str] = Header(None)
):
    code = party_tenant(x_tenant_code)
    sql = "SELECT * FROM parties WHERE is_active=1"
    params = []
    if party_type:
        sql += " AND party_type IN (?, 'both')"
        params.append(party_type)
    if search.strip():
        sql += " AND (name LIKE ? OR phone LIKE ? OR gstin LIKE ?)"
        term = f"%{search.strip()}%"
        params.extend([term, term, term])
    sql += " ORDER BY name LIMIT ?"
    params.append(limit)
    with tenant_connection(code) as db:
        rows = db.execute(sql, params).fetchall()
    return {"parties": [dict(row) for row in rows]}

@router.post("/parties", status_code=201)
def create_party(payload: PartyCreate, x_tenant_code: Optional[str] = Header(None)):
    code = party_tenant(x_tenant_code)
    data = payload.model_dump()
    data["name"] = (data.get("name") or f"__{data['party_type'].upper()}_{__import__('time').time_ns()}__").strip()
    columns = list(data.keys())
    with tenant_connection(code) as db:
        cursor = db.execute(
            f"INSERT INTO parties ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [data[key] for key in columns]
        )
        row = db.execute("SELECT * FROM parties WHERE id=?", (cursor.lastrowid,)).fetchone()
    return {"message": "Party created.", "party": dict(row)}

@router.get("/parties/{party_id}")
def get_party(party_id: int, x_tenant_code: Optional[str] = Header(None)):
    code = party_tenant(x_tenant_code)
    with tenant_connection(code) as db:
        row = db.execute("SELECT * FROM parties WHERE id=?", (party_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"party": dict(row)}

@router.put("/parties/{party_id}")
def update_party(
    party_id: int,
    payload: PartyUpdate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = party_tenant(x_tenant_code)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No changes supplied.")
    if "is_active" in data:
        data["is_active"] = int(data["is_active"])
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
    assignments = ", ".join(f"{key}=?" for key in data)
    with tenant_connection(code) as db:
        cursor = db.execute(
            f"UPDATE parties SET {assignments} WHERE id=?",
            [*data.values(), party_id]
        )
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="Record not found.")
        row = db.execute("SELECT * FROM parties WHERE id=?", (party_id,)).fetchone()
    return {"message": "Record updated.", "party": dict(row)}
