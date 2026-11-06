import json
import sqlite3
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .database import tenant_connection, resolve_tenant_database, TenantDatabaseError

router = APIRouter(prefix="/api/v1", tags=["Sales & Billing"])


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
    CREATE TABLE IF NOT EXISTS sale_invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_number TEXT NOT NULL UNIQUE,
        invoice_date TEXT NOT NULL,
        customer_name TEXT,
        customer_phone TEXT,
        subtotal REAL NOT NULL DEFAULT 0,
        discount REAL NOT NULL DEFAULT 0,
        taxable_amount REAL NOT NULL DEFAULT 0,
        gst_amount REAL NOT NULL DEFAULT 0,
        grand_total REAL NOT NULL DEFAULT 0,
        paid_amount REAL NOT NULL DEFAULT 0,
        balance_amount REAL NOT NULL DEFAULT 0,
        payment_status TEXT NOT NULL DEFAULT 'unpaid',
        payment_mode TEXT NOT NULL DEFAULT 'cash',
        notes TEXT,
        custom_fields_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sale_invoice_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        sku TEXT,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        gst_rate REAL NOT NULL DEFAULT 0,
        discount_percent REAL NOT NULL DEFAULT 0,
        taxable_amount REAL NOT NULL DEFAULT 0,
        gst_amount REAL NOT NULL DEFAULT 0,
        line_total REAL NOT NULL DEFAULT 0,
        FOREIGN KEY(invoice_id) REFERENCES sale_invoices(id)
    );

    CREATE TABLE IF NOT EXISTS sale_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id INTEGER NOT NULL,
        payment_date TEXT NOT NULL,
        payment_mode TEXT NOT NULL,
        amount REAL NOT NULL,
        reference TEXT,
        FOREIGN KEY(invoice_id) REFERENCES sale_invoices(id)
    );

    CREATE INDEX IF NOT EXISTS idx_sale_invoice_date
    ON sale_invoices(invoice_date);

    CREATE INDEX IF NOT EXISTS idx_sale_invoice_number
    ON sale_invoices(invoice_number);
    """)

    columns = {row["name"] for row in db.execute(
        "PRAGMA table_info(sale_invoices)"
    ).fetchall()}
    if "customer_party_id" not in columns:
        db.execute("ALTER TABLE sale_invoices ADD COLUMN customer_party_id INTEGER")

    header_columns = {r["name"] for r in db.execute(
        "PRAGMA table_info(sale_invoices)"
    ).fetchall()}
    for name in ("cgst", "sgst", "igst", "total_tax"):
        if name not in header_columns:
            db.execute(f"ALTER TABLE sale_invoices ADD COLUMN {name} REAL NOT NULL DEFAULT 0")

    item_columns = {r["name"] for r in db.execute(
        "PRAGMA table_info(sale_invoice_items)"
    ).fetchall()}
    for name, definition in (
        ("hsn_code", "TEXT"),
        ("cgst", "REAL NOT NULL DEFAULT 0"),
        ("sgst", "REAL NOT NULL DEFAULT 0"),
        ("igst", "REAL NOT NULL DEFAULT 0"),
    ):
        if name not in item_columns:
            db.execute(f"ALTER TABLE sale_invoice_items ADD COLUMN {name} {definition}")


def _mobile_digits(value):
    import re
    return re.sub(r"\D", "", str(value or ""))


def find_or_create_customer(db, customer_name, customer_phone, customer_state_code=None):
    name = str(customer_name or "").strip()
    phone = str(customer_phone or "").strip()

    if not name or name.lower() == "walk-in customer":
        return None

    digits = _mobile_digits(phone)
    candidates = db.execute("""
        SELECT id, name, phone
        FROM parties
        WHERE party_type IN ('customer', 'both')
          AND COALESCE(is_active, 1)=1
        ORDER BY id
    """).fetchall()

    for candidate in candidates:
        existing_digits = _mobile_digits(candidate["phone"])
        if digits and len(digits) >= 7 and existing_digits == digits:
            if customer_state_code:
                db.execute(
                    "UPDATE parties SET state_code=? WHERE id=?",
                    (customer_state_code, candidate["id"])
                )
            return candidate["id"]

        if not digits and not existing_digits and (
            str(candidate["name"] or "").strip().casefold() == name.casefold()
        ):
            if customer_state_code:
                db.execute(
                    "UPDATE parties SET state_code=? WHERE id=?",
                    (customer_state_code, candidate["id"])
                )
            return candidate["id"]

    cursor = db.execute("""
        INSERT INTO parties (party_type, name, phone, state_code)
        VALUES ('customer', ?, ?, ?)
    """, (name, phone or None, customer_state_code or None))
    return cursor.lastrowid


class SaleItem(BaseModel):
    product_id: int = Field(gt=0)
    quantity: float = Field(gt=0)
    discount_percent: float = Field(default=0, ge=0, le=100)


class SaleCreate(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_state_code: Optional[str] = None
    items: list[SaleItem] = Field(min_length=1)
    bill_discount: float = Field(default=0, ge=0)
    paid_amount: float = Field(default=0, ge=0)
    payment_mode: str = "cash"
    payment_reference: Optional[str] = None
    notes: Optional[str] = None
    custom_fields: dict = Field(default_factory=dict)


def get_branch(db):
    row = db.execute(
        "SELECT id FROM branches ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        raise HTTPException(status_code=500, detail="No branch is configured.")
    return row["id"]


@router.get("/sales/products")
def search_sale_products(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=100),
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = tenant_code(x_tenant_code)
    term = f"%{search.strip()}%"
    with tenant_connection(code) as db:
        setup(db)
        branch_id = get_branch(db)
        rows = db.execute("""
            SELECT p.id, p.name, p.sku, p.isbn10, p.isbn13,
                   p.author, p.publisher, p.unit, p.hsn_code,
                   COALESCE(p.selling_price, 0) AS selling_price,
                   COALESCE(p.mrp, 0) AS mrp,
                   COALESCE(p.gst_rate, 0) AS gst_rate,
                   COALESCE(sb.quantity, 0) AS stock
            FROM products p
            LEFT JOIN stock_balances sb
              ON sb.product_id=p.id AND sb.branch_id=?
            WHERE COALESCE(p.is_active, 1)=1
              AND (?='' OR p.name LIKE ? OR p.sku LIKE ?
                   OR p.isbn10 LIKE ? OR p.isbn13 LIKE ?
                   OR p.author LIKE ? OR p.publisher LIKE ?)
            ORDER BY p.name
            LIMIT ?
        """, (
            branch_id, search.strip(), term, term, term, term,
            term, term, limit
        )).fetchall()
    return {"products": [dict(row) for row in rows]}


@router.post("/sales", status_code=201)
def create_sale(
    payload: SaleCreate,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = tenant_code(x_tenant_code)
    allowed_modes = {
        "cash", "upi", "card", "bank_transfer", "credit", "other"
    }
    mode = payload.payment_mode.lower().strip()
    if mode not in allowed_modes:
        raise HTTPException(status_code=400, detail="Invalid payment mode.")

    if not payload.items:
        raise HTTPException(status_code=400, detail="Add at least one product.")

    with tenant_connection(code) as db:
        setup(db)
        from .finance import setup as finance_setup
        finance_setup(db)
        branch_id = get_branch(db)
        db.execute("BEGIN IMMEDIATE")

        try:
            calculated = []
            subtotal = 0.0

            for item in payload.items:
                product = db.execute("""
                    SELECT id, name, sku, selling_price, gst_rate, hsn_code
                    FROM products
                    WHERE id=? AND COALESCE(is_active, 1)=1
                """, (item.product_id,)).fetchone()

                if not product:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Product {item.product_id} was not found."
                    )

                stock_row = db.execute("""
                    SELECT quantity FROM stock_balances
                    WHERE branch_id=? AND product_id=?
                """, (branch_id, item.product_id)).fetchone()

                stock = float(stock_row["quantity"]) if stock_row else 0
                if item.quantity > stock:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient stock for {product['name']}. Available: {stock:g}"
                    )

                price = money(product["selling_price"])
                rate = money(product["gst_rate"])
                gross = money(price * item.quantity)
                line_discount = money(gross * item.discount_percent / 100)
                taxable_before_bill_discount = money(gross - line_discount)
                subtotal += taxable_before_bill_discount

                calculated.append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "sku": product["sku"],
                    "hsn_code": product["hsn_code"],
                    "quantity": item.quantity,
                    "price": price,
                    "rate": rate,
                    "discount_percent": item.discount_percent,
                    "taxable_before_bill_discount": taxable_before_bill_discount
                })

            subtotal = money(subtotal)
            bill_discount = money(payload.bill_discount)
            if bill_discount > subtotal:
                raise HTTPException(
                    status_code=400,
                    detail="Bill discount cannot exceed the subtotal."
                )

            # Resolve customer and business state before splitting GST.
            customer_party_id = find_or_create_customer(
                db, payload.customer_name, payload.customer_phone,
                payload.customer_state_code
            )
            gst_settings = db.execute(
                "SELECT state_code FROM gst_settings WHERE id=1"
            ).fetchone()
            business_state = str(
                (gst_settings["state_code"] if gst_settings else "") or ""
            ).strip()

            customer_state = ""
            if customer_party_id:
                party = db.execute(
                    "SELECT state_code FROM parties WHERE id=?",
                    (customer_party_id,)
                ).fetchone()
                if party:
                    customer_state = str(party["state_code"] or "").strip()

            # Walk-in customers default to the business state.
            place_of_supply = customer_state or business_state
            intra_state = (
                not business_state or not place_of_supply
                or business_state.casefold() == place_of_supply.casefold()
            )

            # Allocate bill discount proportionately before calculating GST.
            factor = (subtotal - bill_discount) / subtotal if subtotal else 0
            taxable_total = cgst_total = sgst_total = igst_total = 0.0

            for line in calculated:
                taxable = money(line["taxable_before_bill_discount"] * factor)
                gst = money(taxable * line["rate"] / 100)

                if intra_state:
                    cgst = money(gst / 2)
                    sgst = money(gst - cgst)
                    igst = 0.0
                else:
                    cgst = sgst = 0.0
                    igst = gst

                line["taxable"] = taxable
                line["gst"] = money(cgst + sgst + igst)
                line["cgst"] = cgst
                line["sgst"] = sgst
                line["igst"] = igst
                line["hsn_code"] = line.get("hsn_code")
                line["total"] = money(taxable + line["gst"])

                taxable_total += taxable
                cgst_total += cgst
                sgst_total += sgst
                igst_total += igst

            taxable_total = money(taxable_total)
            cgst_total = money(cgst_total)
            sgst_total = money(sgst_total)
            igst_total = money(igst_total)
            gst_total = money(cgst_total + sgst_total + igst_total)
            grand_total = money(taxable_total + gst_total)

            paid = money(payload.paid_amount)
            if paid > grand_total:
                raise HTTPException(
                    status_code=400,
                    detail="Payment cannot exceed the invoice total."
                )

            balance = money(grand_total - paid)
            status = (
                "paid" if balance == 0 else
                "partial" if paid > 0 else "unpaid"
            )

            now = datetime.now().astimezone().isoformat(timespec="seconds")
            invoice_date = now[:10]
            prefix = "INV-" + datetime.now().strftime("%Y%m%d") + "-"
            last = db.execute("""
                SELECT invoice_number FROM sale_invoices
                WHERE invoice_number LIKE ?
                ORDER BY id DESC LIMIT 1
            """, (prefix + "%",)).fetchone()
            sequence = 1
            if last:
                try:
                    sequence = int(last["invoice_number"].rsplit("-", 1)[1]) + 1
                except (ValueError, IndexError):
                    sequence = 1
            invoice_number = prefix + f"{sequence:04d}"

            cursor = db.execute("""
                INSERT INTO sale_invoices (
                    invoice_number, invoice_date, customer_name,
                    customer_phone, subtotal, discount, taxable_amount,
                    gst_amount, cgst, sgst, igst, total_tax,
                    grand_total, paid_amount, balance_amount,
                    payment_status, payment_mode, notes, custom_fields_json,
                    customer_party_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice_number, invoice_date,
                (payload.customer_name or "").strip() or "Walk-in Customer",
                (payload.customer_phone or "").strip(),
                subtotal, bill_discount, taxable_total, gst_total,
                cgst_total, sgst_total, igst_total, gst_total,
                grand_total, paid, balance, status, mode,
                payload.notes,
                json.dumps(payload.custom_fields, ensure_ascii=False),
                customer_party_id
            ))
            invoice_id = cursor.lastrowid

            for line in calculated:
                db.execute("""
                    INSERT INTO sale_invoice_items (
                        invoice_id, product_id, product_name, sku,
                        quantity, unit_price, gst_rate, discount_percent,
                        taxable_amount, gst_amount, line_total,
                        hsn_code, cgst, sgst, igst
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    invoice_id, line["product_id"], line["name"], line["sku"],
                    line["quantity"], line["price"], line["rate"],
                    line["discount_percent"], line["taxable"],
                    line["gst"], line["total"], line["hsn_code"],
                    line["cgst"], line["sgst"], line["igst"]
                ))

                new_stock = db.execute("""
                    SELECT quantity FROM stock_balances
                    WHERE branch_id=? AND product_id=?
                """, (branch_id, line["product_id"])).fetchone()
                remaining = money(float(new_stock["quantity"]) - line["quantity"])

                db.execute("""
                    UPDATE stock_balances
                    SET quantity=?, updated_at=CURRENT_TIMESTAMP
                    WHERE branch_id=? AND product_id=?
                """, (remaining, branch_id, line["product_id"]))

                # Keep the existing inventory ledger in sync.
                db.execute("""
                    INSERT INTO stock_ledger (
                        branch_id, product_id, transaction_type,
                        quantity_in, quantity_out, balance_after, notes
                    ) VALUES (?, ?, 'sale', 0, ?, ?, ?)
                """, (
                    branch_id, line["product_id"], line["quantity"],
                    remaining, f"Sale {invoice_number}"
                ))

            if paid > 0:
                db.execute("""
                    INSERT INTO sale_payments (
                        invoice_id, payment_date, payment_mode, amount, reference
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    invoice_id, now, mode, paid, payload.payment_reference
                ))

            db.commit()
        except Exception:
            db.rollback()
            raise

    return {
        "message": "Sale saved successfully.",
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "grand_total": grand_total,
        "paid_amount": paid,
        "balance_amount": balance,
        "payment_status": status
    }


