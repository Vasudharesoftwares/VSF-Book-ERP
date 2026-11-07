from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from .database import tenant_connection, TenantDatabaseError

router = APIRouter(prefix="/api/v1", tags=["GST and Accounting"])

def tenant(x_tenant_code):
    code = (x_tenant_code or "").strip().upper()
    if code not in ("DEMO-01", "DEMO-02"):
        raise HTTPException(400, "Valid tenant code required")
    return code

def setup(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS gst_settings (
      id INTEGER PRIMARY KEY CHECK(id=1),
      gstin TEXT DEFAULT '',
      business_state TEXT DEFAULT '',
      state_code TEXT DEFAULT '',
      financial_year TEXT DEFAULT '',
      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    INSERT OR IGNORE INTO gst_settings(id) VALUES(1);

    CREATE TABLE IF NOT EXISTS gst_tax_rates (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      rate REAL NOT NULL,
      is_active INTEGER DEFAULT 1,
      UNIQUE(name,rate)
    );

    CREATE TABLE IF NOT EXISTS accounts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      code TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL,
      account_type TEXT NOT NULL,
      parent_id INTEGER,
      opening_balance REAL DEFAULT 0,
      is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS journal_vouchers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      voucher_no TEXT UNIQUE NOT NULL,
      voucher_date TEXT NOT NULL,
      voucher_type TEXT NOT NULL,
      narration TEXT DEFAULT '',
      source_type TEXT DEFAULT '',
      source_id INTEGER,
      status TEXT DEFAULT 'posted',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS journal_lines (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      voucher_id INTEGER NOT NULL,
      account_id INTEGER NOT NULL,
      debit REAL DEFAULT 0,
      credit REAL DEFAULT 0,
      narration TEXT DEFAULT '',
      FOREIGN KEY(voucher_id) REFERENCES journal_vouchers(id),
      FOREIGN KEY(account_id) REFERENCES accounts(id)
    );

    CREATE INDEX IF NOT EXISTS idx_journal_lines_account
    ON journal_lines(account_id);

    CREATE UNIQUE INDEX IF NOT EXISTS idx_journal_source_unique
    ON journal_vouchers(source_type, source_id)
    WHERE source_type <> '' AND source_id IS NOT NULL;
    """)
    defaults = [
      ("1000","Cash","asset"),
      ("1010","Bank","asset"),
      ("1100","Accounts Receivable","asset"),
      ("1200","Inventory","asset"),
      ("1300","Input CGST","asset"),
      ("1310","Input SGST","asset"),
      ("1320","Input IGST","asset"),
      ("2000","Accounts Payable","liability"),
      ("2010","Goods Received Not Invoiced","liability"),
      ("2100","Output CGST","liability"),
      ("2110","Output SGST","liability"),
      ("2120","Output IGST","liability"),
      ("3000","Capital","equity"),
      ("4000","Sales Revenue","income"),
      ("4100","Other Income","income"),
      ("5000","Purchases","expense"),
        ("5010", "Cost of Goods Sold", "expense"),
      ("5100","Operating Expenses","expense"),
      ("5020","Purchase Price Variance","expense"),
    ]
    for code,name,typ in defaults:
        db.execute("""INSERT OR IGNORE INTO accounts
        (code,name,account_type) VALUES(?,?,?)""",(code,name,typ))
    grni = db.execute(
        "SELECT name FROM accounts WHERE code='2010'"
    ).fetchone()
    if not grni or grni["name"] != "Goods Received Not Invoiced":
        raise RuntimeError(
            "Account code 2010 is already assigned to a different account. "
            "Resolve the account-code conflict before using goods receipts."
        )

    ppv = db.execute(
        "SELECT name FROM accounts WHERE code='5020'"
    ).fetchone()
    if not ppv or ppv["name"] != "Purchase Price Variance":
        raise RuntimeError(
            "Account code 5020 is already assigned to a different account. "
            "Resolve the account-code conflict before using receipt-linked invoices."
        )

    for rate in (0,5,12,18,28):
        db.execute("""INSERT OR IGNORE INTO gst_tax_rates(name,rate)
        VALUES(?,?)""",(f"GST {rate}%",rate))

def accounts_map(db):
    return {r["name"]:r["id"] for r in db.execute(
        "SELECT id,name FROM accounts WHERE is_active=1"
    ).fetchall()}

def money(v):
    return float(Decimal(str(v or 0)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    ))


def post_journal(
    db,
    voucher_date,
    voucher_type,
    narration,
    source_type,
    source_id,
    lines,
):
    """
    Insert one balanced, source-linked journal voucher.

    The caller owns the transaction. This function never commits.
    Repeated source references are rejected to prevent duplicate posting.

    Each line is a dict:
      {"account_id": int, "debit": number, "credit": number,
       "narration": optional string}
    """
    if not source_type or source_id is None:
        raise ValueError("Journal source reference is required.")

    existing = db.execute(
        """SELECT voucher_no FROM journal_vouchers
           WHERE source_type=? AND source_id=?""",
        (source_type, source_id),
    ).fetchone()

    if existing:
        raise ValueError(
            f"Accounting entry already exists: {existing['voucher_no']}"
        )

    if len(lines) < 2:
        raise ValueError("A journal voucher needs at least two lines.")

    normalized = []
    debit_total = 0.0
    credit_total = 0.0

    for line in lines:
        account_id = int(line["account_id"])
        debit = money(line.get("debit", 0))
        credit = money(line.get("credit", 0))

        if debit < 0 or credit < 0 or (debit and credit):
            raise ValueError("Invalid journal debit or credit line.")

        account = db.execute(
            "SELECT id FROM accounts WHERE id=? AND is_active=1",
            (account_id,),
        ).fetchone()

        if not account:
            raise ValueError(f"Inactive or missing account: {account_id}")

        if debit == 0 and credit == 0:
            continue

        debit_total += debit
        credit_total += credit

        normalized.append((
            account_id,
            debit,
            credit,
            str(line.get("narration", "")),
        ))

    debit_total = money(debit_total)
    credit_total = money(credit_total)

    if len(normalized) < 2 or debit_total <= 0 or debit_total != credit_total:
        raise ValueError("Journal debits and credits must balance.")

    next_id = db.execute(
        "SELECT COALESCE(MAX(id), 0) + 1 FROM journal_vouchers"
    ).fetchone()[0]

    number = (
        "JV-" + date.today().strftime("%Y%m%d") +
        "-" + str(next_id).zfill(6)
    )

    cursor = db.execute(
        """INSERT INTO journal_vouchers
           (voucher_no, voucher_date, voucher_type, narration,
            source_type, source_id, status)
           VALUES (?, ?, ?, ?, ?, ?, 'posted')""",
        (
            number, voucher_date, voucher_type, narration,
            source_type, source_id,
        ),
    )

    db.executemany(
        """INSERT INTO journal_lines
           (voucher_id, account_id, debit, credit, narration)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (cursor.lastrowid, account_id, debit, credit, line_narration)
            for account_id, debit, credit, line_narration in normalized
        ],
    )

    return number

