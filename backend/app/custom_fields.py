import json
import re
from datetime import date
from typing import Optional, Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .database import tenant_connection, resolve_tenant_database, TenantDatabaseError

router = APIRouter(prefix="/api/v1", tags=["Dynamic Custom Fields"])

FIELD_TYPES = {
    "text", "long_text", "number", "decimal", "date",
    "dropdown", "multi_select", "checkbox", "email", "phone"
}

MODULES = {
    "products", "inventory", "purchases", "sales",
    "customers", "suppliers", "gst", "accounting",
    "staff", "reports"
}

def cf_tenant(code):
    code = (code or "").strip().upper()
    try:
        resolve_tenant_database(code)
    except TenantDatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return code

def cf_key(label):
    value = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not value:
        raise HTTPException(status_code=400, detail="Invalid field label.")
    return value[:60]

class CustomFieldCreate(BaseModel):
    module_key: str
    label: str = Field(min_length=1, max_length=100)
    field_type: str
    options: list[str] = []
    is_required: bool = False

class CustomFieldUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    field_type: Optional[str] = None
    options: Optional[list[str]] = None
    is_required: Optional[bool] = None
    is_active: Optional[bool] = None

class CustomFieldReorder(BaseModel):
    field_ids: list[int]

class CustomFieldValues(BaseModel):
    values: dict[str, object]

def field_dict(row):
    item = dict(row)
    item["options"] = json.loads(item.pop("options_json") or "[]")
    item["is_required"] = bool(item["is_required"])
    item["is_active"] = bool(item["is_active"])
    return item

def check_field_type(field_type, options):
    if field_type not in FIELD_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported field type.")
    if field_type in {"dropdown", "multi_select"} and not options:
        raise HTTPException(status_code=400, detail="Add at least one dropdown option.")