@router.get("/sales")
def list_sales(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = tenant_code(x_tenant_code)
    term = f"%{search.strip()}%"
    with tenant_connection(code) as db:
        setup(db)
        rows = db.execute("""
            SELECT * FROM sale_invoices
            WHERE (?='' OR invoice_number LIKE ?
                OR customer_name LIKE ? OR customer_phone LIKE ?)
            ORDER BY id DESC LIMIT ?
        """, (search.strip(), term, term, term, limit)).fetchall()
    return {"sales": [dict(row) for row in rows]}


@router.get("/sales/{invoice_id}")
def get_sale(
    invoice_id: int,
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = tenant_code(x_tenant_code)
    with tenant_connection(code) as db:
        setup(db)
        invoice = db.execute(
            "SELECT * FROM sale_invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found.")
        items = db.execute("""
            SELECT * FROM sale_invoice_items
            WHERE invoice_id=? ORDER BY id
        """, (invoice_id,)).fetchall()
        payments = db.execute("""
            SELECT * FROM sale_payments
            WHERE invoice_id=? ORDER BY id
        """, (invoice_id,)).fetchall()

    result = dict(invoice)
    result["custom_fields"] = json.loads(result.pop("custom_fields_json") or "{}")
    result["items"] = [dict(row) for row in items]
    result["payments"] = [dict(row) for row in payments]
    return result

@router.get("/customers/directory")
def customer_directory(
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=500, ge=1, le=1000),
    x_tenant_code: Optional[str] = Header(default=None)
):
    code = tenant_code(x_tenant_code)
    term = f"%{search.strip()}%"

    with tenant_connection(code) as db:
        setup(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            # Link older named invoices to customer records as well.
            old_invoices = db.execute("""
                SELECT id, customer_name, customer_phone
                FROM sale_invoices
                WHERE customer_party_id IS NULL
                ORDER BY id
            """).fetchall()

            for invoice in old_invoices:
                customer_id = find_or_create_customer(
                    db, invoice["customer_name"], invoice["customer_phone"]
                )
                if customer_id is not None:
                    db.execute("""
                        UPDATE sale_invoices
                        SET customer_party_id=?
                        WHERE id=? AND customer_party_id IS NULL
                    """, (customer_id, invoice["id"]))

            rows = db.execute("""
                SELECT
                    p.id,
                    p.name AS customer_name,
                    p.phone AS mobile_number,
                    MIN(si.invoice_date) AS first_purchase_date,
                    COUNT(si.id) AS total_invoices,
                    COALESCE(SUM(si.grand_total), 0) AS total_purchase_value,
                    COALESCE(SUM(si.balance_amount), 0) AS outstanding_balance
                FROM parties p
                INNER JOIN sale_invoices si
                    ON si.customer_party_id = p.id
                WHERE p.party_type IN ('customer', 'both')
                  AND COALESCE(p.is_active, 1)=1
                  AND (
                    ?='' OR p.name LIKE ? OR p.phone LIKE ?
                  )
                GROUP BY p.id, p.name, p.phone
                ORDER BY p.name
                LIMIT ?
            """, (search.strip(), term, term, limit)).fetchall()

            db.commit()
        except Exception:
            db.rollback()
            raise

    return {"customers": [dict(row) for row in rows]}