@router.get("/gst/dashboard")
def gst_dashboard(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)

        # Current billing workflow stores invoices in sale_invoices.
        # Do not union the legacy sales table: that risks double-counting.
        sales = db.execute("""
            SELECT
                COALESCE(SUM(taxable_amount), 0) AS taxable,
                COALESCE(SUM(cgst), 0) AS cgst,
                COALESCE(SUM(sgst), 0) AS sgst,
                COALESCE(SUM(igst), 0) AS igst,
                COALESCE(SUM(total_tax), 0) AS tax,
                COUNT(*) AS invoices
            FROM sale_invoices
        """).fetchone()

        purchases = db.execute("""
            SELECT
                COALESCE(SUM(taxable_amount), 0) AS taxable,
                COALESCE(SUM(cgst), 0) AS cgst,
                COALESCE(SUM(sgst), 0) AS sgst,
                COALESCE(SUM(igst), 0) AS igst,
                COALESCE(SUM(total_tax), 0) AS tax,
                COUNT(*) AS invoices
            FROM purchases
            WHERE LOWER(COALESCE(status, '')) NOT IN
                  ('draft', 'cancelled', 'cancel')
        """).fetchone()

        return {
            "sales": dict(sales),
            "purchases": dict(purchases),
            "output_tax": money(sales["tax"]),
            "input_tax": money(purchases["tax"]),
            "net_tax": money(sales["tax"] - purchases["tax"])
        }

