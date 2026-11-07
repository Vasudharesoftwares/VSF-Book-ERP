import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .database import (
    tenant_connection,
    resolve_tenant_database,
    TenantDatabaseError,
)

router = APIRouter(prefix="/api/v1", tags=["Purchases"])


def tenant_code(value):
    code = (value or "").strip().upper()
    try:
        resolve_tenant_database(code)
    except TenantDatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return code


def money(value):
    return float(Decimal(str(value or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ))


def setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        po_no TEXT NOT NULL,
        supplier_id INTEGER NOT NULL REFERENCES parties(id),
        branch_id INTEGER NOT NULL REFERENCES branches(id),
        order_date TEXT NOT NULL,
        expected_date TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(branch_id, po_no)
    );

    CREATE TABLE IF NOT EXISTS purchase_order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity REAL NOT NULL CHECK(quantity > 0),
        received_quantity REAL NOT NULL DEFAULT 0,
        unit_cost REAL NOT NULL DEFAULT 0,
        gst_rate REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS goods_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        receipt_no TEXT NOT NULL,
        purchase_order_id INTEGER REFERENCES purchase_orders(id),
        supplier_id INTEGER NOT NULL REFERENCES parties(id),
        branch_id INTEGER NOT NULL REFERENCES branches(id),
        receipt_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        notes TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(branch_id, receipt_no)
    );

    CREATE TABLE IF NOT EXISTS goods_receipt_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        goods_receipt_id INTEGER NOT NULL REFERENCES goods_receipts(id) ON DELETE CASCADE,
        purchase_order_item_id INTEGER REFERENCES purchase_order_items(id),
        product_id INTEGER NOT NULL REFERENCES products(id),
        received_quantity REAL NOT NULL CHECK(received_quantity > 0),
        accepted_quantity REAL NOT NULL DEFAULT 0,
        rejected_quantity REAL NOT NULL DEFAULT 0,
        unit_cost REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS purchase_returns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        return_no TEXT NOT NULL,
        purchase_id INTEGER REFERENCES purchases(id),
        supplier_id INTEGER NOT NULL REFERENCES parties(id),
        branch_id INTEGER NOT NULL REFERENCES branches(id),
        return_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(branch_id, return_no)
    );

    CREATE TABLE IF NOT EXISTS purchase_return_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_return_id INTEGER NOT NULL REFERENCES purchase_returns(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id),
        quantity REAL NOT NULL CHECK(quantity > 0),
        unit_cost REAL NOT NULL DEFAULT 0
    );

    CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier
        ON purchase_orders(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_goods_receipts_supplier
        ON goods_receipts(supplier_id);
    CREATE INDEX IF NOT EXISTS idx_purchase_returns_supplier
        ON purchase_returns(supplier_id);
    """)

    # Perpetual weighted-average costing tables.
    # DDL is run by setup before the goods-receipt transaction begins.
    db.executescript("""
    CREATE TABLE IF NOT EXISTS inventory_cost_balances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        branch_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        physical_quantity REAL NOT NULL DEFAULT 0,
        inventory_value REAL NOT NULL DEFAULT 0,
        average_unit_cost REAL,
        cost_status TEXT NOT NULL DEFAULT 'verified',
        last_movement_id INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(branch_id, product_id)
    );

    CREATE TABLE IF NOT EXISTS inventory_cost_movements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        movement_key TEXT NOT NULL UNIQUE,
        branch_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        movement_type TEXT NOT NULL,
        reference_type TEXT,
        reference_id INTEGER,
        reference_line_id INTEGER,
        quantity_in REAL NOT NULL DEFAULT 0,
        quantity_out REAL NOT NULL DEFAULT 0,
        unit_cost REAL,
        value_in REAL NOT NULL DEFAULT 0,
        value_out REAL NOT NULL DEFAULT 0,
        quantity_after REAL NOT NULL,
        inventory_value_after REAL NOT NULL,
        cost_status TEXT NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_inventory_cost_movements_product
    ON inventory_cost_movements(branch_id, product_id, id);

    CREATE INDEX IF NOT EXISTS idx_inventory_cost_movements_reference
    ON inventory_cost_movements(reference_type, reference_id);
    """)

    # Receipt-linked supplier invoice allocations.
    # Multiple invoices may cover one receipt line, but never more than accepted qty.
    db.executescript("""
    CREATE TABLE IF NOT EXISTS purchase_receipt_invoice_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL REFERENCES purchases(id),
        purchase_item_id INTEGER NOT NULL REFERENCES purchase_items(id),
        goods_receipt_item_id INTEGER NOT NULL REFERENCES goods_receipt_items(id),
        quantity REAL NOT NULL CHECK(quantity > 0),
        receipt_unit_cost REAL NOT NULL,
        invoice_unit_cost REAL NOT NULL,
        inventory_variance_allocation REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_receipt_invoice_allocations_item
    ON purchase_receipt_invoice_lines(goods_receipt_item_id);
    """)

    # Idempotent posting flags for existing purchase invoices.
    columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(purchases)"
        ).fetchall()
    }
    if "stock_posted" not in columns:
        db.execute(
            "ALTER TABLE purchases ADD COLUMN stock_posted INTEGER NOT NULL DEFAULT 0"
        )

    # Receipt-linked purchase invoice status migrations.
    purchase_columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(purchases)"
        ).fetchall()
    }
    purchase_status_migrations = {
        "receipt_allocation_status": "TEXT NOT NULL DEFAULT 'pending'",
        "inventory_cost_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for column, definition in purchase_status_migrations.items():
        if column not in purchase_columns:
            db.execute(
                f"ALTER TABLE purchases ADD COLUMN {column} {definition}"
            )

    # Receipt-linked invoice costing and quantity-allocation migrations.
    purchase_item_columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(purchase_items)"
        ).fetchall()
    }
    purchase_item_migrations = {
        "receipt_allocated_quantity": "REAL NOT NULL DEFAULT 0",
        "final_cost_variance": "REAL NOT NULL DEFAULT 0",
        "costing_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for column, definition in purchase_item_migrations.items():
        if column not in purchase_item_columns:
            db.execute(
                f"ALTER TABLE purchase_items ADD COLUMN {column} {definition}"
            )

    receipt_item_columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(goods_receipt_items)"
        ).fetchall()
    }
    receipt_item_migrations = {
        "invoiced_quantity": "REAL NOT NULL DEFAULT 0",
        "costing_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for column, definition in receipt_item_migrations.items():
        if column not in receipt_item_columns:
            db.execute(
                f"ALTER TABLE goods_receipt_items ADD COLUMN {column} {definition}"
            )

    # Idempotent purchase-return accounting allocation fields.
    return_item_columns = {
        row["name"] for row in db.execute(
            "PRAGMA table_info(purchase_return_items)"
        ).fetchall()
    }
    return_item_migrations = {
        "original_purchase_item_id": "INTEGER",
        "inventory_unit_cost": "REAL NOT NULL DEFAULT 0",
        "supplier_credit_total": "REAL NOT NULL DEFAULT 0",
        "cost_variance": "REAL NOT NULL DEFAULT 0",
        "costing_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for column, definition in return_item_migrations.items():
        if column not in return_item_columns:
            db.execute(
                f"ALTER TABLE purchase_return_items ADD COLUMN {column} {definition}"
            )


def branch_id(db):
    row = db.execute(
        "SELECT id FROM branches WHERE is_active=1 ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="No active branch is configured.")
    return row["id"]


def next_number(db, table, column, prefix, branch):
    row = db.execute(
        f"SELECT {column} FROM {table} WHERE branch_id=? AND {column} LIKE ? ORDER BY id DESC LIMIT 1",
        (branch, prefix + "%")
    ).fetchone()
    number = 1
    if row:
        try:
            number = int(str(row[column]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            pass
    return prefix + f"{number:04d}"


def product_or_404(db, product_id):
    row = db.execute("""
        SELECT id, name, sku, purchase_price, gst_rate
        FROM products
        WHERE id=? AND COALESCE(is_active,1)=1
    """, (product_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found.")
    return row


class OrderItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(default=0, ge=0)
    gst_rate: float = Field(default=0, ge=0)


class OrderCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    order_date: Optional[str] = None
    expected_date: Optional[str] = None
    notes: Optional[str] = None
    items: list[OrderItem] = Field(min_length=1)


class ReceiptItem(BaseModel):
    product_id: int = Field(gt=0)
    purchase_order_item_id: Optional[int] = None
    received_quantity: float = Field(gt=0)
    accepted_quantity: float = Field(ge=0)
    rejected_quantity: float = Field(default=0, ge=0)
    unit_cost: float = Field(default=0, ge=0)


class ReceiptCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    purchase_order_id: Optional[int] = None
    receipt_date: Optional[str] = None
    notes: Optional[str] = None
    items: list[ReceiptItem] = Field(min_length=1)


class DirectPurchaseItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    gst_rate: float = Field(default=0, ge=0)
    discount_amount: float = Field(default=0, ge=0)


class DirectPurchaseCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    invoice_date: Optional[str] = None
    supplier_invoice_no: Optional[str] = None
    paid_amount: float = Field(default=0, ge=0)
    payment_method: Literal[
        "cash", "upi", "card", "bank_transfer", "cheque", "credit", "other"
    ] = "cash"
    notes: Optional[str] = None
    items: list[DirectPurchaseItem] = Field(min_length=1)


class ReceiptInvoiceItem(BaseModel):
    goods_receipt_item_id: int = Field(gt=0)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(gt=0)
    gst_rate: float = Field(default=0, ge=0)
    discount_amount: float = Field(default=0, ge=0)
    # Signed amount allocated to remaining inventory.
    # The unallocated variance is automatically posted to PPV.
    inventory_variance_allocation: float = 0


class ReceiptInvoiceCreate(BaseModel):
    goods_receipt_id: int = Field(gt=0)
    supplier_id: int = Field(gt=0)
    invoice_date: Optional[str] = None
    supplier_invoice_no: Optional[str] = None
    notes: Optional[str] = None
    items: list[ReceiptInvoiceItem] = Field(min_length=1)


class SupplierPaymentCreate(BaseModel):
    purchase_id: int = Field(gt=0)
    amount: float = Field(gt=0)
    payment_method: Literal[
        "cash", "upi", "card", "bank_transfer", "cheque", "credit", "other"
    ] = "cash"
    payment_date: Optional[str] = None
    reference_no: Optional[str] = None
    notes: Optional[str] = None


class ReturnItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0)
    unit_cost: float = Field(ge=0)


class ReturnCreate(BaseModel):
    supplier_id: int = Field(gt=0)
    purchase_id: int = Field(gt=0)
    return_date: Optional[str] = None
    reason: Optional[str] = None
    items: list[ReturnItem] = Field(min_length=1)


@router.get("/purchases/dashboard")
def purchase_dashboard(x_tenant_code: Optional[str] = Header(None)):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        data = {
            "purchase_orders": db.execute(
                "SELECT COUNT(*) FROM purchase_orders"
            ).fetchone()[0],
            "open_orders": db.execute(
                "SELECT COUNT(*) FROM purchase_orders WHERE status IN ('draft','sent','partially_received')"
            ).fetchone()[0],
            "goods_receipts": db.execute(
                "SELECT COUNT(*) FROM goods_receipts"
            ).fetchone()[0],
            "purchase_invoices": db.execute(
                "SELECT COUNT(*) FROM purchases"
            ).fetchone()[0],
            "purchase_value": db.execute(
                "SELECT COALESCE(SUM(grand_total),0) FROM purchases"
            ).fetchone()[0],
            "supplier_payable": db.execute(
                "SELECT COALESCE(SUM(CASE WHEN balance_amount > 0 THEN balance_amount ELSE 0 END),0) FROM purchases"
            ).fetchone()[0],
            "supplier_credit": db.execute(
                "SELECT COALESCE(SUM(CASE WHEN balance_amount < 0 THEN -balance_amount ELSE 0 END),0) FROM purchases"
            ).fetchone()[0],
            "returns": db.execute(
                "SELECT COUNT(*) FROM purchase_returns"
            ).fetchone()[0],
        }
    return data


@router.get("/purchases/lookups")
def purchase_lookups(x_tenant_code: Optional[str] = Header(None)):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        suppliers = db.execute("""
            SELECT id,name,phone,gstin
            FROM parties
            WHERE party_type IN ('supplier','both') AND COALESCE(is_active,1)=1
            ORDER BY name
        """).fetchall()
        products = db.execute("""
            SELECT id,sku,name,purchase_price,gst_rate
            FROM products WHERE COALESCE(is_active,1)=1 ORDER BY name
        """).fetchall()
    return {
        "suppliers": [dict(x) for x in suppliers],
        "products": [dict(x) for x in products],
    }


@router.get("/purchase-orders")
def list_purchase_orders(
    search: str = Query("", max_length=120),
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    term = f"%{search.strip()}%"
    with tenant_connection(code) as db:
        setup(db)
        rows = db.execute("""
            SELECT po.*, p.name AS supplier_name,
                   COUNT(i.id) AS item_count,
                   COALESCE(SUM(i.quantity),0) AS ordered_quantity,
                   COALESCE(SUM(i.received_quantity),0) AS received_quantity
            FROM purchase_orders po
            JOIN parties p ON p.id=po.supplier_id
            LEFT JOIN purchase_order_items i ON i.purchase_order_id=po.id
            WHERE (?='' OR po.po_no LIKE ? OR p.name LIKE ?)
            GROUP BY po.id ORDER BY po.id DESC
        """, (search.strip(), term, term)).fetchall()
    return {"orders": [dict(x) for x in rows]}


@router.post("/purchase-orders", status_code=201)
def create_purchase_order(
    payload: OrderCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        supplier = db.execute("""
            SELECT id FROM parties
            WHERE id=? AND party_type IN ('supplier','both') AND is_active=1
        """, (payload.supplier_id,)).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        branch = branch_id(db)
        db.execute("BEGIN IMMEDIATE")
        po_no = next_number(db, "purchase_orders", "po_no", "PO-", branch)
        cursor = db.execute("""
            INSERT INTO purchase_orders
            (po_no,supplier_id,branch_id,order_date,expected_date,notes)
            VALUES (?,?,?,?,?,?)
        """, (
            po_no, payload.supplier_id, branch,
            payload.order_date or datetime.now().date().isoformat(),
            payload.expected_date, payload.notes
        ))
        po_id = cursor.lastrowid
        for item in payload.items:
            product_or_404(db, item.product_id)
            db.execute("""
                INSERT INTO purchase_order_items
                (purchase_order_id,product_id,quantity,unit_cost,gst_rate)
                VALUES (?,?,?,?,?)
            """, (po_id,item.product_id,item.quantity,item.unit_cost,item.gst_rate))
        # Deliberately no stock_balances or stock_ledger update here.
    return {"message": "Purchase order created. Stock has not changed.", "id": po_id, "po_no": po_no}


@router.get("/purchase-orders/{order_id}")
def get_purchase_order(
    order_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        order = db.execute("""
            SELECT po.*,p.name supplier_name FROM purchase_orders po
            JOIN parties p ON p.id=po.supplier_id WHERE po.id=?
        """, (order_id,)).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Purchase order not found.")
        items = db.execute("""
            SELECT i.*,p.name product_name,p.sku
            FROM purchase_order_items i JOIN products p ON p.id=i.product_id
            WHERE i.purchase_order_id=? ORDER BY i.id
        """, (order_id,)).fetchall()
    result = dict(order)
    result["items"] = [dict(x) for x in items]
    return result


@router.post("/goods-receipts", status_code=201)
def create_goods_receipt(
    payload: ReceiptCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    for item in payload.items:
        if money(item.accepted_quantity + item.rejected_quantity) != money(item.received_quantity):
            raise HTTPException(
                status_code=400,
                detail="Accepted quantity plus rejected quantity must equal received quantity."
            )
    with tenant_connection(code) as db:
        setup(db)
        supplier = db.execute(
            "SELECT id FROM parties WHERE id=? AND party_type IN ('supplier','both')",
            (payload.supplier_id,)
        ).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        branch = branch_id(db)
        db.execute("BEGIN IMMEDIATE")
        po = None
        if payload.purchase_order_id:
            po = db.execute(
                "SELECT * FROM purchase_orders WHERE id=? AND supplier_id=? AND branch_id=?",
                (payload.purchase_order_id, payload.supplier_id, branch)
            ).fetchone()
            if not po:
                raise HTTPException(status_code=404, detail="Matching purchase order not found.")
            if po["status"] in ("received", "cancelled"):
                raise HTTPException(status_code=400, detail="This purchase order cannot receive more goods.")
        elif any(item.purchase_order_item_id is not None for item in payload.items):
            raise HTTPException(status_code=400, detail="A purchase order is required when selecting purchase order items.")

        receipt_no = next_number(db, "goods_receipts", "receipt_no", "GR-", branch)
        cursor = db.execute("""
            INSERT INTO goods_receipts
            (receipt_no,purchase_order_id,supplier_id,branch_id,receipt_date,notes)
            VALUES (?,?,?,?,?,?)
        """, (
            receipt_no,payload.purchase_order_id,payload.supplier_id,
            branch,payload.receipt_date or datetime.now().date().isoformat(),
            payload.notes
        ))
        receipt_id = cursor.lastrowid
        for item in payload.items:
            product_or_404(db, item.product_id)
            if item.purchase_order_item_id:
                po_item = db.execute("""
                    SELECT * FROM purchase_order_items
                    WHERE id=? AND purchase_order_id=?
                """, (item.purchase_order_item_id,payload.purchase_order_id)).fetchone()
                if not po_item or po_item["product_id"] != item.product_id:
                    raise HTTPException(status_code=400, detail="Invalid purchase order item.")
                reserved = db.execute("""
                    SELECT COALESCE(SUM(gri.received_quantity), 0)
                    FROM goods_receipt_items gri
                    JOIN goods_receipts gr ON gr.id=gri.goods_receipt_id
                    WHERE gri.purchase_order_item_id=?
                      AND gr.status='draft'
                """, (item.purchase_order_item_id,)).fetchone()[0]

                if (
                    po_item["received_quantity"]
                    + float(reserved)
                    + item.received_quantity
                    > po_item["quantity"] + 0.000001
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="Receipt exceeds the remaining ordered quantity, including other draft receipts."
                    )
            elif payload.purchase_order_id:
                raise HTTPException(status_code=400, detail="Every item in a purchase-order receipt must reference an item from that order.")
            db.execute("""
                INSERT INTO goods_receipt_items
                (goods_receipt_id,purchase_order_item_id,product_id,
                 received_quantity,accepted_quantity,rejected_quantity,unit_cost)
                VALUES (?,?,?,?,?,?,?)
            """, (
                receipt_id,item.purchase_order_item_id,item.product_id,
                item.received_quantity,item.accepted_quantity,
                item.rejected_quantity,item.unit_cost
            ))
    return {"message": "Goods receipt saved as draft. Stock has not changed.", "id": receipt_id, "receipt_no": receipt_no}


@router.get("/goods-receipts")
def list_goods_receipts(x_tenant_code: Optional[str] = Header(None)):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        rows = db.execute("""
            SELECT gr.*,p.name supplier_name,
                   COALESCE(SUM(i.received_quantity),0) received_quantity,
                   COALESCE(SUM(i.accepted_quantity),0) accepted_quantity
            FROM goods_receipts gr JOIN parties p ON p.id=gr.supplier_id
            LEFT JOIN goods_receipt_items i ON i.goods_receipt_id=gr.id
            GROUP BY gr.id ORDER BY gr.id DESC
        """).fetchall()
    return {"receipts": [dict(x) for x in rows]}


@router.get("/goods-receipts/{receipt_id}")
def get_goods_receipt_detail(
    receipt_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        receipt = db.execute("""
            SELECT gr.*, p.name AS supplier_name
            FROM goods_receipts gr
            JOIN parties p ON p.id=gr.supplier_id
            WHERE gr.id=?
        """, (receipt_id,)).fetchone()

        if not receipt:
            raise HTTPException(status_code=404, detail="Goods receipt not found.")

        rows = db.execute("""
            SELECT gri.*, pr.name AS product_name, pr.sku
            FROM goods_receipt_items gri
            JOIN products pr ON pr.id=gri.product_id
            WHERE gri.goods_receipt_id=?
            ORDER BY gri.id
        """, (receipt_id,)).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            accepted = float(item.get("accepted_quantity") or 0)
            invoiced = float(item.get("invoiced_quantity") or 0)
            item["remaining_quantity"] = max(0.0, accepted - invoiced)
            items.append(item)

    result = dict(receipt)
    result["items"] = items
    return result


@router.post("/goods-receipts/{receipt_id}/accept")
def accept_goods_receipt(
    receipt_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)

    with tenant_connection(code) as db:
        setup(db)

        # Finance setup uses schema scripts; run it before BEGIN IMMEDIATE.
        from .finance import (
            setup as finance_setup,
            post_journal,
            accounts_map,
        )
        from .wac_engine import (
            receive_inventory,
            WACError,
        )

        finance_setup(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")

        receipt = db.execute(
            "SELECT * FROM goods_receipts WHERE id=?", (receipt_id,)
        ).fetchone()

        if not receipt:
            raise HTTPException(status_code=404, detail="Goods receipt not found.")
        if receipt["status"] == "accepted":
            raise HTTPException(status_code=409, detail="Goods receipt was already accepted.")
        if receipt["status"] != "draft":
            raise HTTPException(status_code=400, detail="Only draft receipts can be accepted.")

        items = db.execute(
            "SELECT * FROM goods_receipt_items WHERE goods_receipt_id=? ORDER BY id",
            (receipt_id,)
        ).fetchall()

        if not items:
            raise HTTPException(status_code=400, detail="Receipt has no items.")

        if receipt["purchase_order_id"]:
            requested = {}
            for item in items:
                po_item_id = item["purchase_order_item_id"]
                if po_item_id is None:
                    raise HTTPException(
                        status_code=400,
                        detail="Purchase-order receipt contains an unlinked item."
                    )
                requested[po_item_id] = (
                    requested.get(po_item_id, 0)
                    + float(item["received_quantity"])
                )

            for po_item_id, requested_quantity in requested.items():
                po_item = db.execute("""
                    SELECT * FROM purchase_order_items
                    WHERE id=? AND purchase_order_id=?
                """, (po_item_id, receipt["purchase_order_id"])).fetchone()

                if not po_item:
                    raise HTTPException(
                        status_code=400,
                        detail="Receipt references an invalid purchase-order item."
                    )

                if (
                    float(po_item["received_quantity"]) + requested_quantity
                    > float(po_item["quantity"]) + 0.000001
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="Receipt exceeds the remaining ordered quantity."
                    )

        inventory_total = 0.0
        accepted_item_count = 0

        for item in items:
            accepted = money(item["accepted_quantity"])

            if accepted > 0:
                unit_cost = money(item["unit_cost"])

                if unit_cost <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Enter a positive unit cost for product "
                            f"{item['product_id']} before accepting this receipt."
                        )
                    )

                old = db.execute("""
                    SELECT quantity FROM stock_balances
                    WHERE branch_id=? AND product_id=?
                """, (receipt["branch_id"], item["product_id"])).fetchone()

                previous = float(old["quantity"]) if old else 0.0

                # If a WAC balance exists, its quantity must match physical stock.
                cost_balance = db.execute("""
                    SELECT physical_quantity
                    FROM inventory_cost_balances
                    WHERE branch_id=? AND product_id=?
                """, (receipt["branch_id"], item["product_id"])).fetchone()

                if cost_balance and abs(
                    float(cost_balance["physical_quantity"]) - previous
                ) > 0.000001:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Physical stock and verified cost quantity differ "
                            f"for product {item['product_id']}. Reconcile opening "
                            f"stock before accepting this receipt."
                        )
                    )

                movement_key = (
                    f"goods-receipt:{receipt_id}:item:{item['id']}"
                )

                try:
                    receive_inventory(
                        db,
                        movement_key=movement_key,
                        branch_id=receipt["branch_id"],
                        product_id=item["product_id"],
                        quantity=accepted,
                        unit_cost=unit_cost,
                        movement_type="purchase_receipt",
                        reference_type="goods_receipt",
                        reference_id=receipt_id,
                        reference_line_id=item["id"],
                        notes=receipt["receipt_no"],
                    )
                except WACError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Inventory costing could not be updated for "
                            f"product {item['product_id']}: {exc}"
                        )
                    )

                new_quantity = money(previous + accepted)

                db.execute("""
                    INSERT INTO stock_balances(branch_id,product_id,quantity)
                    VALUES (?,?,?)
                    ON CONFLICT(branch_id,product_id)
                    DO UPDATE SET
                        quantity=excluded.quantity,
                        updated_at=CURRENT_TIMESTAMP
                """, (
                    receipt["branch_id"],
                    item["product_id"],
                    new_quantity,
                ))

                db.execute("""
                    INSERT INTO stock_ledger
                    (branch_id,product_id,transaction_type,reference_type,
                     reference_id,quantity_in,quantity_out,balance_after,
                     unit_cost,notes)
                    VALUES (?, ?, 'purchase_receipt', 'goods_receipt',
                            ?, ?, 0, ?, ?, ?)
                """, (
                    receipt["branch_id"],
                    item["product_id"],
                    receipt_id,
                    accepted,
                    new_quantity,
                    unit_cost,
                    receipt["receipt_no"],
                ))

                inventory_total = money(
                    inventory_total + money(accepted * unit_cost)
                )
                accepted_item_count += 1

            if item["purchase_order_item_id"]:
                db.execute("""
                    UPDATE purchase_order_items
                    SET received_quantity=received_quantity+?
                    WHERE id=?
                """, (
                    item["received_quantity"],
                    item["purchase_order_item_id"],
                ))

        # Post one balanced Inventory / GRNI journal for the accepted goods.
        if inventory_total > 0:
            account_ids = accounts_map(db)
            inventory_account = account_ids.get("Inventory")
            grni_account = account_ids.get("Goods Received Not Invoiced")

            if not inventory_account or not grni_account:
                raise HTTPException(
                    status_code=500,
                    detail="Inventory or GRNI accounting account is missing."
                )

            try:
                post_journal(
                    db,
                    voucher_date=receipt["receipt_date"],
                    voucher_type="GOODS_RECEIPT",
                    narration=f"Goods receipt {receipt['receipt_no']} - GRNI",
                    source_type="goods_receipt",
                    source_id=receipt_id,
                    lines=[
                        {
                            "account_id": inventory_account,
                            "debit": inventory_total,
                            "credit": 0,
                            "narration": "Inventory received",
                        },
                        {
                            "account_id": grni_account,
                            "debit": 0,
                            "credit": inventory_total,
                            "narration": "Goods received not invoiced",
                        },
                    ],
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=f"Goods receipt accounting could not be posted: {exc}"
                )

        db.execute(
            "UPDATE goods_receipts SET status='accepted' WHERE id=?",
            (receipt_id,)
        )

        if receipt["purchase_order_id"]:
            remaining = db.execute("""
                SELECT COUNT(*) FROM purchase_order_items
                WHERE purchase_order_id=? AND received_quantity < quantity
            """, (receipt["purchase_order_id"],)).fetchone()[0]

            received = db.execute("""
                SELECT COUNT(*) FROM purchase_order_items
                WHERE purchase_order_id=? AND received_quantity > 0
            """, (receipt["purchase_order_id"],)).fetchone()[0]

            status = (
                "received" if remaining == 0
                else ("partially_received" if received else "sent")
            )

            db.execute(
                "UPDATE purchase_orders SET status=? WHERE id=?",
                (status, receipt["purchase_order_id"])
            )

    return {
        "message": (
            "Goods receipt accepted. Stock, weighted-average cost and "
            "GRNI accounting were updated."
        ),
        "id": receipt_id,
        "accepted_items": accepted_item_count,
        "inventory_value": inventory_total,
    }


@router.post("/purchases/direct", status_code=201)
def create_direct_purchase(
    payload: DirectPurchaseCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        from .finance import setup as finance_setup, post_journal, accounts_map
        finance_setup(db)
        db.commit()
        supplier = db.execute(
            "SELECT id,state_code FROM parties WHERE id=? AND party_type IN ('supplier','both') AND is_active=1",
            (payload.supplier_id,)
        ).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        branch = branch_id(db)
        gst_settings = db.execute(
            "SELECT state_code FROM gst_settings WHERE id=1"
        ).fetchone()
        business_state = str(
            (gst_settings["state_code"] if gst_settings else "") or ""
        ).strip()
        supplier_state = str(supplier["state_code"] or "").strip()

        # GST state codes must be valid two-digit Indian state codes.
        GST_STATE_CODES = {
            "01", "02", "03", "04", "05", "06", "07", "08", "09",
            "10", "11", "12", "13", "14", "15", "16", "17", "18",
            "19", "20", "21", "22", "23", "24", "26", "27", "29",
            "30", "31", "32", "33", "34", "35", "36", "37", "38",
            "97", "99",
        }

        if business_state not in GST_STATE_CODES:
            raise HTTPException(
                status_code=400,
                detail="Configure a valid 2-digit business GST state code before posting purchases."
            )

        if supplier_state not in GST_STATE_CODES:
            raise HTTPException(
                status_code=400,
                detail="Configure a valid 2-digit GST state code for this supplier before posting purchases."
            )

        intra_state = business_state == supplier_state

        calculated = []
        subtotal = discount_total = taxable_total = 0.0
        cgst_total = sgst_total = igst_total = tax_total = 0.0

        for item in payload.items:
            product = product_or_404(db,item.product_id)
            gross = money(item.quantity * item.unit_cost)
            discount = money(item.discount_amount)
            if discount > gross:
                raise HTTPException(status_code=400, detail="Line discount exceeds line value.")

            taxable = money(gross - discount)
            tax = money(taxable * item.gst_rate / 100)

            if intra_state:
                cgst = money(tax / 2)
                sgst = money(tax - cgst)
                igst = 0.0
            else:
                cgst = sgst = 0.0
                igst = tax

            calculated.append((
                item, product, taxable, tax, cgst, sgst, igst,
                money(taxable + tax)
            ))
            subtotal += gross
            discount_total += discount
            taxable_total += taxable
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst
            tax_total += tax

        subtotal = money(subtotal)
        discount_total = money(discount_total)
        taxable_total = money(taxable_total)
        cgst_total = money(cgst_total)
        sgst_total = money(sgst_total)
        igst_total = money(igst_total)
        tax_total = money(cgst_total + sgst_total + igst_total)
        grand_total = money(taxable_total + tax_total)
        paid = money(payload.paid_amount)
        if paid > grand_total:
            raise HTTPException(status_code=400, detail="Payment cannot exceed invoice total.")
        if paid > 0 and payload.payment_method not in ("cash", "upi", "card", "bank_transfer", "cheque"):
            raise HTTPException(status_code=400, detail="Select a valid payment method.")
        balance = money(grand_total-paid)
        invoice_no = next_number(db,"purchases","invoice_no","PINV-",branch)
        now = datetime.now().date().isoformat()
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute("""
            INSERT INTO purchases
            (invoice_no,supplier_id,branch_id,invoice_date,supplier_invoice_no,
             subtotal,discount_amount,taxable_amount,cgst,sgst,igst,total_tax,
             grand_total,paid_amount,balance_amount,status,notes,stock_posted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """, (
            invoice_no,payload.supplier_id,branch,
            payload.invoice_date or now,payload.supplier_invoice_no,
            subtotal,discount_total,taxable_total,
            cgst_total,sgst_total,igst_total,tax_total,
            grand_total,paid,balance,
            "paid" if balance == 0 else ("partial" if paid else "unpaid"),
            payload.notes
        ))
        purchase_id = cursor.lastrowid
        for item,product,taxable,tax,cgst,sgst,igst,line_total in calculated:
            db.execute("""
                INSERT INTO purchase_items
                (purchase_id,product_id,quantity,unit_cost,discount_amount,
                 gst_rate,taxable_amount,tax_amount,line_total)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                purchase_id,item.product_id,item.quantity,item.unit_cost,
                item.discount_amount,item.gst_rate,taxable,tax,line_total
            ))
            old = db.execute("""
                SELECT quantity FROM stock_balances
                WHERE branch_id=? AND product_id=?
            """, (branch,item.product_id)).fetchone()
            previous = float(old["quantity"]) if old else 0
            new = money(previous+item.quantity)
            db.execute("""
                INSERT INTO stock_balances(branch_id,product_id,quantity)
                VALUES (?,?,?)
                ON CONFLICT(branch_id,product_id)
                DO UPDATE SET quantity=excluded.quantity,updated_at=CURRENT_TIMESTAMP
            """, (branch,item.product_id,new))
            db.execute("""
                INSERT INTO stock_ledger
                (branch_id,product_id,transaction_type,reference_type,reference_id,
                 quantity_in,quantity_out,balance_after,unit_cost,notes)
                VALUES (?,?, 'direct_purchase','purchase',?,?,?, ?,?,?)
            """, (
                branch,item.product_id,purchase_id,item.quantity,0,new,
                item.unit_cost,invoice_no
            ))
            db.execute(
                "UPDATE products SET purchase_price=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (item.unit_cost,item.product_id)
            )
        if paid > 0:
            db.execute("""
                INSERT INTO payments
                (party_id,purchase_id,branch_id,payment_type,payment_method,
                 amount,payment_date,notes)
                VALUES (?,?,?,'payment',?,?,?,?)
            """, (
                payload.supplier_id,purchase_id,branch,payload.payment_method,
                paid,now,payload.notes
            ))

        # Post the purchase invoice to the general ledger.
        if grand_total > 0:
            account_ids = accounts_map(db)
            payment_account = "Cash" if payload.payment_method == "cash" else "Bank"

            required_accounts = [
                "Inventory", "Input CGST", "Input SGST",
                "Input IGST", "Accounts Payable"
            ]
            if paid > 0:
                required_accounts.append(payment_account)

            missing = [name for name in required_accounts if name not in account_ids]
            if missing:
                raise ValueError("Missing accounting accounts: " + ", ".join(missing))

            journal_lines = [
                {"account_id": account_ids["Inventory"], "debit": taxable_total, "credit": 0}
            ]

            if cgst_total > 0:
                journal_lines.append({
                    "account_id": account_ids["Input CGST"],
                    "debit": cgst_total, "credit": 0
                })
            if sgst_total > 0:
                journal_lines.append({
                    "account_id": account_ids["Input SGST"],
                    "debit": sgst_total, "credit": 0
                })
            if igst_total > 0:
                journal_lines.append({
                    "account_id": account_ids["Input IGST"],
                    "debit": igst_total, "credit": 0
                })
            if paid > 0:
                journal_lines.append({
                    "account_id": account_ids[payment_account],
                    "debit": 0, "credit": paid
                })
            if balance > 0:
                journal_lines.append({
                    "account_id": account_ids["Accounts Payable"],
                    "debit": 0, "credit": balance
                })

            post_journal(
                db,
                payload.invoice_date or now,
                "PURCHASE",
                "Purchase invoice " + str(invoice_no),
                "purchase_invoice",
                purchase_id,
                journal_lines,
            )
    return {
        "message": "Direct purchase invoice posted and stock updated.",
        "id": purchase_id,"invoice_no": invoice_no,
        "grand_total": grand_total,"paid_amount": paid,"balance_amount": balance
    }


