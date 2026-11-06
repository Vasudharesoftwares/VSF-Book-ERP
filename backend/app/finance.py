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
      ("2100","Output CGST","liability"),
      ("2110","Output SGST","liability"),
      ("2120","Output IGST","liability"),
      ("3000","Capital","equity"),
      ("4000","Sales Revenue","income"),
      ("4100","Other Income","income"),
      ("5000","Purchases","expense"),
      ("5100","Operating Expenses","expense"),
    ]
    for code,name,typ in defaults:
        db.execute("""INSERT OR IGNORE INTO accounts
        (code,name,account_type) VALUES(?,?,?)""",(code,name,typ))
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

@router.get("/gst/dashboard")
def gst_dashboard(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        sales=db.execute("""SELECT
          COALESCE(SUM(taxable_amount),0) taxable,
          COALESCE(SUM(cgst),0) cgst,
          COALESCE(SUM(sgst),0) sgst,
          COALESCE(SUM(igst),0) igst,
          COALESCE(SUM(tax),0) tax,
          COALESCE(SUM(invoices),0) invoices
          FROM (
            SELECT taxable_amount,cgst,sgst,igst,total_tax AS tax,1 AS invoices
            FROM sales
            WHERE LOWER(COALESCE(status,'')) NOT IN ('draft','cancelled','cancel')
            UNION ALL
            SELECT taxable_amount,cgst,sgst,igst,total_tax AS tax,1 AS invoices
            FROM sale_invoices
          )""").fetchone()
        purchases=db.execute("""SELECT
          COALESCE(SUM(taxable_amount),0) taxable,
          COALESCE(SUM(cgst),0) cgst,
          COALESCE(SUM(sgst),0) sgst,
          COALESCE(SUM(igst),0) igst,
          COALESCE(SUM(total_tax),0) tax,
          COUNT(*) invoices
          FROM purchases WHERE LOWER(COALESCE(status,'')) NOT IN
          ('draft','cancelled','cancel')""").fetchone()
        return {
          "sales":dict(sales),"purchases":dict(purchases),
          "output_tax":money(sales["tax"]),
          "input_tax":money(purchases["tax"]),
          "net_tax":money(sales["tax"]-purchases["tax"])
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
        SELECT hsn, gst_rate,
               SUM(quantity) quantity,
               SUM(taxable_value) taxable_value,
               SUM(tax_value) tax_value
        FROM (
            SELECT COALESCE(p.hsn_code,'UNSPECIFIED') hsn,
                   COALESCE(i.gst_rate,0) gst_rate,
                   i.quantity quantity,
                   i.taxable_amount taxable_value,
                   i.tax_amount tax_value
            FROM purchase_items i
            JOIN purchases t ON t.id=i.purchase_id
            LEFT JOIN products p ON p.id=i.product_id
            WHERE LOWER(COALESCE(t.status,'')) NOT IN
                  ('draft','cancelled','cancel')

            UNION ALL

            SELECT COALESCE(NULLIF(i.hsn_code,''),'UNSPECIFIED') hsn,
                   COALESCE(i.gst_rate,0) gst_rate,
                   i.quantity quantity,
                   i.taxable_amount taxable_value,
                   i.gst_amount tax_value
            FROM sale_invoice_items i
            JOIN sale_invoices t ON t.id=i.invoice_id
        )
        GROUP BY hsn,gst_rate
        ORDER BY hsn
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

@router.get("/accounting/trial-balance")
def trial_balance(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
        SELECT a.id,a.code,a.name,a.account_type,
        COALESCE(SUM(l.debit),0) debit,
        COALESCE(SUM(l.credit),0) credit,
        a.opening_balance
        FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
        LEFT JOIN journal_vouchers v ON v.id=l.voucher_id
        AND v.status='posted'
        WHERE a.is_active=1
        GROUP BY a.id ORDER BY a.code
        """).fetchall()]

@router.get("/accounting/ledger/{account_id}")
def account_ledger(account_id: int,
                   x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
        SELECT v.voucher_no,v.voucher_date,v.voucher_type,
        v.narration,l.debit,l.credit,l.narration line_narration
        FROM journal_lines l JOIN journal_vouchers v ON v.id=l.voucher_id
        WHERE l.account_id=? AND v.status='posted'
        ORDER BY v.voucher_date,v.id
        """,(account_id,)).fetchall()]

@router.get("/accounting/profit-loss")
def profit_loss(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
        SELECT a.code,a.name,a.account_type,
        SUM(l.credit)-SUM(l.debit) net
        FROM accounts a JOIN journal_lines l ON l.account_id=a.id
        JOIN journal_vouchers v ON v.id=l.voucher_id
        WHERE a.account_type IN ('income','expense') AND v.status='posted'
        GROUP BY a.id ORDER BY a.code
        """).fetchall()]

@router.get("/accounting/balance-sheet")
def balance_sheet(x_tenant_code: Optional[str]=Header(None)):
    with tenant_connection(tenant(x_tenant_code)) as db:
        setup(db)
        return [dict(r) for r in db.execute("""
        SELECT a.code,a.name,a.account_type,
        SUM(l.debit)-SUM(l.credit) balance
        FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id
        LEFT JOIN journal_vouchers v ON v.id=l.voucher_id
        AND v.status='posted'
        WHERE a.account_type IN ('asset','liability','equity')
        GROUP BY a.id ORDER BY a.code
        """).fetchall()]
