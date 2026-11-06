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
    purchase_id: Optional[int] = None
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
                "SELECT COALESCE(SUM(balance_amount),0) FROM purchases"
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


@router.post("/goods-receipts/{receipt_id}/accept")
def accept_goods_receipt(
    receipt_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
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
            "SELECT * FROM goods_receipt_items WHERE goods_receipt_id=?",
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
                    requested.get(po_item_id, 0) + float(item["received_quantity"])
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

        for item in items:
            accepted = money(item["accepted_quantity"])
            if accepted > 0:
                old = db.execute("""
                    SELECT quantity FROM stock_balances
                    WHERE branch_id=? AND product_id=?
                """, (receipt["branch_id"],item["product_id"])).fetchone()
                previous = float(old["quantity"]) if old else 0
                new = money(previous + accepted)
                db.execute("""
                    INSERT INTO stock_balances(branch_id,product_id,quantity)
                    VALUES (?,?,?)
                    ON CONFLICT(branch_id,product_id)
                    DO UPDATE SET quantity=excluded.quantity,updated_at=CURRENT_TIMESTAMP
                """, (receipt["branch_id"],item["product_id"],new))
                db.execute("""
                    INSERT INTO stock_ledger
                    (branch_id,product_id,transaction_type,reference_type,reference_id,
                     quantity_in,quantity_out,balance_after,unit_cost,notes)
                    VALUES (?,?, 'purchase_receipt','goods_receipt',?,?,?, ?,?,?)
                """, (
                    receipt["branch_id"],item["product_id"],receipt_id,
                    accepted,0,new,item["unit_cost"],receipt["receipt_no"]
                ))

            if item["purchase_order_item_id"]:
                db.execute("""
                    UPDATE purchase_order_items
                    SET received_quantity=received_quantity+?
                    WHERE id=?
                """, (item["received_quantity"],item["purchase_order_item_id"]))

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
            status = "received" if remaining == 0 else ("partially_received" if received else "sent")
            db.execute(
                "UPDATE purchase_orders SET status=? WHERE id=?",
                (status,receipt["purchase_order_id"])
            )
    return {"message": "Goods receipt accepted. Accepted quantities added to stock."}


@router.post("/purchases/direct", status_code=201)
def create_direct_purchase(
    payload: DirectPurchaseCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        supplier = db.execute(
            "SELECT id FROM parties WHERE id=? AND party_type IN ('supplier','both') AND is_active=1",
            (payload.supplier_id,)
        ).fetchone()
        if not supplier:
            raise HTTPException(status_code=404, detail="Supplier not found.")
        branch = branch_id(db)
        calculated = []
        subtotal = discount_total = taxable_total = tax_total = 0.0
        for item in payload.items:
            product = product_or_404(db,item.product_id)
            gross = money(item.quantity * item.unit_cost)
            discount = money(item.discount_amount)
            if discount > gross:
                raise HTTPException(status_code=400, detail="Line discount exceeds line value.")
            taxable = money(gross - discount)
            tax = money(taxable * item.gst_rate / 100)
            calculated.append((item,product,taxable,tax,money(taxable+tax)))
            subtotal += gross
            discount_total += discount
            taxable_total += taxable
            tax_total += tax
        grand_total = money(taxable_total + tax_total)
        paid = money(payload.paid_amount)
        if paid > grand_total:
            raise HTTPException(status_code=400, detail="Payment cannot exceed invoice total.")
        balance = money(grand_total-paid)
        invoice_no = next_number(db,"purchases","invoice_no","PINV-",branch)
        now = datetime.now().date().isoformat()
        db.execute("BEGIN IMMEDIATE")
        cursor = db.execute("""
            INSERT INTO purchases
            (invoice_no,supplier_id,branch_id,invoice_date,supplier_invoice_no,
             subtotal,discount_amount,taxable_amount,total_tax,grand_total,
             paid_amount,balance_amount,status,notes,stock_posted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """, (
            invoice_no,payload.supplier_id,branch,
            payload.invoice_date or now,payload.supplier_invoice_no,
            money(subtotal),money(discount_total),money(taxable_total),
            money(tax_total),grand_total,paid,balance,
            "paid" if balance == 0 else ("partial" if paid else "unpaid"),
            payload.notes
        ))
        purchase_id = cursor.lastrowid
        for item,product,taxable,tax,line_total in calculated:
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
    return {
        "message": "Direct purchase invoice posted and stock updated.",
        "id": purchase_id,"invoice_no": invoice_no,
        "grand_total": grand_total,"paid_amount": paid,"balance_amount": balance
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
        db.execute("BEGIN IMMEDIATE")
        purchase = db.execute(
            "SELECT * FROM purchases WHERE id=?", (payload.purchase_id,)
        ).fetchone()
        if not purchase:
            raise HTTPException(status_code=404, detail="Purchase invoice not found.")
        if money(payload.amount) > money(purchase["balance_amount"]):
            raise HTTPException(status_code=400, detail="Payment exceeds outstanding balance.")
        branch = purchase["branch_id"]
        new_paid = money(purchase["paid_amount"]+payload.amount)
        new_balance = money(purchase["balance_amount"]-payload.amount)
        db.execute("""
            INSERT INTO payments
            (party_id,purchase_id,branch_id,payment_type,payment_method,
             amount,reference_no,payment_date,notes)
            VALUES (?,?,?,'payment',?,?,?,?,?)
        """, (
            purchase["supplier_id"],purchase["id"],branch,
            payload.payment_method,payload.amount,payload.reference_no,
            payload.payment_date or datetime.now().date().isoformat(),
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
    return {"message":"Supplier payment recorded.","paid_amount":new_paid,"balance_amount":new_balance}


@router.post("/purchase-returns", status_code=201)
def create_purchase_return(
    payload: ReturnCreate,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        branch = branch_id(db)
        if payload.purchase_id:
            purchase = db.execute("""
                SELECT id,supplier_id,branch_id FROM purchases WHERE id=?
            """, (payload.purchase_id,)).fetchone()
            if not purchase or purchase["supplier_id"] != payload.supplier_id:
                raise HTTPException(status_code=404, detail="Related purchase invoice not found.")
            branch = purchase["branch_id"]
        return_no = next_number(db,"purchase_returns","return_no","PR-",branch)
        cursor = db.execute("""
            INSERT INTO purchase_returns
            (return_no,purchase_id,supplier_id,branch_id,return_date,reason)
            VALUES (?,?,?,?,?,?)
        """, (
            return_no,payload.purchase_id,payload.supplier_id,branch,
            payload.return_date or datetime.now().date().isoformat(),payload.reason
        ))
        return_id = cursor.lastrowid
        for item in payload.items:
            product_or_404(db,item.product_id)
            db.execute("""
                INSERT INTO purchase_return_items
                (purchase_return_id,product_id,quantity,unit_cost)
                VALUES (?,?,?,?)
            """, (return_id,item.product_id,item.quantity,item.unit_cost))
    return {"message":"Purchase return saved as draft. Stock has not changed.","id":return_id,"return_no":return_no}


@router.post("/purchase-returns/{return_id}/post")
def post_purchase_return(
    return_id: int,
    x_tenant_code: Optional[str] = Header(None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        db.execute("BEGIN IMMEDIATE")

        record = db.execute(
            "SELECT * FROM purchase_returns WHERE id=?", (return_id,)
        ).fetchone()

        if not record:
            raise HTTPException(status_code=404, detail="Purchase return not found.")
        if record["status"] == "posted":
            raise HTTPException(status_code=409, detail="Return already posted.")

        items = db.execute(
            "SELECT * FROM purchase_return_items WHERE purchase_return_id=?",
            (return_id,)
        ).fetchall()

        if not items:
            raise HTTPException(status_code=400, detail="Return has no items.")

        # If linked to an invoice, never allow returns beyond its
        # purchased quantity less quantities already returned.
        if record["purchase_id"]:
            purchase = db.execute("""
                SELECT id, supplier_id, branch_id
                FROM purchases
                WHERE id=?
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

            requested = {}
            for item in items:
                product_id = item["product_id"]
                requested[product_id] = (
                    requested.get(product_id, 0) + float(item["quantity"])
                )

            for product_id, return_quantity in requested.items():
                purchased = db.execute("""
                    SELECT COALESCE(SUM(quantity), 0) AS quantity
                    FROM purchase_items
                    WHERE purchase_id=? AND product_id=?
                """, (record["purchase_id"], product_id)).fetchone()

                already_returned = db.execute("""
                    SELECT COALESCE(SUM(ri.quantity), 0) AS quantity
                    FROM purchase_return_items ri
                    JOIN purchase_returns r
                      ON r.id=ri.purchase_return_id
                    WHERE r.purchase_id=?
                      AND r.status='posted'
                      AND ri.product_id=?
                """, (record["purchase_id"], product_id)).fetchone()

                purchased_quantity = float(purchased["quantity"])
                previous_returns = float(already_returned["quantity"])

                if return_quantity + previous_returns > purchased_quantity + 0.000001:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Return exceeds the remaining purchased quantity "
                            f"for product ID {product_id}. Purchased: "
                            f"{purchased_quantity}, already returned: "
                            f"{previous_returns}, requested now: {return_quantity}."
                        )
                    )

        # Stock must also be available before it can be returned.
        for item in items:
            stock = db.execute("""
                SELECT quantity FROM stock_balances
                WHERE branch_id=? AND product_id=?
            """, (record["branch_id"], item["product_id"])).fetchone()

            available = float(stock["quantity"]) if stock else 0

            if item["quantity"] > available + 0.000001:
                raise HTTPException(
                    status_code=400,
                    detail="Return quantity exceeds available stock."
                )

            remaining = money(available - item["quantity"])

            db.execute("""
                UPDATE stock_balances
                SET quantity=?, updated_at=CURRENT_TIMESTAMP
                WHERE branch_id=? AND product_id=?
            """, (remaining, record["branch_id"], item["product_id"]))

            db.execute("""
                INSERT INTO stock_ledger
                (branch_id,product_id,transaction_type,reference_type,reference_id,
                 quantity_in,quantity_out,balance_after,unit_cost,notes)
                VALUES (?,?, 'purchase_return','purchase_return',?,0,?,?,?,?)
            """, (
                record["branch_id"], item["product_id"], return_id,
                item["quantity"], remaining, item["unit_cost"], record["return_no"]
            ))

        db.execute(
            "UPDATE purchase_returns SET status='posted' WHERE id=?",
            (return_id,)
        )

    return {"message": "Purchase return posted. Stock reduced."}


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
                   COALESCE(SUM(balance_amount),0) AS outstanding
            FROM purchases GROUP BY substr(invoice_date,1,7)
            ORDER BY month DESC LIMIT 24
        """).fetchall()
        suppliers = db.execute("""
            SELECT p.id,p.name,
                   COUNT(pu.id) invoices,
                   COALESCE(SUM(pu.grand_total),0) purchase_value,
                   COALESCE(SUM(pu.balance_amount),0) outstanding
            FROM parties p LEFT JOIN purchases pu ON pu.supplier_id=p.id
            WHERE p.party_type IN ('supplier','both')
            GROUP BY p.id ORDER BY purchase_value DESC
        """).fetchall()
    return {
        "monthly":[dict(x) for x in monthly],
        "suppliers":[dict(x) for x in suppliers]
    }