@router.post("/purchases/from-goods-receipt")
def create_purchase_from_goods_receipt(
    payload: ReceiptInvoiceCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    """
    Post a supplier invoice against accepted goods.

    This route does not receive stock again. It clears GRNI, records GST/AP,
    and allocates the invoice-vs-receipt price difference between Inventory
    and Purchase Price Variance (PPV).
    """
    code = tenant_code(x_tenant_code)

    with tenant_connection(code) as db:
        setup(db)

        from .finance import (
            setup as finance_setup,
            post_journal,
            accounts_map,
        )
        from .wac_engine import adjust_inventory_value, WACError

        finance_setup(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")

        receipt = db.execute("""
            SELECT *
            FROM goods_receipts
            WHERE id=? AND supplier_id=?
        """, (payload.goods_receipt_id, payload.supplier_id)).fetchone()

        if not receipt:
            raise HTTPException(
                status_code=404,
                detail="Goods receipt not found for this supplier."
            )
        if receipt["status"] != "accepted":
            raise HTTPException(
                status_code=400,
                detail="Only accepted goods receipts can be invoiced."
            )

        supplier = db.execute("""
            SELECT id, state_code
            FROM parties
            WHERE id=? AND party_type IN ('supplier','both') AND is_active=1
        """, (payload.supplier_id,)).fetchone()

        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found.")

        gst_settings = db.execute(
            "SELECT state_code FROM gst_settings WHERE id=1"
        ).fetchone()

        business_state = str(
            (gst_settings["state_code"] if gst_settings else "") or ""
        ).strip()
        supplier_state = str(supplier["state_code"] or "").strip()

        valid_states = {
            "01", "02", "03", "04", "05", "06", "07", "08", "09",
            "10", "11", "12", "13", "14", "15", "16", "17", "18",
            "19", "20", "21", "22", "23", "24", "26", "27", "29",
            "30", "31", "32", "33", "34", "35", "36", "37", "38",
            "97", "99",
        }

        if business_state not in valid_states:
            raise HTTPException(
                status_code=400,
                detail="Configure a valid 2-digit business GST state code."
            )
        if supplier_state not in valid_states:
            raise HTTPException(
                status_code=400,
                detail="Configure a valid 2-digit supplier GST state code."
            )

        intra_state = business_state == supplier_state
        seen_receipt_lines = set()
        calculated = []

        subtotal = discount_total = taxable_total = 0.0
        cgst_total = sgst_total = igst_total = 0.0
        grni_total = inventory_allocation_total = ppv_total = 0.0

        for item in payload.items:
            if item.goods_receipt_item_id in seen_receipt_lines:
                raise HTTPException(
                    status_code=400,
                    detail="A receipt line may appear only once per invoice."
                )
            seen_receipt_lines.add(item.goods_receipt_item_id)

            receipt_line = db.execute("""
                SELECT gri.*, gr.branch_id, gr.receipt_no, gr.status
                FROM goods_receipt_items gri
                JOIN goods_receipts gr ON gr.id=gri.goods_receipt_id
                WHERE gri.id=? AND gr.id=? AND gr.supplier_id=?
            """, (
                item.goods_receipt_item_id,
                payload.goods_receipt_id,
                payload.supplier_id,
            )).fetchone()

            if not receipt_line or receipt_line["status"] != "accepted":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Receipt line {item.goods_receipt_item_id} "
                        "does not belong to this accepted receipt."
                    )
                )

            accepted_qty = money(receipt_line["accepted_quantity"])
            receipt_cost = money(receipt_line["unit_cost"])

            if accepted_qty <= 0 or receipt_cost <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Only accepted, positively costed receipt quantities can be invoiced."
                )

            previously_invoiced = db.execute("""
                SELECT COALESCE(SUM(quantity),0)
                FROM purchase_receipt_invoice_lines
                WHERE goods_receipt_item_id=?
            """, (item.goods_receipt_item_id,)).fetchone()[0]

            available_qty = money(accepted_qty - float(previously_invoiced))
            quantity = money(item.quantity)

            if quantity > available_qty + 0.000001:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Invoice quantity for receipt line "
                        f"{item.goods_receipt_item_id} exceeds its uninvoiced "
                        f"accepted quantity ({available_qty})."
                    )
                )

            invoice_unit_cost = money(item.unit_cost)
            gross = money(quantity * invoice_unit_cost)
            discount = money(item.discount_amount)

            if discount > gross:
                raise HTTPException(
                    status_code=400,
                    detail="Line discount exceeds line value."
                )

            taxable = money(gross - discount)
            tax = money(taxable * item.gst_rate / 100)

            if intra_state:
                cgst = money(tax / 2)
                sgst = money(tax - cgst)
                igst = 0.0
            else:
                cgst = sgst = 0.0
                igst = tax

            receipt_value = money(quantity * receipt_cost)
            variance = money(taxable - receipt_value)
            inventory_allocation = money(
                item.inventory_variance_allocation
            )

            # Allocation must have the same sign as the variance and cannot
            # exceed it. PPV receives the remaining amount.
            if (
                (variance > 0 and (
                    inventory_allocation < 0
                    or inventory_allocation > variance
                ))
                or (variance < 0 and (
                    inventory_allocation > 0
                    or inventory_allocation < variance
                ))
                or (variance == 0 and inventory_allocation != 0)
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Inventory variance allocation for receipt line "
                        f"{item.goods_receipt_item_id} must be between zero "
                        f"and the total variance, with the same sign."
                    )
                )

            ppv = money(variance - inventory_allocation)

            calculated.append({
                "item": item,
                "receipt_line": receipt_line,
                "quantity": quantity,
                "receipt_cost": receipt_cost,
                "invoice_cost": invoice_unit_cost,
                "gross": gross,
                "discount": discount,
                "taxable": taxable,
                "tax": tax,
                "cgst": cgst,
                "sgst": sgst,
                "igst": igst,
                "line_total": money(taxable + tax),
                "receipt_value": receipt_value,
                "inventory_allocation": inventory_allocation,
                "ppv": ppv,
            })

            subtotal += gross
            discount_total += discount
            taxable_total += taxable
            cgst_total += cgst
            sgst_total += sgst
            igst_total += igst
            grni_total += receipt_value
            inventory_allocation_total += inventory_allocation
            ppv_total += ppv

        subtotal = money(subtotal)
        discount_total = money(discount_total)
        taxable_total = money(taxable_total)
        cgst_total = money(cgst_total)
        sgst_total = money(sgst_total)
        igst_total = money(igst_total)
        tax_total = money(cgst_total + sgst_total + igst_total)
        grni_total = money(grni_total)
        inventory_allocation_total = money(inventory_allocation_total)
        ppv_total = money(ppv_total)
        grand_total = money(taxable_total + tax_total)

        if grand_total <= 0:
            raise HTTPException(
                status_code=400,
                detail="Supplier invoice total must be greater than zero."
            )

        branch = receipt["branch_id"]
        invoice_date = (
            payload.invoice_date or datetime.now().date().isoformat()
        )
        invoice_no = next_number(
            db, "purchases", "invoice_no", "PINV-", branch
        )

        cursor = db.execute("""
            INSERT INTO purchases
            (invoice_no,supplier_id,branch_id,invoice_date,supplier_invoice_no,
             subtotal,discount_amount,taxable_amount,cgst,sgst,igst,total_tax,
             round_off,grand_total,paid_amount,balance_amount,status,notes,stock_posted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """, (
            invoice_no,
            payload.supplier_id,
            branch,
            invoice_date,
            payload.supplier_invoice_no,
            subtotal,
            discount_total,
            taxable_total,
            cgst_total,
            sgst_total,
            igst_total,
            tax_total,
            0,
            grand_total,
            0,
            grand_total,
            "unpaid",
            payload.notes,
        ))
        purchase_id = cursor.lastrowid

        for entry in calculated:
            item = entry["item"]
            receipt_line = entry["receipt_line"]

            purchase_item_cursor = db.execute("""
                INSERT INTO purchase_items
                (purchase_id,product_id,quantity,unit_cost,discount_amount,
                 gst_rate,taxable_amount,tax_amount,line_total)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                purchase_id,
                receipt_line["product_id"],
                entry["quantity"],
                entry["invoice_cost"],
                entry["discount"],
                item.gst_rate,
                entry["taxable"],
                entry["tax"],
                entry["line_total"],
            ))

            allocation_cursor = db.execute("""
                INSERT INTO purchase_receipt_invoice_lines
                (purchase_id,purchase_item_id,goods_receipt_item_id,quantity,
                 receipt_unit_cost,invoice_unit_cost,inventory_variance_allocation)
                VALUES (?,?,?,?,?,?,?)
            """, (
                purchase_id,
                purchase_item_cursor.lastrowid,
                item.goods_receipt_item_id,
                entry["quantity"],
                entry["receipt_cost"],
                entry["invoice_cost"],
                entry["inventory_allocation"],
            ))

            # Keep purchase-item summary fields synchronized with the
            # detailed receipt allocation record.
            full_cost_variance = money(
                entry["taxable"] - entry["receipt_value"]
            )

            db.execute("""
                UPDATE purchase_items
                SET receipt_allocated_quantity=?,
                    final_cost_variance=?,
                    costing_status='costed'
                WHERE id=? AND purchase_id=?
            """, (
                entry["quantity"],
                full_cost_variance,
                purchase_item_cursor.lastrowid,
                purchase_id,
            ))

            # Accumulate invoiced quantity across multiple supplier invoices.
            # A receipt line becomes costed only when all accepted quantity
            # has been invoiced.
            db.execute("""
                UPDATE goods_receipt_items
                SET invoiced_quantity=invoiced_quantity+?,
                    costing_status=CASE
                        WHEN invoiced_quantity+? >= accepted_quantity-0.000001
                        THEN 'costed'
                        ELSE 'pending'
                    END
                WHERE id=?
            """, (
                entry["quantity"],
                entry["quantity"],
                item.goods_receipt_item_id,
            ))

            # Revalue only the explicitly allocated amount. Do not alter
            # physical stock or add the received quantity a second time.
            if entry["inventory_allocation"] != 0:
                product_id = receipt_line["product_id"]
                stock = db.execute("""
                    SELECT quantity FROM stock_balances
                    WHERE branch_id=? AND product_id=?
                """, (branch, product_id)).fetchone()

                cost_balance = db.execute("""
                    SELECT physical_quantity
                    FROM inventory_cost_balances
                    WHERE branch_id=? AND product_id=?
                """, (branch, product_id)).fetchone()

                if not stock or not cost_balance:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot revalue product {product_id}: "
                            "verified WAC and physical stock balances are required."
                        )
                    )

                if abs(
                    float(stock["quantity"])
                    - float(cost_balance["physical_quantity"])
                ) > 0.000001:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Cannot revalue product {product_id}: "
                            "physical stock and WAC quantities do not match."
                        )
                    )

                try:
                    adjust_inventory_value(
                        db,
                        movement_key=(
                            f"receipt-invoice:{purchase_id}:"
                            f"allocation:{allocation_cursor.lastrowid}"
                        ),
                        branch_id=branch,
                        product_id=product_id,
                        value_change=entry["inventory_allocation"],
                        reason=f"Supplier invoice price variance {invoice_no}",
                        reference_type="purchase_invoice",
                        reference_id=purchase_id,
                        reference_line_id=allocation_cursor.lastrowid,
                    )
                except WACError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Inventory revaluation failed for product {product_id}: {exc}"
                    )

        # Every line on this invoice is linked to an accepted receipt.
        # Record the invoice-level allocation and costing completion.
        db.execute("""
            UPDATE purchases
            SET receipt_allocation_status='complete',
                inventory_cost_status='costed'
            WHERE id=?
        """, (purchase_id,))

        account_ids = accounts_map(db)
        required = [
            "Inventory",
            "Goods Received Not Invoiced",
            "Purchase Price Variance",
            "Input CGST",
            "Input SGST",
            "Input IGST",
            "Accounts Payable",
        ]
        missing = [name for name in required if name not in account_ids]
        if missing:
            raise HTTPException(
                status_code=500,
                detail="Missing accounting accounts: " + ", ".join(missing)
            )

        journal_lines = [
            {
                "account_id": account_ids["Goods Received Not Invoiced"],
                "debit": grni_total,
                "credit": 0,
                "narration": "Clear goods received not invoiced",
            },
        ]

        if inventory_allocation_total > 0:
            journal_lines.append({
                "account_id": account_ids["Inventory"],
                "debit": inventory_allocation_total,
                "credit": 0,
                "narration": "Inventory price variance allocation",
            })
        elif inventory_allocation_total < 0:
            journal_lines.append({
                "account_id": account_ids["Inventory"],
                "debit": 0,
                "credit": abs(inventory_allocation_total),
                "narration": "Inventory price variance allocation",
            })

        if ppv_total > 0:
            journal_lines.append({
                "account_id": account_ids["Purchase Price Variance"],
                "debit": ppv_total,
                "credit": 0,
                "narration": "Unallocated purchase price variance",
            })
        elif ppv_total < 0:
            journal_lines.append({
                "account_id": account_ids["Purchase Price Variance"],
                "debit": 0,
                "credit": abs(ppv_total),
                "narration": "Unallocated purchase price variance",
            })

        for name, amount in (
            ("Input CGST", cgst_total),
            ("Input SGST", sgst_total),
            ("Input IGST", igst_total),
        ):
            if amount > 0:
                journal_lines.append({
                    "account_id": account_ids[name],
                    "debit": amount,
                    "credit": 0,
                    "narration": name,
                })

        journal_lines.append({
            "account_id": account_ids["Accounts Payable"],
            "debit": 0,
            "credit": grand_total,
            "narration": "Supplier invoice payable",
        })

        try:
            post_journal(
                db,
                invoice_date,
                "PURCHASE_INVOICE_GRNI",
                f"Supplier invoice {invoice_no} against {receipt['receipt_no']}",
                "purchase_invoice",
                purchase_id,
                journal_lines,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Supplier invoice accounting could not be posted: {exc}"
            )

    return {
        "message": (
            "Supplier invoice posted against accepted goods. "
            "GRNI cleared, GST and Accounts Payable recorded. "
            "Stock quantity was not increased again."
        ),
        "id": purchase_id,
        "invoice_no": invoice_no,
        "goods_receipt_id": payload.goods_receipt_id,
        "grni_cleared": grni_total,
        "taxable_amount": taxable_total,
        "gst_amount": tax_total,
        "inventory_variance_allocation": inventory_allocation_total,
        "purchase_price_variance": ppv_total,
        "grand_total": grand_total,
        "balance_amount": grand_total,
    }


@router.get("/purchases")
def list_purchases(
    search: str = Query("", max_length=120),
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    term = f"%{search.strip()}%"
    with tenant_connection(code) as db:
        setup(db)
        rows = db.execute("""
            SELECT pu.*,p.name supplier_name
            FROM purchases pu JOIN parties p ON p.id=pu.supplier_id
            WHERE (?='' OR pu.invoice_no LIKE ? OR pu.supplier_invoice_no LIKE ? OR p.name LIKE ?)
            ORDER BY pu.id DESC LIMIT 500
        """, (search.strip(),term,term,term)).fetchall()
    return {"purchases":[dict(x) for x in rows]}


@router.post("/purchases/payments", status_code=201)
def add_supplier_payment(
    payload: SupplierPaymentCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        from .finance import setup as finance_setup, post_journal, accounts_map
        finance_setup(db)
        db.commit()
        if payload.payment_method not in ("cash", "upi", "card", "bank_transfer", "cheque"):
            raise HTTPException(status_code=400, detail="Select a valid supplier payment method.")
        db.execute("BEGIN IMMEDIATE")
        purchase = db.execute(
            "SELECT * FROM purchases WHERE id=?", (payload.purchase_id,)
        ).fetchone()
        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase invoice not found.")
        outstanding = money(purchase["balance_amount"])
        if outstanding <= 0:
            raise HTTPException(
                status_code=400,
                detail="This invoice has no payable balance. Any negative balance is supplier credit."
            )
        if money(payload.amount) > outstanding:
            raise HTTPException(status_code=400, detail="Payment exceeds outstanding balance.")
        branch = purchase["branch_id"]
        payment_date = payload.payment_date or datetime.now().date().isoformat()
        new_paid = money(purchase["paid_amount"]+payload.amount)
        new_balance = money(purchase["balance_amount"]-payload.amount)
        payment_cursor = db.execute("""
            INSERT INTO payments
            (party_id,purchase_id,branch_id,payment_type,payment_method,
             amount,reference_no,payment_date,notes)
            VALUES (?,?,?,'payment',?,?,?,?,?)
        """, (
            purchase["supplier_id"],purchase["id"],branch,
            payload.payment_method,payload.amount,payload.reference_no,
            payment_date,
            payload.notes
        ))
        db.execute("""
            UPDATE purchases SET paid_amount=?,balance_amount=?,status=?
            WHERE id=?
        """, (
            new_paid,new_balance,
            "paid" if new_balance == 0 else "partial",
            purchase["id"]
        ))

        # Post the supplier payment to the general ledger.
        account_ids = accounts_map(db)
        payment_account = "Cash" if payload.payment_method == "cash" else "Bank"
        missing = [
            name for name in ("Accounts Payable", payment_account)
            if name not in account_ids
        ]
        if missing:
            raise ValueError("Missing accounting accounts: " + ", ".join(missing))

        payment_amount = money(payload.amount)
        post_journal(
            db,
            payment_date,
            "PAYMENT",
            "Supplier payment for purchase invoice " + str(purchase["id"]),
            "supplier_payment",
            payment_cursor.lastrowid,
            [
                {
                    "account_id": account_ids["Accounts Payable"],
                    "debit": payment_amount,
                    "credit": 0,
                },
                {
                    "account_id": account_ids[payment_account],
                    "debit": 0,
                    "credit": payment_amount,
                },
            ],
        )
    return {"message":"Supplier payment recorded.","paid_amount":new_paid,"balance_amount":new_balance}


@router.post("/purchase-returns", status_code=201)
def create_purchase_return(
    payload: ReturnCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        db.execute("BEGIN IMMEDIATE")

        purchase = db.execute("""
            SELECT * FROM purchases WHERE id=?
        """, (payload.purchase_id,)).fetchone()

        if not purchase or purchase["supplier_id"] != payload.supplier_id:
            raise HTTPException(
                status_code=404,
                detail="Related purchase invoice not found for this supplier."
            )

        branch = purchase["branch_id"]
        return_no = next_number(db, "purchase_returns", "return_no", "PR-", branch)
        cursor = db.execute("""
            INSERT INTO purchase_returns
            (return_no,purchase_id,supplier_id,branch_id,return_date,reason)
            VALUES (?,?,?,?,?,?)
        """, (
            return_no, payload.purchase_id, payload.supplier_id, branch,
            payload.return_date or datetime.now().date().isoformat(),
            payload.reason
        ))
        return_id = cursor.lastrowid

        # Allocate each requested product quantity to its original invoice
        # lines. Draft returns reserve quantities too, preventing duplicate drafts.
        for item in payload.items:
            product_or_404(db, item.product_id)

            source_lines = db.execute("""
                SELECT * FROM purchase_items
                WHERE purchase_id=? AND product_id=?
                ORDER BY id
            """, (payload.purchase_id, item.product_id)).fetchall()

            if not source_lines:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product ID {item.product_id} is not on the selected invoice."
                )

            legacy = db.execute("""
                SELECT COALESCE(SUM(ri.quantity),0) AS quantity
                FROM purchase_return_items ri
                JOIN purchase_returns r ON r.id=ri.purchase_return_id
                WHERE r.purchase_id=? AND r.status IN ('draft','posted')
                  AND ri.product_id=? AND ri.original_purchase_item_id IS NULL
            """, (payload.purchase_id, item.product_id)).fetchone()
            legacy_remaining = float(legacy["quantity"] or 0)
            quantity_left = float(item.quantity)

            for source in source_lines:
                allocated = db.execute("""
                    SELECT COALESCE(SUM(quantity),0) AS quantity
                    FROM purchase_return_items
                    WHERE original_purchase_item_id=?
                """, (source["id"],)).fetchone()
                already_allocated = float(allocated["quantity"] or 0)

                source_quantity = float(source["quantity"] or 0)
                # Older returns without source-line references are consumed
                # against invoice lines in their original order.
                legacy_for_line = min(
                    legacy_remaining,
                    max(0.0, source_quantity - already_allocated)
                )
                legacy_remaining -= legacy_for_line
                available = max(
                    0.0,
                    source_quantity - already_allocated - legacy_for_line
                )
                take = min(quantity_left, available)

                if take <= 0.000001:
                    continue

                source_unit_cost = float(source["unit_cost"] or 0)
                source_taxable = float(source["taxable_amount"] or 0)
                inventory_unit_cost = (
                    source_taxable / source_quantity
                    if source_quantity > 0 and source_taxable > 0
                    else source_unit_cost
                )

                db.execute("""
                    INSERT INTO purchase_return_items
                    (purchase_return_id,product_id,quantity,unit_cost,
                     original_purchase_item_id,inventory_unit_cost,
                     supplier_credit_total,cost_variance,costing_status)
                    VALUES (?,?,?,?,?,?,0,0,'invoice_cost')
                """, (
                    return_id, item.product_id, take, source_unit_cost,
                    source["id"], inventory_unit_cost
                ))
                quantity_left -= take

                if quantity_left <= 0.000001:
                    break

            if quantity_left > 0.000001:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Return quantity exceeds the remaining quantity on "
                        f"purchase invoice {purchase['invoice_no']} for product "
                        f"ID {item.product_id}."
                    )
                )

    return {
        "message": "Purchase return saved as draft. Original invoice quantities are reserved.",
        "id": return_id,
        "return_no": return_no
    }


@router.post("/purchase-returns/{return_id}/post")
def post_purchase_return(
    return_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        from .finance import setup as finance_setup, post_journal, accounts_map

        finance_setup(db)
        db.commit()
        db.execute("BEGIN IMMEDIATE")

        record = db.execute(
            "SELECT * FROM purchase_returns WHERE id=?", (return_id,)
        ).fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="Purchase return not found.")
        if record["status"] == "posted":
            raise HTTPException(status_code=409, detail="Return already posted.")
        if not record["purchase_id"]:
            raise HTTPException(
                status_code=400,
                detail="A purchase return must be linked to its original invoice."
            )

        purchase = db.execute("""
            SELECT * FROM purchases WHERE id=?
        """, (record["purchase_id"],)).fetchone()

        if (
            not purchase
            or purchase["supplier_id"] != record["supplier_id"]
            or purchase["branch_id"] != record["branch_id"]
        ):
            raise HTTPException(
                status_code=400,
                detail="The linked purchase invoice does not match this return."
            )

        items = db.execute("""
            SELECT ri.*, pi.quantity AS source_quantity,
                   pi.unit_cost AS source_unit_cost,
                   pi.discount_amount AS source_discount,
                   pi.gst_rate AS source_gst_rate,
                   pi.taxable_amount AS source_taxable,
                   pi.tax_amount AS source_tax
            FROM purchase_return_items ri
            LEFT JOIN purchase_items pi
              ON pi.id=ri.original_purchase_item_id
            WHERE ri.purchase_return_id=?
            ORDER BY ri.id
        """, (return_id,)).fetchall()

        if not items:
            raise HTTPException(status_code=400, detail="Return has no items.")

        total_taxable = 0.0
        total_input_tax = 0.0
        stock_quantities = {}

        for item in items:
            if item["original_purchase_item_id"] is None or not item["source_quantity"]:
                raise HTTPException(
                    status_code=400,
                    detail="A return line is missing its original purchase invoice allocation."
                )

            source_quantity = float(item["source_quantity"])
            return_quantity = float(item["quantity"])
            if return_quantity > source_quantity + 0.000001:
                raise HTTPException(
                    status_code=400,
                    detail="Return quantity exceeds its original purchase line."
                )

            taxable_source = float(item["source_taxable"] or 0)
            if taxable_source > 0:
                taxable = money(taxable_source * return_quantity / source_quantity)
            else:
                gross_base = (
                    float(item["source_unit_cost"] or 0) * source_quantity
                    - float(item["source_discount"] or 0)
                )
                taxable = money(max(0, gross_base) * return_quantity / source_quantity)

            tax_source = float(item["source_tax"] or 0)
            if tax_source > 0:
                input_tax = money(tax_source * return_quantity / source_quantity)
            else:
                input_tax = money(
                    taxable * float(item["source_gst_rate"] or 0) / 100
                )

            total_taxable = money(total_taxable + taxable)
            total_input_tax = money(total_input_tax + input_tax)
            stock_quantities[item["product_id"]] = (
                stock_quantities.get(item["product_id"], 0.0) + return_quantity
            )

        return_total = money(total_taxable + total_input_tax)
        if return_total <= 0:
            raise HTTPException(
                status_code=400,
                detail="The calculated supplier credit is zero; this return cannot be posted."
            )

        # Verify stock availability before changing any quantities.
        stock_rows = {}
        for product_id, quantity in stock_quantities.items():
            stock = db.execute("""
                SELECT quantity FROM stock_balances
                WHERE branch_id=? AND product_id=?
            """, (record["branch_id"], product_id)).fetchone()
            available = float(stock["quantity"]) if stock else 0.0
            if quantity > available + 0.000001:
                raise HTTPException(
                    status_code=400,
                    detail=f"Return quantity exceeds available stock for product ID {product_id}."
                )
            stock_rows[product_id] = available

        # Reverse the GST using the tax split recorded on the original invoice.
        original_cgst = money(purchase["cgst"] or 0)
        original_sgst = money(purchase["sgst"] or 0)
        original_igst = money(purchase["igst"] or 0)

        reverse_igst = 0.0
        reverse_cgst = 0.0
        reverse_sgst = 0.0

        if total_input_tax > 0:
            if original_igst > 0:
                reverse_igst = total_input_tax
            elif original_cgst + original_sgst > 0:
                reverse_cgst = money(
                    total_input_tax * original_cgst /
                    (original_cgst + original_sgst)
                )
                reverse_sgst = money(total_input_tax - reverse_cgst)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Original invoice GST split is unavailable; return was not posted."
                )

        account_ids = accounts_map(db)
        required_accounts = ["Accounts Payable", "Inventory"]
        if reverse_cgst > 0:
            required_accounts.append("Input CGST")
        if reverse_sgst > 0:
            required_accounts.append("Input SGST")
        if reverse_igst > 0:
            required_accounts.append("Input IGST")

        missing = [name for name in required_accounts if name not in account_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="Missing accounting accounts: " + ", ".join(missing)
            )

        journal_lines = [{
            "account_id": account_ids["Accounts Payable"],
            "debit": return_total,
            "credit": 0,
            "narration": "Supplier credit for purchase return"
        }, {
            "account_id": account_ids["Inventory"],
            "debit": 0,
            "credit": total_taxable,
            "narration": "Inventory returned to supplier"
        }]

        if reverse_cgst > 0:
            journal_lines.append({
                "account_id": account_ids["Input CGST"],
                "debit": 0,
                "credit": reverse_cgst,
                "narration": "Reverse input CGST on purchase return"
            })
        if reverse_sgst > 0:
            journal_lines.append({
                "account_id": account_ids["Input SGST"],
                "debit": 0,
                "credit": reverse_sgst,
                "narration": "Reverse input SGST on purchase return"
            })
        if reverse_igst > 0:
            journal_lines.append({
                "account_id": account_ids["Input IGST"],
                "debit": 0,
                "credit": reverse_igst,
                "narration": "Reverse input IGST on purchase return"
            })

        # Supplier credit reduces the invoice balance. A negative balance
        # represents credit due from the supplier; it is not a cash refund.
        new_balance = money(float(purchase["balance_amount"] or 0) - return_total)
        paid_amount = money(purchase["paid_amount"] or 0)
        if new_balance < 0:
            new_status = "credit"
        elif new_balance == 0:
            new_status = "paid"
        elif paid_amount > 0:
            new_status = "partial"
        else:
            new_status = "unpaid"

        for product_id, quantity in stock_quantities.items():
            remaining = money(stock_rows[product_id] - quantity)
            db.execute("""
                UPDATE stock_balances
                SET quantity=?, updated_at=CURRENT_TIMESTAMP
                WHERE branch_id=? AND product_id=?
            """, (remaining, record["branch_id"], product_id))

            cost_total = 0.0
            cost_quantity = 0.0
            for item in items:
                if item["product_id"] == product_id:
                    source_qty = float(item["source_quantity"])
                    source_taxable = float(item["source_taxable"] or 0)
                    source_cost = (
                        source_taxable / source_qty
                        if source_taxable > 0 and source_qty > 0
                        else float(item["source_unit_cost"] or 0)
                    )
                    cost_total += source_cost * float(item["quantity"])
                    cost_quantity += float(item["quantity"])

            average_cost = (
                money(cost_total / cost_quantity) if cost_quantity else 0
            )
            db.execute("""
                INSERT INTO stock_ledger
                (branch_id,product_id,transaction_type,reference_type,reference_id,
                 quantity_in,quantity_out,balance_after,unit_cost,notes)
                VALUES (?,?, 'purchase_return','purchase_return',?,0,?,?,?,?)
            """, (
                record["branch_id"], product_id, return_id,
                quantity, remaining, average_cost, record["return_no"]
            ))

        db.execute("""
            UPDATE purchases
            SET balance_amount=?, status=?
            WHERE id=?
        """, (new_balance, new_status, purchase["id"]))

        post_journal(
            db,
            record["return_date"],
            "PURCHASE_RETURN",
            "Supplier purchase return " + str(record["return_no"]),
            "purchase_return",
            return_id,
            journal_lines
        )

        db.execute(
            "UPDATE purchase_returns SET status='posted' WHERE id=?",
            (return_id,)
        )

    return {
        "message": "Purchase return posted. Stock reduced, GST reversed and supplier credit recorded.",
        "return_id": return_id,
        "supplier_credit": return_total,
        "taxable_value": total_taxable,
        "input_gst_reversed": total_input_tax,
        "invoice_balance": new_balance,
        "invoice_status": new_status
    }


@router.get("/purchase-reports")
def purchase_reports(x_tenant_code: Optional[str] = Header(None)):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        monthly = db.execute("""
            SELECT substr(invoice_date,1,7) AS month,
                   COUNT(*) AS invoices,
                   COALESCE(SUM(grand_total),0) AS total,
                   COALESCE(SUM(paid_amount),0) AS paid,
                   COALESCE(SUM(CASE WHEN balance_amount > 0 THEN balance_amount ELSE 0 END),0) AS outstanding,
                   COALESCE(SUM(CASE WHEN balance_amount < 0 THEN -balance_amount ELSE 0 END),0) AS supplier_credit
            FROM purchases GROUP BY substr(invoice_date,1,7)
            ORDER BY month DESC LIMIT 24
        """).fetchall()
        suppliers = db.execute("""
            SELECT p.id,p.name,
                   COUNT(pu.id) invoices,
                   COALESCE(SUM(pu.grand_total),0) purchase_value,
                   COALESCE(SUM(CASE WHEN pu.balance_amount > 0 THEN pu.balance_amount ELSE 0 END),0) outstanding,
                   COALESCE(SUM(CASE WHEN pu.balance_amount < 0 THEN -pu.balance_amount ELSE 0 END),0) supplier_credit
            FROM parties p LEFT JOIN purchases pu ON pu.supplier_id=p.id
            WHERE p.party_type IN ('supplier','both')
            GROUP BY p.id ORDER BY purchase_value DESC
        """).fetchall()
    return {
        "monthly":[dict(x) for x in monthly],
        "suppliers":[dict(x) for x in suppliers]
    }