@router.get("/gst/settings")
def get_gst_settings(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return dict(db.execute("SELECT * FROM gst_settings WHERE id=1").fetchone())

class GSTSettings(BaseModel):
    gstin: str=""
    business_state: str=""
    state_code: str=""
    financial_year: str=""

@router.put("/gst/settings")
def update_gst_settings(data: GSTSettings,
                        x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        db.execute("""UPDATE gst_settings SET gstin=?,business_state=?,
        state_code=?,financial_year=?,updated_at=CURRENT_TIMESTAMP
        WHERE id=1""",(data.gstin,data.business_state,
        data.state_code,data.financial_year))
        return {"message":"GST settings saved"}

@router.get("/gst/tax-rates")
def tax_rates(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute(
          "SELECT * FROM gst_tax_rates ORDER BY rate"
        ).fetchall()]

class TaxRate(BaseModel):
    name: str
    rate: float=Field(ge=0,le=100)

@router.post("/gst/tax-rates")
def add_tax_rate(data: TaxRate,
                 x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        try:
            db.execute("INSERT INTO gst_tax_rates(name,rate) VALUES(?,?)",
                       (data.name,data.rate))
        except Exception:
            raise HTTPException(409,"Tax rate already exists")
        return {"message":"Tax rate saved"}

@router.get("/gst/register/{kind}")
def gst_register(kind: str,
                 from_date: Optional[str]=None,
                 to_date: Optional[str]=None,
                 x_tenant_code: Optional[str]=Header(None)):
    if kind not in ("sales","purchases"):
        raise HTTPException(400,"Use sales or purchases")

    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)

        if kind == "sales":
            sql = """SELECT
                i.id,
                i.invoice_number AS invoice_no,
                i.invoice_date,
                i.taxable_amount,
                i.cgst,
                i.sgst,
                i.igst,
                i.total_tax,
                i.grand_total,
                i.payment_status AS status,
                i.customer_name AS party_name,
                p.gstin,
                p.state_code
                FROM sale_invoices i
                LEFT JOIN parties p ON p.id=i.customer_party_id
                WHERE 1=1"""
            params = []
            if from_date:
                sql += " AND date(i.invoice_date)>=date(?)"
                params.append(from_date)
            if to_date:
                sql += " AND date(i.invoice_date)<=date(?)"
                params.append(to_date)
            sql += " ORDER BY i.invoice_date DESC,i.id DESC"
        else:
            sql = """SELECT t.id,t.invoice_no,t.invoice_date,
                t.taxable_amount,t.cgst,t.sgst,t.igst,t.total_tax,
                t.grand_total,t.status,p.name party_name,p.gstin,p.state_code
                FROM purchases t LEFT JOIN parties p ON p.id=t.supplier_id
                WHERE LOWER(COALESCE(t.status,'')) NOT IN
                ('draft','cancelled','cancel')"""
            params = []
            if from_date:
                sql += " AND date(t.invoice_date)>=date(?)"
                params.append(from_date)
            if to_date:
                sql += " AND date(t.invoice_date)<=date(?)"
                params.append(to_date)
            sql += " ORDER BY t.invoice_date DESC,t.id DESC"

        return [dict(r) for r in db.execute(sql,params).fetchall()]

@router.get("/gst/hsn-summary")
def hsn_summary(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
            SELECT
                supply_type,
                hsn,
                gst_rate,
                SUM(quantity) AS quantity,
                SUM(taxable_value) AS taxable_value,
                SUM(tax_value) AS tax_value
            FROM (
                SELECT
                    'Outward' AS supply_type,
                    COALESCE(NULLIF(i.hsn_code, ''), 'UNSPECIFIED') AS hsn,
                    COALESCE(i.gst_rate, 0) AS gst_rate,
                    i.quantity AS quantity,
                    i.taxable_amount AS taxable_value,
                    i.gst_amount AS tax_value
                FROM sale_invoice_items i
                JOIN sale_invoices t ON t.id = i.invoice_id

                UNION ALL

                SELECT
                    'Inward' AS supply_type,
                    COALESCE(NULLIF(p.hsn_code, ''), 'UNSPECIFIED') AS hsn,
                    COALESCE(i.gst_rate, 0) AS gst_rate,
                    i.quantity AS quantity,
                    i.taxable_amount AS taxable_value,
                    i.tax_amount AS tax_value
                FROM purchase_items i
                JOIN purchases t ON t.id = i.purchase_id
                LEFT JOIN products p ON p.id = i.product_id
                WHERE LOWER(COALESCE(t.status, '')) NOT IN
                      ('draft', 'cancelled', 'cancel')
            )
            GROUP BY supply_type, hsn, gst_rate
            ORDER BY supply_type, hsn, gst_rate
        """).fetchall()]

@router.get("/gst/gstr1")
def gstr1(x_tenant_code: Optional[str]=Header(None)):
    return gst_register("sales",x_tenant_code=x_tenant_code)

@router.get("/gst/gstr3b")
def gstr3b(x_tenant_code: Optional[str]=Header(None)):
    return gst_dashboard(x_tenant_code=x_tenant_code)

@router.get("/accounting/accounts")
def list_accounts(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute(
          "SELECT * FROM accounts ORDER BY code"
        ).fetchall()]

class AccountInput(BaseModel):
    code: str
    name: str
    account_type: str

@router.post("/accounting/accounts")
def create_account(data: AccountInput,
                   x_tenant_code: Optional[str]=Header(None)):
    if data.account_type not in ("asset","liability","equity","income","expense"):
        raise HTTPException(400,"Invalid account type")
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        try:
            db.execute("""INSERT INTO accounts(code,name,account_type)
            VALUES(?,?,?)""",(data.code,data.name,data.account_type))
        except Exception:
            raise HTTPException(409,"Account code already exists")
        return {"message":"Account created"}

class JournalLine(BaseModel):
    account_id: int
    debit: float=Field(default=0,ge=0)
    credit: float=Field(default=0,ge=0)
    narration: str=""

class VoucherInput(BaseModel):
    voucher_date: str
    voucher_type: str
    narration: str=""
    lines: list[JournalLine]

@router.post("/accounting/vouchers")
def create_voucher(data: VoucherInput,
                   x_tenant_code: Optional[str]=Header(None)):
    debit=money(sum(x.debit for x in data.lines))
    credit=money(sum(x.credit for x in data.lines))
    if len(data.lines)<2 or debit<=0 or debit!=credit:
        raise HTTPException(400,"Voucher must have equal debit and credit totals")
    if any(x.debit and x.credit for x in data.lines):
        raise HTTPException(400,"A line cannot contain both debit and credit")
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        for line in data.lines:
            if not db.execute("SELECT id FROM accounts WHERE id=? AND is_active=1",
                              (line.account_id,)).fetchone():
                raise HTTPException(400,"Invalid account")
        db.execute("BEGIN IMMEDIATE")
        try:
            number="JV-"+date.today().strftime("%Y%m%d")+"-"+str(
              db.execute("SELECT COUNT(*) FROM journal_vouchers").fetchone()[0]+1
            ).zfill(4)
            cur=db.execute("""INSERT INTO journal_vouchers
            (voucher_no,voucher_date,voucher_type,narration)
            VALUES(?,?,?,?)""",(number,data.voucher_date,
            data.voucher_type,data.narration))
            for line in data.lines:
                db.execute("""INSERT INTO journal_lines
                (voucher_id,account_id,debit,credit,narration)
                VALUES(?,?,?,?,?)""",(cur.lastrowid,line.account_id,
                money(line.debit),money(line.credit),line.narration))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"message":"Voucher posted","voucher_no":number}

@router.get("/accounting/vouchers")
def vouchers(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
        SELECT * FROM journal_vouchers ORDER BY voucher_date DESC,id DESC
        """).fetchall()]


def validate_accounting_dates(from_date=None, to_date=None):
    for label, value in (("from_date", from_date), ("to_date", to_date)):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise HTTPException(400, f"Invalid {label}; use YYYY-MM-DD")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "From date cannot be after To date")



