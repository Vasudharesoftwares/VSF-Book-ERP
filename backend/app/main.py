import sqlite3
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import APP_VERSION, TENANT_DATABASES, TEMPLATE_DATABASE
from .database import (
    tenant_connection,
    resolve_tenant_database,
    TenantDatabaseError,
)

app = FastAPI(
    title="VASUDHARE SALESFORCE",
    version=APP_VERSION,
    description="Independent bookstore ERP platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Tenant-Code"],
)


# ---------- Request models ----------

class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    product_type: Literal[
        "book", "stationery", "school_supply", "office_supply", "other"
    ] = "book"
    name: str = Field(min_length=1, max_length=250)
    isbn10: Optional[str] = None
    isbn13: Optional[str] = None
    barcode: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    language: Optional[str] = None
    subject: Optional[str] = None
    class_grade: Optional[str] = None
    board: Optional[str] = None
    binding: Optional[str] = None
    hsn_code: Optional[str] = None
    category_id: Optional[int] = None
    unit: str = "PCS"
    mrp: float = Field(default=0, ge=0)
    purchase_price: float = Field(default=0, ge=0)
    selling_price: float = Field(default=0, ge=0)
    gst_rate: float = Field(default=0, ge=0)
    reorder_level: float = Field(default=0, ge=0)
    shelf_location: Optional[str] = None
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    product_type: Optional[Literal[
        "book", "stationery", "school_supply", "office_supply", "other"
    ]] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=250)
    isbn10: Optional[str] = None
    isbn13: Optional[str] = None
    barcode: Optional[str] = None
    author: Optional[str] = None
    publisher: Optional[str] = None
    edition: Optional[str] = None
    language: Optional[str] = None
    subject: Optional[str] = None
    class_grade: Optional[str] = None
    board: Optional[str] = None
    binding: Optional[str] = None
    hsn_code: Optional[str] = None
    category_id: Optional[int] = None
    unit: Optional[str] = None
    mrp: Optional[float] = Field(default=None, ge=0)
    purchase_price: Optional[float] = Field(default=None, ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    gst_rate: Optional[float] = Field(default=None, ge=0)
    reorder_level: Optional[float] = Field(default=None, ge=0)
    shelf_location: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class StockAdjustment(BaseModel):
    product_id: int = Field(gt=0)
    quantity_change: float
    reason: str = Field(min_length=2, max_length=250)


# ---------- Shared helpers ----------

def inspect_database(path):
    if not path.is_file():
        return {"available": False, "integrity": "missing", "tables": 0}
    with sqlite3.connect(path) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        tables = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    return {"available": True, "integrity": integrity, "tables": tables}


def tenant_code_from_header(x_tenant_code: Optional[str]):
    code = (x_tenant_code or "").strip().upper()
    if code not in TENANT_DATABASES:
        raise HTTPException(
            status_code=400,
            detail="Select a configured bookstore demo: DEMO-01 or DEMO-02.",
        )
    try:
        resolve_tenant_database(code)
    except TenantDatabaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return code


def get_main_branch_id(db):
    row = db.execute("SELECT id FROM branches ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="No branch is configured.")
    return row["id"]


def row_dict(row):
    return dict(row) if row else None


# ---------- General routes ----------

@app.get("/")
def root():
    return {
        "application": "VASUDHARE SALESFORCE",
        "version": APP_VERSION,
        "message": "Bookstore ERP API is running.",
    }


@app.get("/api/v1/health")
def health():
    template = inspect_database(TEMPLATE_DATABASE)
    demos = {
        code: inspect_database(path)
        for code, path in TENANT_DATABASES.items()
    }
    healthy = (
        template["available"]
        and template["integrity"] == "ok"
        and all(
            item["available"] and item["integrity"] == "ok"
            for item in demos.values()
        )
    )
    return {
        "status": "healthy" if healthy else "attention_required",
        "application": "VASUDHARE SALESFORCE",
        "version": APP_VERSION,
        "template_database": template,
        "demo_databases": demos,
    }


@app.get("/api/v1/system/modules")
def modules():
    names = [
        ("dashboard", "Dashboard"),
        ("books", "Books & Products"),
        ("inventory", "Inventory"),
        ("purchases", "Purchases"),
        ("billing", "Sales & Billing"),
        ("customers", "Customers"),
        ("suppliers", "Suppliers"),
        ("gst", "GST & Tax"),
        ("accounts", "Accounting"),
        ("reports", "Reports"),
        ("users", "Staff & Permissions"),
        ("settings", "Settings"),
    ]
    return {"modules": [{"id": key, "name": name} for key, name in names]}


# ---------- Product catalogue ----------

@app.get("/api/v1/products")
def list_products(
    search: Optional[str] = Query(default=None, max_length=150),
    product_type: Optional[str] = None,
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)

    sql = """
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE 1=1
    """
    params = []

    if active_only:
        sql += " AND p.is_active=1"
    if product_type:
        sql += " AND p.product_type=?"
        params.append(product_type)
    if search:
        term = f"%{search.strip()}%"
        sql += """
            AND (
                p.name LIKE ? OR p.sku LIKE ? OR p.isbn10 LIKE ?
                OR p.isbn13 LIKE ? OR p.barcode LIKE ?
                OR p.author LIKE ? OR p.publisher LIKE ?
            )
        """
        params.extend([term] * 7)

    sql += " ORDER BY p.name LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with tenant_connection(code) as db:
        rows = db.execute(sql, params).fetchall()
        total = db.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0]

    return {
        "tenant": code,
        "total_products": total,
        "returned": len(rows),
        "products": [dict(row) for row in rows],
    }


@app.post("/api/v1/products", status_code=201)
def create_product(
    payload: ProductCreate,
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)
    data = payload.model_dump()

    columns = list(data.keys())
    values = [data[column] for column in columns]

    with tenant_connection(code) as db:
        branch_id = get_main_branch_id(db)
        try:
            cursor = db.execute(
                f"INSERT INTO products ({','.join(columns)}) "
                f"VALUES ({','.join(['?'] * len(columns))})",
                values,
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="This SKU already exists or the category is invalid.",
            ) from exc

        product_id = cursor.lastrowid
        db.execute(
            """INSERT OR IGNORE INTO stock_balances
               (branch_id, product_id, quantity)
               VALUES (?, ?, 0)""",
            (branch_id, product_id),
        )
        product = db.execute(
            "SELECT * FROM products WHERE id=?", (product_id,)
        ).fetchone()

    return {"message": "Product created.", "product": dict(product)}


@app.get("/api/v1/products/{product_id}")
def get_product(
    product_id: int,
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)
    with tenant_connection(code) as db:
        product = db.execute(
            """SELECT p.*, c.name AS category_name
               FROM products p LEFT JOIN categories c
               ON c.id=p.category_id WHERE p.id=?""",
            (product_id,),
        ).fetchone()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found.")
    return {"product": dict(product)}


@app.put("/api/v1/products/{product_id}")
def update_product(
    product_id: int,
    payload: ProductUpdate,
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)
    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(status_code=400, detail="No changes supplied.")

    if "is_active" in data and data["is_active"] is not None:
        data["is_active"] = int(data["is_active"])

    data["updated_at"] = __import__("datetime").datetime.now().isoformat(
        timespec="seconds"
    )

    assignments = ", ".join(f"{key}=?" for key in data)

    with tenant_connection(code) as db:
        try:
            cursor = db.execute(
                f"UPDATE products SET {assignments} WHERE id=?",
                list(data.values()) + [product_id],
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409, detail="Invalid product or category."
            ) from exc

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found.")

        product = db.execute(
            "SELECT * FROM products WHERE id=?", (product_id,)
        ).fetchone()

    return {"message": "Product updated.", "product": dict(product)}




@app.delete("/api/v1/products/{product_id}")
def delete_product(
    product_id: int,
    x_tenant_code: Optional[str] = Header(default=None),
):
    """Safely deactivate a product without destroying historical records."""
    code = tenant_code_from_header(x_tenant_code)

    with tenant_connection(code) as db:
        product = db.execute(
            "SELECT id, name, is_active FROM products WHERE id=?",
            (product_id,),
        ).fetchone()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        if not product["is_active"]:
            return {
                "message": "Product is already inactive.",
                "product_id": product_id,
            }

        db.execute(
            """UPDATE products
               SET is_active=0, updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (product_id,),
        )

    return {
        "message": "Product deactivated. Historical records have been preserved.",
        "product_id": product_id,
    }

# ---------- Inventory ----------

@app.get("/api/v1/inventory")
def list_inventory(
    search: Optional[str] = Query(default=None, max_length=150),
    low_stock_only: bool = False,
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)

    sql = """
        SELECT
            p.id AS product_id, p.sku, p.name, p.product_type,
            p.barcode, p.isbn13, p.reorder_level, p.unit,
            p.shelf_location, p.purchase_price, p.selling_price,
            COALESCE(s.quantity, 0) AS quantity,
            CASE
                WHEN COALESCE(s.quantity, 0) <= p.reorder_level
                THEN 1 ELSE 0
            END AS low_stock
        FROM products p
        LEFT JOIN stock_balances s
          ON s.product_id=p.id AND s.branch_id=?
        WHERE p.is_active=1
    """
    params = []

    if search:
        term = f"%{search.strip()}%"
        sql += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
        params.extend([term, term, term])

    if low_stock_only:
        sql += " AND COALESCE(s.quantity,0) <= p.reorder_level"

    sql += " ORDER BY p.name"

    with tenant_connection(code) as db:
        branch_id = get_main_branch_id(db)
        rows = db.execute(sql, [branch_id, *params]).fetchall()

    items = [dict(row) for row in rows]
    return {
        "tenant": code,
        "total_items": len(items),
        "low_stock_count": sum(item["low_stock"] for item in items),
        "inventory": items,
    }


@app.post("/api/v1/inventory/adjust")
def adjust_inventory(
    payload: StockAdjustment,
    x_tenant_code: Optional[str] = Header(default=None),
):
    code = tenant_code_from_header(x_tenant_code)

    if payload.quantity_change == 0:
        raise HTTPException(
            status_code=400, detail="Quantity change cannot be zero."
        )

    with tenant_connection(code) as db:
        branch_id = get_main_branch_id(db)

        product = db.execute(
            "SELECT id FROM products WHERE id=? AND is_active=1",
            (payload.product_id,),
        ).fetchone()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found.")

        current = db.execute(
            """SELECT quantity FROM stock_balances
               WHERE branch_id=? AND product_id=?""",
            (branch_id, payload.product_id),
        ).fetchone()

        old_quantity = float(current["quantity"]) if current else 0.0
        new_quantity = old_quantity + payload.quantity_change

        if new_quantity < 0:
            raise HTTPException(
                status_code=400,
                detail="Insufficient stock. Adjustment would make stock negative.",
            )

        db.execute(
            """INSERT INTO stock_balances
               (branch_id, product_id, quantity, updated_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(branch_id, product_id)
               DO UPDATE SET quantity=excluded.quantity,
                             updated_at=CURRENT_TIMESTAMP""",
            (branch_id, payload.product_id, new_quantity),
        )

        db.execute(
            """INSERT INTO stock_ledger
               (branch_id, product_id, transaction_type,
                quantity_in, quantity_out, balance_after, notes)
               VALUES (?, ?, 'manual_adjustment', ?, ?, ?, ?)""",
            (
                branch_id,
                payload.product_id,
                max(payload.quantity_change, 0),
                abs(min(payload.quantity_change, 0)),
                new_quantity,
                payload.reason,
            ),
        )

    return {
        "message": "Stock adjusted.",
        "product_id": payload.product_id,
        "previous_quantity": old_quantity,
        "quantity_change": payload.quantity_change,
        "new_quantity": new_quantity,
    }


@app.get("/api/v1/inventory/low-stock")
def low_stock(
    x_tenant_code: Optional[str] = Header(default=None),
):
    return list_inventory(
        search=None,
        low_stock_only=True,
        x_tenant_code=x_tenant_code,
    )


from .custom_fields import router as custom_fields_router
app.include_router(custom_fields_router)


from .parties import router as parties_router
app.include_router(parties_router)


from .sales import router as sales_router
app.include_router(sales_router)


from .purchases import router as purchases_router
app.include_router(purchases_router)

from .finance import router as finance_router
app.include_router(finance_router)