@router.get("/custom-fields")
def get_custom_fields(
    module_key: str,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    if module_key not in MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")
    with tenant_connection(code) as db:
        rows = db.execute(
            """SELECT * FROM custom_field_definitions
               WHERE module_key=? ORDER BY sort_order, id""",
            (module_key,)
        ).fetchall()
    return {"module_key": module_key, "fields": [field_dict(r) for r in rows]}

@router.post("/custom-fields", status_code=201)
def create_custom_field(
    payload: CustomFieldCreate,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    module = payload.module_key.strip().lower()
    label = payload.label.strip()
    check_field_type(payload.field_type, payload.options)
    if module not in MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")
    key = cf_key(label)
    options = [str(x).strip() for x in payload.options if str(x).strip()]
    with tenant_connection(code) as db:
        try:
            cursor = db.execute(
                """INSERT INTO custom_field_definitions
                   (module_key, field_key, label, field_type,
                    options_json, is_required, sort_order)
                   VALUES (?, ?, ?, ?, ?, ?, 
                    COALESCE((SELECT MAX(sort_order)+1
                    FROM custom_field_definitions WHERE module_key=?),0))""",
                (module, key, label, payload.field_type,
                 json.dumps(options), int(payload.is_required), module)
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(
                    status_code=409,
                    detail="A field with this name already exists in this module."
                )
            raise
        row = db.execute(
            "SELECT * FROM custom_field_definitions WHERE id=?",
            (cursor.lastrowid,)
        ).fetchone()
    return {"message": "Custom field created.", "field": field_dict(row)}

@router.put("/custom-fields/{field_id}")
def update_custom_field(
    field_id: int,
    payload: CustomFieldUpdate,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="No changes supplied.")
    if "field_type" in data:
        check_field_type(data["field_type"], data.get("options", []))
    if "options" in data:
        data["options_json"] = json.dumps(data.pop("options"))
    if "is_required" in data:
        data["is_required"] = int(data["is_required"])
    if "is_active" in data:
        data["is_active"] = int(data["is_active"])
    data["updated_at"] = "CURRENT_TIMESTAMP"
    assignments = []
    values = []
    for key, value in data.items():
        if key == "updated_at":
            assignments.append("updated_at=CURRENT_TIMESTAMP")
        else:
            assignments.append(f"{key}=?")
            values.append(value)
    values.append(field_id)
    with tenant_connection(code) as db:
        cursor = db.execute(
            f"UPDATE custom_field_definitions SET {','.join(assignments)} WHERE id=?",
            values
        )
        if not cursor.rowcount:
            raise HTTPException(status_code=404, detail="Field not found.")
        row = db.execute(
            "SELECT * FROM custom_field_definitions WHERE id=?", (field_id,)
        ).fetchone()
    return {"message": "Custom field updated.", "field": field_dict(row)}

@router.put("/custom-fields/reorder")
def reorder_custom_fields(
    payload: CustomFieldReorder,
    module_key: str,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    if module_key not in MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")
    with tenant_connection(code) as db:
        existing = {
            row["id"] for row in db.execute(
                "SELECT id FROM custom_field_definitions WHERE module_key=?",
                (module_key,)
            ).fetchall()
        }
        if set(payload.field_ids) != existing:
            raise HTTPException(
                status_code=400,
                detail="Reorder must include all fields in this module."
            )
        for position, field_id in enumerate(payload.field_ids):
            db.execute(
                """UPDATE custom_field_definitions
                   SET sort_order=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=? AND module_key=?""",
                (position, field_id, module_key)
            )
    return {"message": "Field order saved."}

@router.get("/custom-field-values/{module_key}/{entity_id}")
def get_custom_field_values(
    module_key: str,
    entity_id: str,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    if module_key not in MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")
    with tenant_connection(code) as db:
        rows = db.execute(
            """SELECT d.field_key, v.value_json
               FROM custom_field_values v
               JOIN custom_field_definitions d ON d.id=v.field_id
               WHERE v.module_key=? AND v.entity_id=?""",
            (module_key, entity_id)
        ).fetchall()
    return {
        "module_key": module_key,
        "entity_id": entity_id,
        "values": {
            row["field_key"]: json.loads(row["value_json"])
            for row in rows
        }
    }

@router.put("/custom-field-values/{module_key}/{entity_id}")
def save_custom_field_values(
    module_key: str,
    entity_id: str,
    payload: CustomFieldValues,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = cf_tenant(x_tenant_code)
    if module_key not in MODULES:
        raise HTTPException(status_code=400, detail="Invalid module.")
    with tenant_connection(code) as db:
        definitions = db.execute(
            """SELECT * FROM custom_field_definitions
               WHERE module_key=? AND is_active=1""",
            (module_key,)
        ).fetchall()
        by_key = {row["field_key"]: row for row in definitions}
        for key, value in payload.values.items():
            field = by_key.get(key)
            if not field:
                raise HTTPException(
                    status_code=400, detail=f"Unknown or inactive custom field: {key}"
                )
            if value in ("", None, []):
                if field["is_required"]:
                    raise HTTPException(
                        status_code=400, detail=f"{field['label']} is required."
                    )
                encoded = None
            else:
                kind = field["field_type"]
                if kind in {"number", "decimal"}:
                    try:
                        number = float(value)
                        if kind == "number" and not number.is_integer():
                            raise ValueError()
                        value = int(number) if kind == "number" else number
                    except (ValueError, TypeError):
                        raise HTTPException(
                            status_code=400, detail=f"{field['label']} must be numeric."
                        )
                elif kind == "checkbox":
                    if not isinstance(value, bool):
                        raise HTTPException(
                            status_code=400, detail=f"{field['label']} must be checked or unchecked."
                        )
                elif kind == "date":
                    try:
                        date.fromisoformat(str(value))
                    except ValueError:
                        raise HTTPException(
                            status_code=400, detail=f"{field['label']} must be a valid date."
                        )
                elif kind == "dropdown":
                    options = json.loads(field["options_json"] or "[]")
                    if value not in options:
                        raise HTTPException(
                            status_code=400, detail=f"Invalid option for {field['label']}."
                        )
                elif kind == "multi_select":
                    options = json.loads(field["options_json"] or "[]")
                    if not isinstance(value, list) or any(v not in options for v in value):
                        raise HTTPException(
                            status_code=400, detail=f"Invalid selection for {field['label']}."
                        )
                encoded = json.dumps(value)
            db.execute(
                """INSERT INTO custom_field_values
                   (module_key, entity_id, field_id, value_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(module_key, entity_id, field_id)
                   DO UPDATE SET value_json=excluded.value_json,
                                 updated_at=CURRENT_TIMESTAMP""",
                (module_key, entity_id, field["id"], encoded)
            )
    return {"message": "Custom field values saved."}