def normal_side(account_type):
    return "Dr" if account_type in ("asset", "expense") else "Cr"


def normal_movement(account_type, debit, credit):
    if account_type in ("asset", "expense"):
        return money(debit - credit)
    return money(credit - debit)


def account_movement(db, account_id, account_type, start=None, end=None):
    sql = """
        SELECT COALESCE(SUM(l.debit),0) debit,
               COALESCE(SUM(l.credit),0) credit
        FROM journal_lines l
        JOIN journal_vouchers v ON v.id=l.voucher_id
        WHERE l.account_id=? AND v.status='posted'
    """
    params = [account_id]

    if start:
        sql += " AND date(v.voucher_date)>=date(?)"
        params.append(start)
    if end:
        sql += " AND date(v.voucher_date)<=date(?)"
        params.append(end)

    row = db.execute(sql, params).fetchone()
    debit = money(row["debit"])
    credit = money(row["credit"])
    return debit, credit, normal_movement(account_type, debit, credit)


@router.get("/accounting/trial-balance")
def trial_balance(from_date: Optional[str]=None, to_date: Optional[str]=None,
                  x_tenant_code: Optional[str]=Header(None)):
    validate_accounting_dates(from_date, to_date)

    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        result = []

        accounts = db.execute("""
            SELECT id,code,name,account_type,opening_balance
            FROM accounts
            WHERE is_active=1
            ORDER BY code
        """).fetchall()

        for account in accounts:
            typ = account["account_type"]
            opening = money(account["opening_balance"])

            if from_date:
                _, _, prior_movement = account_movement(
                    db, account["id"], typ, end=None
                )
                # Only entries strictly before the selected start date.
                prior = db.execute("""
                    SELECT COALESCE(SUM(l.debit),0) debit,
                           COALESCE(SUM(l.credit),0) credit
                    FROM journal_lines l
                    JOIN journal_vouchers v ON v.id=l.voucher_id
                    WHERE l.account_id=? AND v.status='posted'
                      AND date(v.voucher_date)<date(?)
                """, (account["id"], from_date)).fetchone()
                opening += normal_movement(
                    typ, money(prior["debit"]), money(prior["credit"])
                )
            else:
                opening = money(account["opening_balance"])

            period_debit, period_credit, period_net = account_movement(
                db, account["id"], typ, start=from_date, end=to_date
            )
            closing = money(opening + period_net)

            result.append({
                "id": account["id"],
                "code": account["code"],
                "name": account["name"],
                "account_type": typ,
                "normal_side": normal_side(typ),
                "opening_balance": money(account["opening_balance"]),
                "opening_debit": max(opening, 0) if normal_side(typ) == "Dr" else max(-opening, 0),
                "opening_credit": max(opening, 0) if normal_side(typ) == "Cr" else max(-opening, 0),
                "debit": period_debit,
                "credit": period_credit,
                "period_debit": period_debit,
                "period_credit": period_credit,
                "closing_balance": abs(closing),
                "closing_debit": abs(closing) if closing < 0 and normal_side(typ) == "Cr" else abs(closing) if closing > 0 and normal_side(typ) == "Dr" else 0,
                "closing_credit": abs(closing) if closing < 0 and normal_side(typ) == "Dr" else abs(closing) if closing > 0 and normal_side(typ) == "Cr" else 0,
            })

        return result


