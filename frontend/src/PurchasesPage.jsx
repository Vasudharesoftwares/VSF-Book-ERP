import { useCallback, useEffect, useState } from "react";
import {
  ShoppingCart, FileText, PackageCheck, Receipt, RotateCcw,
  Wallet, RefreshCw, Plus, CheckCircle, BarChart3
} from "lucide-react";

const API = "http://127.0.0.1:8000/api/v1";

const money = value => "₹" + Number(value || 0).toLocaleString("en-IN", {
  minimumFractionDigits: 2, maximumFractionDigits: 2
});

const today = () => new Date().toISOString().slice(0, 10);

const emptyLine = {
  product_id: "", quantity: 1, unit_cost: 0, gst_rate: 0,
  discount_amount: 0
};

export default function PurchasesPage({ tenant }) {
  const [tab, setTab] = useState("Dashboard");
  const [dashboard, setDashboard] = useState({});
  const [lookups, setLookups] = useState({ suppliers: [], products: [] });
  const [orders, setOrders] = useState([]);
  const [receipts, setReceipts] = useState([]);
  const [invoices, setInvoices] = useState([]);
  const [reports, setReports] = useState({ monthly: [], suppliers: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [showForm, setShowForm] = useState(false);

  const [orderForm, setOrderForm] = useState({
    supplier_id: "", order_date: today(), expected_date: "", notes: "",
    item: { ...emptyLine }
  });

  const [receiptForm, setReceiptForm] = useState({
    supplier_id: "", purchase_order_id: "", receipt_date: today(),
    product_id: "", purchase_order_item_id: "",
    received_quantity: 1, accepted_quantity: 1,
    rejected_quantity: 0, unit_cost: 0, notes: ""
  });

  const [invoiceForm, setInvoiceForm] = useState({
    supplier_id: "", invoice_date: today(), supplier_invoice_no: "",
    paid_amount: 0, payment_method: "cash", notes: "",
    item: { ...emptyLine }
  });

  const [paymentForm, setPaymentForm] = useState({
    purchase_id: "", amount: "", payment_method: "cash",
    payment_date: today(), reference_no: "", notes: ""
  });

  const [returnForm, setReturnForm] = useState({
    supplier_id: "", purchase_id: "", return_date: today(),
    reason: "", product_id: "", quantity: 1, unit_cost: 0
  });

  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Code": tenant
  };

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(API + path, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed.");
    return data;
  }, [tenant]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [d, l, o, g, p, r] = await Promise.all([
        request("/purchases/dashboard"),
        request("/purchases/lookups"),
        request("/purchase-orders"),
        request("/goods-receipts"),
        request("/purchases"),
        request("/purchase-reports")
      ]);
      setDashboard(d);
      setLookups(l);
      setOrders(o.orders || []);
      setReceipts(g.receipts || []);
      setInvoices(p.purchases || []);
      setReports(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [request]);

  useEffect(() => { refresh(); }, [refresh]);

  const supplierOptions = lookups.suppliers || [];
  const productOptions = lookups.products || [];

  const supplierName = id =>
    supplierOptions.find(x => Number(x.id) === Number(id))?.name || "Supplier";

  const productName = id =>
    productOptions.find(x => Number(x.id) === Number(id))?.name || "Product";

  function notify(text) {
    setMessage(text);
    setError("");
    setShowForm(false);
    refresh();
  }

  async function submit(path, body, success) {
    setError("");
    setMessage("");
    try {
      const result = await request(path, {
        method: "POST",
        body: JSON.stringify(body)
      });
      notify(result.message || success);
    } catch (e) {
      setError(e.message);
    }
  }

  function changeLine(setter, key, value) {
    setter(previous => ({
      ...previous,
      item: { ...previous.item, [key]: value }
    }));
  }

  async function loadOrderItems(orderId) {
    if (!orderId) {
      setReceiptForm(previous => ({
        ...previous, purchase_order_id: "", purchase_order_item_id: "",
        product_id: ""
      }));
      return;
    }
    try {
      const order = await request(`/purchase-orders/${orderId}`);
      setReceiptForm(previous => ({
        ...previous,
        purchase_order_id: String(orderId),
        supplier_id: String(order.supplier_id),
        purchase_order_item_id: "",
        product_id: ""
      }));
      setSelectedOrderItems(order.items || []);
    } catch (e) {
      setError(e.message);
    }
  }

  const [selectedOrderItems, setSelectedOrderItems] = useState([]);

  function openForm(name) {
    setError("");
    setMessage("");
    setShowForm(name);
  }

  const tabs = [
    ["Dashboard", BarChart3],
    ["Purchase Orders", ShoppingCart],
    ["Goods Receipts", PackageCheck],
    ["Purchase Invoices", FileText],
    ["Supplier Payments", Wallet],
    ["Purchase Returns", RotateCcw],
    ["Reports", Receipt]
  ];

  return (
    <div className="purchase-module">
      <div className="welcome-row">
        <div>
          <div className="eyebrow">PURCHASING & SUPPLIER MANAGEMENT</div>
          <h1>Purchases</h1>
          <p>Purchase orders, incoming stock, supplier invoices and payments.</p>
        </div>
        <button className="secondary-action" onClick={refresh} disabled={loading}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>

      <div className="purchase-tabs">
        {tabs.map(([name, Icon]) => (
          <button key={name}
            className={tab === name ? "purchase-tab active" : "purchase-tab"}
            onClick={() => { setTab(name); setShowForm(false); setError(""); setMessage(""); }}>
            <Icon size={16} /> {name}
          </button>
        ))}
      </div>

      {error && <div className="error-message">{error}</div>}
      {message && <div className="success-message"><CheckCircle size={16} />{message}</div>}
      {loading && <p className="purchase-loading">Loading purchase data...</p>}

      {tab === "Dashboard" && (
        <>
          <div className="stats-grid">
            {[
              ["Purchase Orders", dashboard.purchase_orders, ShoppingCart],
              ["Open Orders", dashboard.open_orders, FileText],
              ["Goods Receipts", dashboard.goods_receipts, PackageCheck],
              ["Purchase Invoices", dashboard.purchase_invoices, Receipt],
              ["Purchase Value", money(dashboard.purchase_value), BarChart3],
              ["Supplier Payable", money(dashboard.supplier_payable), Wallet],
              ["Purchase Returns", dashboard.returns, RotateCcw]
            ].map(([label, value, Icon]) => (
              <div className="stat-card" key={label}>
                <div className="stat-top"><span>{label}</span><span className="stat-icon"><Icon size={17}/></span></div>
                <strong>{value ?? "—"}</strong>
              </div>
            ))}
          </div>

          <div className="data-panel">
            <div className="section-title"><div><h2>Recent purchase invoices</h2><p>Latest supplier bills for this demo database.</p></div></div>
            <InvoiceTable invoices={invoices.slice(0, 8)} />
          </div>
        </>
      )}

      {tab === "Purchase Orders" && (
        <>
          <div className="purchase-toolbar">
            <div><h2>Purchase Orders</h2><p>Creating an order does not increase stock.</p></div>
            <button className="primary-action" onClick={() => openForm("order")}><Plus size={16}/> New Order</button>
          </div>
          {showForm === "order" && (
            <div className="data-panel">
              <h2>Create Purchase Order</h2>
              <form onSubmit={e => {
                e.preventDefault();
                submit("/purchase-orders", {
                  supplier_id: Number(orderForm.supplier_id),
                  order_date: orderForm.order_date,
                  expected_date: orderForm.expected_date || null,
                  notes: orderForm.notes,
                  items: [{
                    product_id: Number(orderForm.item.product_id),
                    quantity: Number(orderForm.item.quantity),
                    unit_cost: Number(orderForm.item.unit_cost),
                    gst_rate: Number(orderForm.item.gst_rate)
                  }]
                }, "Purchase order created.");
              }}>
                <div className="form-grid">
                  <label>Supplier<select required value={orderForm.supplier_id} onChange={e=>setOrderForm({...orderForm,supplier_id:e.target.value})}>
                    <option value="">Select supplier</option>{supplierOptions.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
                  </select></label>
                  <label>Order date<input type="date" value={orderForm.order_date} onChange={e=>setOrderForm({...orderForm,order_date:e.target.value})}/></label>
                  <label>Expected date<input type="date" value={orderForm.expected_date} onChange={e=>setOrderForm({...orderForm,expected_date:e.target.value})}/></label>
                  <label>Product<select required value={orderForm.item.product_id} onChange={e=>changeLine(setOrderForm,"product_id",e.target.value)}>
                    <option value="">Select product</option>{productOptions.map(p=><option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}
                  </select></label>
                  <label>Quantity<input type="number" min="0.001" step="any" required value={orderForm.item.quantity} onChange={e=>changeLine(setOrderForm,"quantity",e.target.value)}/></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={orderForm.item.unit_cost} onChange={e=>changeLine(setOrderForm,"unit_cost",e.target.value)}/></label>
                  <label>GST %<input type="number" min="0" step="0.01" value={orderForm.item.gst_rate} onChange={e=>changeLine(setOrderForm,"gst_rate",e.target.value)}/></label>
                  <label>Notes<input value={orderForm.notes} onChange={e=>setOrderForm({...orderForm,notes:e.target.value})}/></label>
                </div>
                <div className="purchase-form-actions"><button className="primary-action">Save Purchase Order</button><button type="button" className="secondary-action" onClick={()=>setShowForm(false)}>Cancel</button></div>
              </form>
            </div>
          )}
          <div className="data-panel"><PurchaseOrderTable orders={orders}/></div>
        </>
      )}

      {tab === "Goods Receipts" && (
        <>
          <div className="purchase-toolbar">
            <div><h2>Goods Receipts</h2><p>Only accepted quantities are added to inventory.</p></div>
            <button className="primary-action" onClick={()=>openForm("receipt")}><Plus size={16}/> Record Receipt</button>
          </div>
          {showForm === "receipt" && (
            <div className="data-panel">
              <h2>Record Incoming Goods</h2>
              <form onSubmit={e=>{
                e.preventDefault();
                submit("/goods-receipts",{
                  supplier_id:Number(receiptForm.supplier_id),
                  purchase_order_id:receiptForm.purchase_order_id ? Number(receiptForm.purchase_order_id) : null,
                  receipt_date:receiptForm.receipt_date,
                  notes:receiptForm.notes,
                  items:[{
                    product_id:Number(receiptForm.product_id),
                    purchase_order_item_id:receiptForm.purchase_order_item_id ? Number(receiptForm.purchase_order_item_id) : null,
                    received_quantity:Number(receiptForm.received_quantity),
                    accepted_quantity:Number(receiptForm.accepted_quantity),
                    rejected_quantity:Number(receiptForm.rejected_quantity),
                    unit_cost:Number(receiptForm.unit_cost)
                  }]
                },"Goods receipt saved as draft.");
              }}>
                <div className="form-grid">
                  <label>Purchase order (optional)<select value={receiptForm.purchase_order_id} onChange={e=>loadOrderItems(e.target.value)}>
                    <option value="">Direct / no purchase order</option>{orders.filter(o=>!["received","cancelled"].includes(o.status)).map(o=><option key={o.id} value={o.id}>{o.po_no} — {o.supplier_name}</option>)}
                  </select></label>
                  <label>Supplier<select required disabled={!!receiptForm.purchase_order_id} value={receiptForm.supplier_id} onChange={e=>setReceiptForm({...receiptForm,supplier_id:e.target.value})}>
                    <option value="">Select supplier</option>{supplierOptions.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}
                  </select></label>
                  <label>Receipt date<input type="date" value={receiptForm.receipt_date} onChange={e=>setReceiptForm({...receiptForm,receipt_date:e.target.value})}/></label>
                  <label>Product<select required value={receiptForm.purchase_order_item_id || receiptForm.product_id} onChange={e=>{
                    if(receiptForm.purchase_order_id){
                      const item=selectedOrderItems.find(x=>String(x.id)===e.target.value);
                      setReceiptForm({...receiptForm,purchase_order_item_id:e.target.value,product_id:item?String(item.product_id):"",unit_cost:item?.unit_cost||0});
                    } else setReceiptForm({...receiptForm,product_id:e.target.value});
                  }}>
                    <option value="">Select product</option>
                    {(receiptForm.purchase_order_id ? selectedOrderItems.map(i=>({...i, name:i.product_name, sku:i.sku})) : productOptions).map(p=><option key={receiptForm.purchase_order_id?p.id:p.id} value={receiptForm.purchase_order_id?p.id:p.id}>{p.name} {p.sku ? `(${p.sku})` : ""}</option>)}
                  </select></label>
                  <label>Received quantity<input type="number" min="0.001" step="any" required value={receiptForm.received_quantity} onChange={e=>setReceiptForm({...receiptForm,received_quantity:e.target.value})}/></label>
                  <label>Accepted quantity<input type="number" min="0" step="any" required value={receiptForm.accepted_quantity} onChange={e=>setReceiptForm({...receiptForm,accepted_quantity:e.target.value})}/></label>
                  <label>Rejected quantity<input type="number" min="0" step="any" value={receiptForm.rejected_quantity} onChange={e=>setReceiptForm({...receiptForm,rejected_quantity:e.target.value})}/></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" value={receiptForm.unit_cost} onChange={e=>setReceiptForm({...receiptForm,unit_cost:e.target.value})}/></label>
                  <label>Notes<input value={receiptForm.notes} onChange={e=>setReceiptForm({...receiptForm,notes:e.target.value})}/></label>
                </div>
                <p className="purchase-hint">Accepted + rejected quantity must equal received quantity. Saving a draft does not change stock.</p>
                <div className="purchase-form-actions"><button className="primary-action">Save Receipt Draft</button><button type="button" className="secondary-action" onClick={()=>setShowForm(false)}>Cancel</button></div>
              </form>
            </div>
          )}
          <div className="data-panel">
            <table className="erp-table"><thead><tr><th>Receipt</th><th>Date</th><th>Supplier</th><th>Received</th><th>Accepted</th><th>Status</th><th>Action</th></tr></thead>
              <tbody>{receipts.map(r=><tr key={r.id}><td>{r.receipt_no}</td><td>{r.receipt_date}</td><td>{r.supplier_name}</td><td>{r.received_quantity}</td><td>{r.accepted_quantity}</td><td><Status value={r.status}/></td><td>{r.status==="draft" ? <button className="secondary-action" onClick={()=>submit(`/goods-receipts/${r.id}/accept`,{},"Receipt accepted.")}>Accept & Post Stock</button> : "—"}</td></tr>)}</tbody></table>
            {!receipts.length&&<div className="empty-state">No goods receipts found.</div>}
          </div>
        </>
      )}

      {tab === "Purchase Invoices" && (
        <>
          <div className="purchase-toolbar"><div><h2>Purchase Invoices</h2><p>Direct purchases create invoices and post stock.</p></div><button className="primary-action" onClick={()=>openForm("invoice")}><Plus size={16}/> New Invoice</button></div>
          {showForm === "invoice" && (
            <div className="data-panel"><h2>Create Direct Purchase Invoice</h2>
              <form onSubmit={e=>{
                e.preventDefault();
                submit("/purchases/direct",{
                  supplier_id:Number(invoiceForm.supplier_id),
                  invoice_date:invoiceForm.invoice_date,
                  supplier_invoice_no:invoiceForm.supplier_invoice_no,
                  paid_amount:Number(invoiceForm.paid_amount),
                  payment_method:invoiceForm.payment_method,
                  notes:invoiceForm.notes,
                  items:[{
                    product_id:Number(invoiceForm.item.product_id),
                    quantity:Number(invoiceForm.item.quantity),
                    unit_cost:Number(invoiceForm.item.unit_cost),
                    gst_rate:Number(invoiceForm.item.gst_rate),
                    discount_amount:Number(invoiceForm.item.discount_amount)
                  }]
                },"Purchase invoice created.");
              }}>
                <div className="form-grid">
                  <label>Supplier<select required value={invoiceForm.supplier_id} onChange={e=>setInvoiceForm({...invoiceForm,supplier_id:e.target.value})}><option value="">Select supplier</option>{supplierOptions.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
                  <label>Invoice date<input type="date" value={invoiceForm.invoice_date} onChange={e=>setInvoiceForm({...invoiceForm,invoice_date:e.target.value})}/></label>
                  <label>Supplier invoice number<input value={invoiceForm.supplier_invoice_no} onChange={e=>setInvoiceForm({...invoiceForm,supplier_invoice_no:e.target.value})}/></label>
                  <label>Product<select required value={invoiceForm.item.product_id} onChange={e=>changeLine(setInvoiceForm,"product_id",e.target.value)}><option value="">Select product</option>{productOptions.map(p=><option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}</select></label>
                  <label>Quantity<input type="number" min="0.001" step="any" required value={invoiceForm.item.quantity} onChange={e=>changeLine(setInvoiceForm,"quantity",e.target.value)}/></label>
                  <label>Unit cost<input type="number" min="0" step="0.01" required value={invoiceForm.item.unit_cost} onChange={e=>changeLine(setInvoiceForm,"unit_cost",e.target.value)}/></label>
                  <label>GST %<input type="number" min="0" step="0.01" value={invoiceForm.item.gst_rate} onChange={e=>changeLine(setInvoiceForm,"gst_rate",e.target.value)}/></label>
                  <label>Discount amount<input type="number" min="0" step="0.01" value={invoiceForm.item.discount_amount} onChange={e=>changeLine(setInvoiceForm,"discount_amount",e.target.value)}/></label>
                  <label>Paid amount<input type="number" min="0" step="0.01" value={invoiceForm.paid_amount} onChange={e=>setInvoiceForm({...invoiceForm,paid_amount:e.target.value})}/></label>
                  <label>Payment method<select value={invoiceForm.payment_method} onChange={e=>setInvoiceForm({...invoiceForm,payment_method:e.target.value})}>{["cash","upi","card","bank_transfer","cheque","credit","other"].map(x=><option key={x} value={x}>{x.replace("_"," ")}</option>)}</select></label>
                  <label>Notes<input value={invoiceForm.notes} onChange={e=>setInvoiceForm({...invoiceForm,notes:e.target.value})}/></label>
                </div>
                <p className="purchase-hint">Posting this invoice adds the purchased quantity to stock immediately.</p>
                <div className="purchase-form-actions"><button className="primary-action">Save & Post Invoice</button><button type="button" className="secondary-action" onClick={()=>setShowForm(false)}>Cancel</button></div>
              </form>
            </div>
          )}
          <div className="data-panel"><InvoiceTable invoices={invoices}/></div>
        </>
      )}

      {tab === "Supplier Payments" && (
        <>
          <div className="purchase-toolbar"><div><h2>Supplier Payments</h2><p>Record payments against outstanding purchase invoices.</p></div></div>
          <div className="data-panel"><h2>Record Supplier Payment</h2>
            <form onSubmit={e=>{e.preventDefault();submit("/purchases/payments",{
              purchase_id:Number(paymentForm.purchase_id),amount:Number(paymentForm.amount),
              payment_method:paymentForm.payment_method,payment_date:paymentForm.payment_date,
              reference_no:paymentForm.reference_no,notes:paymentForm.notes
            },"Supplier payment recorded.");}}>
              <div className="form-grid">
                <label>Purchase invoice<select required value={paymentForm.purchase_id} onChange={e=>setPaymentForm({...paymentForm,purchase_id:e.target.value})}><option value="">Select outstanding invoice</option>{invoices.filter(p=>Number(p.balance_amount)>0).map(p=><option key={p.id} value={p.id}>{p.invoice_no} — {p.supplier_name} — Due {money(p.balance_amount)}</option>)}</select></label>
                <label>Payment amount<input type="number" min="0.01" step="0.01" required value={paymentForm.amount} onChange={e=>setPaymentForm({...paymentForm,amount:e.target.value})}/></label>
                <label>Payment date<input type="date" value={paymentForm.payment_date} onChange={e=>setPaymentForm({...paymentForm,payment_date:e.target.value})}/></label>
                <label>Payment method<select value={paymentForm.payment_method} onChange={e=>setPaymentForm({...paymentForm,payment_method:e.target.value})}>{["cash","upi","card","bank_transfer","cheque","credit","other"].map(x=><option key={x}>{x}</option>)}</select></label>
                <label>Reference number<input value={paymentForm.reference_no} onChange={e=>setPaymentForm({...paymentForm,reference_no:e.target.value})}/></label>
                <label>Notes<input value={paymentForm.notes} onChange={e=>setPaymentForm({...paymentForm,notes:e.target.value})}/></label>
              </div>
              <div className="purchase-form-actions"><button className="primary-action">Record Payment</button></div>
            </form>
          </div>
          <div className="data-panel"><h2>Outstanding Invoices</h2><InvoiceTable invoices={invoices.filter(p=>Number(p.balance_amount)>0)}/></div>
        </>
      )}

      {tab === "Purchase Returns" && (
        <>
          <div className="purchase-toolbar"><div><h2>Purchase Returns</h2><p>Post a return to reduce stock. Linked invoice quantities are validated.</p></div></div>
          <div className="data-panel"><h2>Create & Post Purchase Return</h2>
            <form onSubmit={async e=>{
              e.preventDefault();
              setError("");setMessage("");
              try {
                const created=await request("/purchase-returns",{
                  method:"POST",body:JSON.stringify({
                    supplier_id:Number(returnForm.supplier_id),
                    purchase_id:returnForm.purchase_id?Number(returnForm.purchase_id):null,
                    return_date:returnForm.return_date,reason:returnForm.reason,
                    items:[{product_id:Number(returnForm.product_id),quantity:Number(returnForm.quantity),unit_cost:Number(returnForm.unit_cost)}]
                  })
                });
                const posted=await request(`/purchase-returns/${created.id}/post`,{method:"POST",body:"{}"});
                notify(posted.message || "Purchase return posted.");
              } catch(err) { setError(err.message); }
            }}>
              <div className="form-grid">
                <label>Supplier<select required value={returnForm.supplier_id} onChange={e=>setReturnForm({...returnForm,supplier_id:e.target.value,purchase_id:""})}><option value="">Select supplier</option>{supplierOptions.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
                <label>Related purchase invoice (optional)<select value={returnForm.purchase_id} onChange={e=>{
                  const p=invoices.find(x=>String(x.id)===e.target.value);
                  setReturnForm({...returnForm,purchase_id:e.target.value,product_id:"",unit_cost:0});
                }}><option value="">Not linked to invoice</option>{invoices.filter(p=>String(p.supplier_id)===String(returnForm.supplier_id)).map(p=><option key={p.id} value={p.id}>{p.invoice_no}</option>)}</select></label>
                <label>Return date<input type="date" value={returnForm.return_date} onChange={e=>setReturnForm({...returnForm,return_date:e.target.value})}/></label>
                <label>Product<select required value={returnForm.product_id} onChange={e=>setReturnForm({...returnForm,product_id:e.target.value})}><option value="">Select product</option>{productOptions.map(p=><option key={p.id} value={p.id}>{p.name} ({p.sku})</option>)}</select></label>
                <label>Quantity<input type="number" min="0.001" step="any" required value={returnForm.quantity} onChange={e=>setReturnForm({...returnForm,quantity:e.target.value})}/></label>
                <label>Unit cost<input type="number" min="0" step="0.01" value={returnForm.unit_cost} onChange={e=>setReturnForm({...returnForm,unit_cost:e.target.value})}/></label>
                <label>Reason<input value={returnForm.reason} onChange={e=>setReturnForm({...returnForm,reason:e.target.value})}/></label>
              </div>
              <p className="purchase-hint">This action posts the return immediately and reduces available stock. Check the details before submitting.</p>
              <div className="purchase-form-actions"><button className="primary-action">Create & Post Return</button></div>
            </form>
          </div>
        </>
      )}

      {tab === "Reports" && (
        <>
          <div className="data-panel"><h2>Monthly Purchase Summary</h2>
            <table className="erp-table"><thead><tr><th>Month</th><th>Invoices</th><th>Total</th><th>Paid</th><th>Outstanding</th></tr></thead>
              <tbody>{reports.monthly.map((r,i)=><tr key={r.month||i}><td>{r.month}</td><td>{r.invoices}</td><td>{money(r.total)}</td><td>{money(r.paid)}</td><td>{money(r.outstanding)}</td></tr>)}</tbody></table>
            {!reports.monthly.length&&<div className="empty-state">No purchase report data available.</div>}
          </div>
          <div className="data-panel"><h2>Supplier Purchase Summary</h2>
            <table className="erp-table"><thead><tr><th>Supplier</th><th>Invoices</th><th>Purchase Value</th><th>Outstanding</th></tr></thead>
              <tbody>{reports.suppliers.map(s=><tr key={s.id}><td>{s.name}</td><td>{s.invoices}</td><td>{money(s.purchase_value)}</td><td>{money(s.outstanding)}</td></tr>)}</tbody></table>
            {!reports.suppliers.length&&<div className="empty-state">No suppliers found.</div>}
          </div>
        </>
      )}
    </div>
  );
}

function Status({ value }) {
  return <span className={`purchase-status ${value === "accepted" || value === "paid" || value === "received" ? "good" : ""}`}>{value || "—"}</span>;
}

function InvoiceTable({ invoices }) {
  return <>
    <table className="erp-table"><thead><tr><th>Invoice</th><th>Date</th><th>Supplier</th><th>Total</th><th>Paid</th><th>Balance</th><th>Status</th></tr></thead>
      <tbody>{invoices.map(p=><tr key={p.id}><td>{p.invoice_no}</td><td>{p.invoice_date}</td><td>{p.supplier_name}</td><td>{money(p.grand_total)}</td><td>{money(p.paid_amount)}</td><td>{money(p.balance_amount)}</td><td><Status value={p.status}/></td></tr>)}</tbody></table>
    {!invoices.length&&<div className="empty-state">No purchase invoices found.</div>}
  </>;
}

function PurchaseOrderTable({ orders }) {
  return <>
    <table className="erp-table"><thead><tr><th>Order</th><th>Date</th><th>Supplier</th><th>Items</th><th>Ordered Qty</th><th>Received Qty</th><th>Status</th></tr></thead>
      <tbody>{orders.map(o=><tr key={o.id}><td>{o.po_no}</td><td>{o.order_date}</td><td>{o.supplier_name}</td><td>{o.item_count}</td><td>{o.ordered_quantity}</td><td>{o.received_quantity}</td><td><Status value={o.status}/></td></tr>)}</tbody></table>
    {!orders.length&&<div className="empty-state">No purchase orders found.</div>}
  </>;
}