@router.get("/accounting/ledger/{account_id}")
def account_ledger(account_id: int,
                   from_date: Optional[str]=None,
                   to_date: Optional[str]=None,
                   x_tenant_code: Optional[str]=Header(None)):
    validate_accounting_dates(from_date, to_date)

    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)

        account = db.execute("""
            SELECT id,code,name,account_type,opening_balance
            FROM accounts WHERE id=? AND is_active=1
        """, (account_id,)).fetchone()

        if not account:
            raise HTTPException(404, "Account not found.")

        typ = account["account_type"]
        opening = money(account["opening_balance"])

        if from_date:
            prior = db.execute("""
                SELECT COALESCE(SUM(l.debit),0) debit,
                       COALESCE(SUM(l.credit),0) credit
                FROM journal_lines l
                JOIN journal_vouchers v ON v.id=l.voucher_id
                WHERE l.account_id=? AND v.status='posted'
                  AND date(v.voucher_date)<date(?)
            """, (account_id, from_date)).fetchone()
            opening += normal_movement(
                typ, money(prior["debit"]), money(prior["credit"])
            )

        rows = db.execute("""
            SELECT v.voucher_no,v.voucher_date,v.voucher_type,
                   v.narration,l.debit,l.credit,
                   l.narration line_narration
            FROM journal_lines l
            JOIN journal_vouchers v ON v.id=l.voucher_id
            WHERE l.account_id=? AND v.status='posted'
              AND (? IS NULL OR date(v.voucher_date)>=date(?))
              AND (? IS NULL OR date(v.voucher_date)<=date(?))
            ORDER BY v.voucher_date,v.id,l.id
        """, (account_id, from_date, from_date, to_date, to_date)).fetchall()

        running = opening
        result = []

        if opening != 0 or from_date:
            result.append({
                "voucher_no": "OPENING",
                "voucher_date": from_date or "",
                "voucher_type": "OPENING BALANCE",
                "narration": f"Opening balance for {account['name']}",
                "debit": 0,
                "credit": 0,
                "line_narration": "Opening balance",
                "is_opening_balance": True,
                "running_balance": abs(running),
                "balance_side": normal_side(typ) if running >= 0 else ("Cr" if normal_side(typ) == "Dr" else "Dr"),
            })

        for row in rows:
            item = dict(row)
            running = money(
                running + normal_movement(
                    typ, money(item["debit"]), money(item["credit"])
                )
            )
            item["is_opening_balance"] = False
            item["running_balance"] = abs(running)
            item["balance_side"] = (
                normal_side(typ) if running >= 0
                else ("Cr" if normal_side(typ) == "Dr" else "Dr")
            )
            result.append(item)

        return result


@router.get("/accounting/profit-loss")
def profit_loss(from_date: Optional[str]=None, to_date: Optional[str]=None,
                x_tenant_code: Optional[str]=Header(None)):
    validate_accounting_dates(from_date, to_date)

    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        result = []
        total_income = 0.0
        total_expenses = 0.0

        accounts = db.execute("""
            SELECT id,code,name,account_type
            FROM accounts
            WHERE is_active=1 AND account_type IN ('income','expense')
            ORDER BY code
        """).fetchall()

        for account in accounts:
            debit, credit, amount = account_movement(
                db, account["id"], account["account_type"],
                start=from_date, end=to_date
            )
            amount = max(0.0, amount)

            if account["account_type"] == "income":
                total_income = money(total_income + amount)
                contribution = amount
            else:
                total_expenses = money(total_expenses + amount)
                contribution = -amount

            if debit or credit or amount:
                result.append({
                    "code": account["code"],
                    "name": account["name"],
                    "account_type": account["account_type"],
                    "debit": debit,
                    "credit": credit,
                    "net": amount,
                    "profit_contribution": contribution,
                })

        net_profit = money(total_income - total_expenses)
        result.append({
            "code": "NET-PROFIT",
            "name": "Net Profit / (Loss)",
            "account_type": "summary",
            "net": net_profit,
            "profit_contribution": net_profit,
            "total_income": total_income,
            "total_expenses": total_expenses,
        })

        return result


@router.get("/accounting/balance-sheet")
def balance_sheet(to_date: Optional[str]=None,
                  x_tenant_code: Optional[str]=Header(None)):
    validate_accounting_dates(to_date=to_date)

    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        result = []
        retained_earnings = 0.0

        accounts = db.execute("""
            SELECT id,code,name,account_type,opening_balance
            FROM accounts
            WHERE is_active=1
              AND account_type IN ('asset','liability','equity')
            ORDER BY code
        """).fetchall()

        for account in accounts:
            typ = account["account_type"]
            debit, credit, movement = account_movement(
                db, account["id"], typ, end=to_date
            )
            balance = money(money(account["opening_balance"]) + movement)

            result.append({
                "code": account["code"],
                "name": account["name"],
                "account_type": typ,
                "normal_side": normal_side(typ),
                "opening_balance": money(account["opening_balance"]),
                "debit": debit,
                "credit": credit,
                "journal_movement": movement,
                "balance": abs(balance),
                "balance_side": (
                    normal_side(typ) if balance >= 0
                    else ("Cr" if normal_side(typ) == "Dr" else "Dr")
                ),
            })

        # Current and accumulated earnings are carried into equity.
        income_accounts = db.execute("""
            SELECT id,account_type,opening_balance FROM accounts
            WHERE is_active=1 AND account_type IN ('income','expense')
        """).fetchall()

        for account in income_accounts:
            _, _, movement = account_movement(
                db, account["id"], account["account_type"], end=to_date
            )
            if account["account_type"] == "income":
                retained_earnings += movement
            else:
                retained_earnings -= movement

        retained_earnings = money(retained_earnings)

        if retained_earnings != 0:
            result.append({
                "code": "3900",
                "name": "Retained Earnings (Accumulated Profit / Loss)",
                "account_type": "equity",
                "normal_side": "Cr",
                "opening_balance": 0,
                "debit": 0,
                "credit": 0,
                "journal_movement": retained_earnings,
                "balance": abs(retained_earnings),
                "balance_side": "Cr" if retained_earnings >= 0 else "Dr",
            })

        return result
