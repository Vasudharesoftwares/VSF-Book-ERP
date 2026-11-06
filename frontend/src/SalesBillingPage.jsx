import { useCallback, useEffect, useMemo, useState } from "react";
import { Search, Plus, Minus, Trash2, Printer, Receipt, History, ShoppingCart, RefreshCw } from "lucide-react";
import { alerts } from "./utils/alerts";

const API = "http://127.0.0.1:8000/api/v1";
const money = n => Number(n || 0).toLocaleString("en-IN", {
  minimumFractionDigits: 2, maximumFractionDigits: 2
});

export default function SalesBillingPage({ tenant }) {
  const [tab, setTab] = useState("new");
  const [search, setSearch] = useState("");
  const [products, setProducts] = useState([]);
  const [cart, setCart] = useState([]);
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerStateCode, setCustomerStateCode] = useState("");
  const [gstSettings, setGstSettings] = useState(null);
  const [discount, setDiscount] = useState("0");
  const [paymentMode, setPaymentMode] = useState("cash");
  const [paid, setPaid] = useState("");
  const [customFields, setCustomFields] = useState([]);
  const [customValues, setCustomValues] = useState({});
  const [sales, setSales] = useState([]);
  const [historySearch, setHistorySearch] = useState("");
  const [selectedInvoice, setSelectedInvoice] = useState(null);
  const [busy, setBusy] = useState(false);

  const headers = useMemo(() => ({
    "Content-Type": "application/json",
    "X-Tenant-Code": tenant
  }), [tenant]);

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(API + path, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed.");
    return data;
  }, [headers]);

  const loadProducts = useCallback(async (term = "") => {
    try {
      const data = await request("/sales/products?search=" + encodeURIComponent(term));
      setProducts(data.products || []);
    } catch (e) {
      alerts.error(e.message);
    }
  }, [request]);

  const loadSales = useCallback(async (term = "") => {
    try {
      const data = await request("/sales?search=" + encodeURIComponent(term));
      setSales(data.sales || []);
    } catch (e) {
      alerts.error(e.message);
    }
  }, [request]);

  useEffect(() => {
    loadProducts("");
    request("/gst/settings")
      .then(data => setGstSettings(data))
      .catch(() => setGstSettings(null));
    request("/custom-fields?module_key=sales")
      .then(data => setCustomFields((data.fields || []).filter(f => f.is_active)))
      .catch(() => setCustomFields([]));
  }, [tenant, loadProducts, request]);

  useEffect(() => {
    if (tab === "history") loadSales(historySearch);
  }, [tab, historySearch, loadSales]);

  const addProduct = async product => {
    try {
      // Recheck live stock instead of relying on an old search result.
      const latest = await request(
        "/sales/products?search=" + encodeURIComponent(product.sku || product.name)
      );
      const fresh = (latest.products || []).find(
        item => Number(item.id) === Number(product.id)
      );

      if (!fresh) {
        await alerts.error("This book could not be found. Please refresh the product search.");
        return;
      }

      const availableStock = Number(fresh.stock || 0);

      if (availableStock <= 0) {
        await alerts.error("This book is out of stock in the main branch.");
        await loadProducts(search);
        return;
      }

      setCart(old => {
        const found = old.find(x => Number(x.id) === Number(fresh.id));

        if (found) {
          if (found.quantity + 1 > availableStock) {
            alerts.error("Not enough stock available. Current stock: " + availableStock);
            return old;
          }
          return old.map(x => Number(x.id) === Number(fresh.id)
            ? { ...x, quantity: x.quantity + 1, stock: availableStock }
            : x
          );
        }

        return [...old, {
          id: fresh.id,
          name: fresh.name,
          sku: fresh.sku,
          price: Number(fresh.selling_price || 0),
          gst: Number(fresh.gst_rate || 0),
          stock: availableStock,
          quantity: 1,
          discount_percent: 0
        }];
      });
    } catch (e) {
      await alerts.error(e);
    }
  };

  const updateItem = (id, changes) => setCart(old =>
    old.map(x => x.id === id ? { ...x, ...changes } : x)
  );

  const totals = useMemo(() => {
    const roundMoney = value => Math.round((Number(value || 0) + Number.EPSILON) * 100) / 100;
    const subtotal = cart.reduce((sum, x) => {
      const gross = x.price * x.quantity;
      return sum + gross - gross * Number(x.discount_percent || 0) / 100;
    }, 0);
    const billDiscount = Math.min(Math.max(Number(discount) || 0, 0), subtotal);
    const factor = subtotal ? (subtotal - billDiscount) / subtotal : 0;

    const businessCode = String(gstSettings?.state_code || "").trim();
    const customerCode = String(customerStateCode || "").trim();
    const interstate = Boolean(
      businessCode && customerCode &&
      businessCode.toLowerCase() !== customerCode.toLowerCase()
    );

    let taxable = 0;
    let cgst = 0;
    let sgst = 0;
    let igst = 0;

    cart.forEach(x => {
      const gross = x.price * x.quantity;
      const afterItemDiscount = gross - gross * Number(x.discount_percent || 0) / 100;
      const lineTaxable = roundMoney(afterItemDiscount * factor);
      const lineGst = roundMoney(lineTaxable * Number(x.gst || 0) / 100);

      taxable += lineTaxable;

      if (interstate) {
        igst += lineGst;
      } else {
        const lineCgst = roundMoney(lineGst / 2);
        cgst += lineCgst;
        sgst += roundMoney(lineGst - lineCgst);
      }
    });

    taxable = roundMoney(taxable);
    cgst = roundMoney(cgst);
    sgst = roundMoney(sgst);
    igst = roundMoney(igst);
    const gst = roundMoney(cgst + sgst + igst);

    return {
      subtotal: roundMoney(subtotal),
      discount: roundMoney(billDiscount),
      taxable, cgst, sgst, igst, gst,
      interstate,
      total: roundMoney(taxable + gst)
    };
  }, [cart, discount, gstSettings, customerStateCode]);

  const saveSale = async () => {
    if (!cart.length) return alerts.error("Add at least one product.");
    const paidAmount = paid === "" ? totals.total : Number(paid);
    if (!Number.isFinite(paidAmount) || paidAmount < 0 || paidAmount > totals.total + 0.001) {
      return alerts.error("Enter a valid payment amount.");
    }
    if (customFields.some(f => f.is_required && (
      customValues[f.field_key] === undefined ||
      customValues[f.field_key] === "" ||
      customValues[f.field_key] === null
    ))) return alerts.error("Please complete all required custom fields.");

    const confirmed = await alerts.confirm(
      "Complete this sale?",
      "The invoice will be saved and stock will be reduced."
    );
    if (!confirmed) return;

    setBusy(true);
    try {
      const result = await request("/sales", {
        method: "POST",
        body: JSON.stringify({
          customer_name: customerName,
          customer_phone: customerPhone,
          customer_state_code: customerStateCode,
          items: cart.map(x => ({
            product_id: x.id,
            quantity: x.quantity,
            discount_percent: Number(x.discount_percent || 0)
          })),
          bill_discount: Number(discount || 0),
          paid_amount: paidAmount,
          payment_mode: paymentMode,
          custom_fields: customValues
        })
      });
      const invoice = await request("/sales/" + result.invoice_id);
      setSelectedInvoice(invoice);
      setCart([]);
      setCustomerName("");
      setCustomerPhone("");
      setCustomerStateCode("");
      setDiscount("0");
      setPaid("");
      setCustomValues({});
      await loadProducts(search);
      await loadSales();
      await alerts.success("Invoice " + result.invoice_number + " saved successfully.");
      setTab("history");
    } catch (e) {
      alerts.error(e.message);
    } finally {
      setBusy(false);
    }
  };

  const openInvoice = async id => {
    try {
      setSelectedInvoice(await request("/sales/" + id));
    } catch (e) {
      alerts.error(e.message);
    }
  };

  const printInvoice = invoice => {
    if (!invoice) return;
    const rows = (invoice.items || []).map(item => `
      <tr>
        <td>${escapeHtml(item.product_name)}</td>
        <td>${item.quantity}</td>
        <td>₹${money(item.unit_price)}</td>
        <td>₹${money(item.line_total)}</td>
      </tr>`).join("");
    const html = `<!doctype html><html><head><title>${escapeHtml(invoice.invoice_number)}</title>
      <style>
      body{font-family:Arial,sans-serif;color:#111;padding:24px}
      h2,p{margin:5px 0}table{width:100%;border-collapse:collapse;margin-top:20px}
      th,td{border-bottom:1px solid #ddd;padding:8px;text-align:left}
      .right{text-align:right}.total{font-size:20px;font-weight:bold}
      @media print{button{display:none}body{padding:4mm}}
      </style></head><body>
      <h2>VASUDHARE SALESFORCE</h2><p>Sales Invoice</p><hr>
      <p><b>Invoice:</b> ${escapeHtml(invoice.invoice_number)}</p>
      <p><b>Date:</b> ${escapeHtml(invoice.invoice_date)}</p>
      <p><b>Customer:</b> ${escapeHtml(invoice.customer_name || "Walk-in Customer")}</p>
      <p><b>Mobile:</b> ${escapeHtml(invoice.customer_phone || "-")}</p>
      <table><thead><tr><th>Product</th><th>Qty</th><th>Rate</th><th>Amount</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <p class="right">Subtotal: ₹${money(invoice.subtotal)}</p>
      <p class="right">Discount: ₹${money(invoice.discount)}</p>
      <p class="right">Taxable: ₹${money(invoice.taxable_amount)}</p>
      <p class="right">CGST: ₹${money(invoice.cgst)}</p>
      <p class="right">SGST: ₹${money(invoice.sgst)}</p>
      <p class="right">IGST: ₹${money(invoice.igst)}</p>
      <p class="right">Total GST: ₹${money(invoice.gst_amount)}</p>
      <p class="right total">Total: ₹${money(invoice.grand_total)}</p>
      <p class="right">Paid: ₹${money(invoice.paid_amount)}</p>
      <p class="right">Balance: ₹${money(invoice.balance_amount)}</p>
      <p>Payment: ${escapeHtml(invoice.payment_mode)}</p>
      <hr><p>Thank you for shopping with us.</p>
      <button onclick="window.print()">Print invoice</button></body></html>`;
    const win = window.open("", "_blank", "width=900,height=700");
    if (!win) return alerts.error("Please allow pop-ups to print invoices.");
    win.document.write(html);
    win.document.close();
    win.focus();
    win.print();
  };

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[ch]);
  }

  const styles = {
    panel: { background: "#fff", border: "1px solid #e5e9e5", borderRadius: 12, padding: 18 },
    input: { width: "100%", padding: "10px 12px", border: "1px solid #d9e0d9", borderRadius: 8, boxSizing: "border-box", fontSize: 14 },
    label: { display: "block", fontSize: 12, fontWeight: 650, color: "#536057", marginBottom: 6 },
    button: { border: 0, borderRadius: 8, padding: "10px 14px", background: "#19734a", color: "white", cursor: "pointer", fontWeight: 650 },
    secondary: { border: "1px solid #dce4dc", borderRadius: 8, padding: "9px 12px", background: "white", cursor: "pointer", color: "#26352b" }
  };

  return <div style={{ color: "#24332a" }}>
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 18 }}>
      <div><h1 style={{ margin: 0, fontSize: 25 }}>Sales & Billing</h1>
        <p style={{ margin: "5px 0 0", color: "#78837b" }}>Retail billing, invoices and sales history</p></div>
      <div style={{ display: "flex", gap: 8 }}>
        <button style={tab === "new" ? styles.button : styles.secondary} onClick={() => setTab("new")}><ShoppingCart size={15} style={{ verticalAlign: "middle", marginRight: 6 }}/>New Sale</button>
        <button style={tab === "history" ? styles.button : styles.secondary} onClick={() => setTab("history")}><History size={15} style={{ verticalAlign: "middle", marginRight: 6 }}/>Sales History</button>
      </div>
    </div>

    {tab === "new" ? <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.55fr) minmax(300px,0.9fr)", gap: 16, alignItems: "start" }}>
      <div style={{ display: "grid", gap: 14 }}>
        <section style={styles.panel}>
          <h3 style={{ margin: "0 0 14px" }}>Customer details <span style={{ color: "#879188", fontSize: 12, fontWeight: 400 }}></span></h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
            <div><label style={styles.label}>Customer name</label><input style={styles.input} value={customerName} onChange={e => setCustomerName(e.target.value)} placeholder="Enter customer name"/></div>
            <div><label style={styles.label}>Mobile number</label><input style={styles.input} value={customerPhone} onChange={e => setCustomerPhone(e.target.value)} placeholder="Optional mobile number"/></div>
            <div><label style={styles.label}>Customer GST state code</label><input style={styles.input} value={customerStateCode} onChange={e => setCustomerStateCode(e.target.value.replace(/\\D/g, "").slice(0, 2))} placeholder="e.g. 03" inputMode="numeric" maxLength={2}/></div>
          </div>
          <small style={{ color: "#7c887f", display: "block", marginTop: 9 }}>Enter the customer's GST state code for interstate billing. Leave blank for a local / walk-in sale. Business state: {gstSettings?.state_code || "Not configured"}.</small>
        </section>

        <section style={styles.panel}>
          <h3 style={{ margin: "0 0 12px" }}>Find products</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <div style={{ position: "relative", flex: 1 }}>
              <Search size={17} style={{ position: "absolute", left: 11, top: 11, color: "#89948b" }}/>
              <input style={{ ...styles.input, paddingLeft: 36 }} value={search} onChange={e => { setSearch(e.target.value); loadProducts(e.target.value); }} placeholder="Search by product name, ISBN, author or SKU"/>
            </div>
            <button style={styles.secondary} onClick={() => loadProducts(search)} title="Refresh products"><RefreshCw size={17}/></button>
          </div>
          <div style={{ maxHeight: 270, overflowY: "auto", marginTop: 10 }}>
            {products.map(p => <div key={p.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "10px 2px", borderBottom: "1px solid #edf0ed" }}>
              <div style={{ minWidth: 0 }}>
                <b style={{ display: "block", fontSize: 14 }}>{p.name}</b>
                <small style={{ color: "#7b877e" }}>{p.sku || "No SKU"} {p.author ? " • " + p.author : ""} • Stock: {Number(p.stock)}</small>
              </div>
              <div style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                <b>₹{money(p.selling_price)}</b>
                <button onClick={() => addProduct(p)} style={{ ...styles.button, padding: "6px 9px", marginLeft: 10 }} disabled={Number(p.stock) <= 0}><Plus size={15}/></button>
              </div>
            </div>)}
            {!products.length && <p style={{ color: "#849087", textAlign: "center", padding: 18 }}>No matching products found.</p>}
          </div>
        </section>

        <section style={styles.panel}>
          <h3 style={{ margin: "0 0 12px" }}>Bill items ({cart.length})</h3>
          {!cart.length ? <p style={{ color: "#849087", textAlign: "center", padding: 18 }}>Search and add products to start a bill.</p> :
            <div style={{ overflowX: "auto" }}><table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead><tr style={{ color: "#758078", textAlign: "left" }}>
                <th style={{ padding: 8 }}>Product</th><th>Rate</th><th>Quantity</th><th>GST</th><th>Total</th><th></th>
              </tr></thead>
              <tbody>{cart.map(x => <tr key={x.id} style={{ borderTop: "1px solid #edf0ed" }}>
                <td style={{ padding: 9, minWidth: 130 }}><b>{x.name}</b><small style={{ display: "block", color: "#89938b" }}>{x.sku}</small></td>
                <td>₹{money(x.price)}</td>
                <td><div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <button style={styles.secondary} onClick={() => updateItem(x.id, { quantity: Math.max(1, x.quantity - 1) })}><Minus size={12}/></button>
                  <input aria-label="Quantity" type="number" min="1" max={x.stock} value={x.quantity} onChange={e => updateItem(x.id, { quantity: Math.min(x.stock, Math.max(1, Number(e.target.value) || 1)) })} style={{ ...styles.input, width: 55, padding: 6, textAlign: "center" }}/>
                  <button style={styles.secondary} disabled={x.quantity >= x.stock} onClick={() => updateItem(x.id, { quantity: x.quantity + 1 })}><Plus size={12}/></button>
                </div></td>
                <td>{x.gst}%</td>
                <td>₹{money(x.price * x.quantity * (1 + x.gst / 100))}</td>
                <td><button style={{ ...styles.secondary, color: "#b33d3d", padding: 6 }} onClick={() => setCart(old => old.filter(y => y.id !== x.id))}><Trash2 size={15}/></button></td>
              </tr>)}</tbody>
            </table></div>}
        </section>
      </div>

      <div style={{ display: "grid", gap: 14 }}>
        <section style={styles.panel}>
          <h3 style={{ margin: "0 0 14px" }}>Bill summary</h3>
          {cart.map(x => <div key={x.id} style={{ display: "flex", justifyContent: "space-between", gap: 10, fontSize: 13, marginBottom: 8 }}><span>{x.name} × {x.quantity}</span><span>₹{money(x.price * x.quantity)}</span></div>)}
          <div style={{ borderTop: "1px solid #e9eee9", paddingTop: 12, marginTop: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 9 }}><span>Subtotal</span><b>₹{money(totals.subtotal)}</b></div>
            <label style={styles.label}>Bill discount (₹)</label>
            <input style={styles.input} type="number" min="0" max={totals.subtotal} value={discount} onChange={e => setDiscount(e.target.value)}/>
            <div style={{ display: "flex", justifyContent: "space-between", margin: "12px 0 8px" }}><span>Taxable amount</span><b>₹{money(totals.taxable)}</b></div>
            {totals.interstate ? (
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}><span>IGST</span><b>₹{money(totals.igst)}</b></div>
            ) : (
              <>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}><span>CGST</span><b>₹{money(totals.cgst)}</b></div>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}><span>SGST</span><b>₹{money(totals.sgst)}</b></div>
              </>
            )}
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12, borderTop: "1px solid #edf0ed", paddingTop: 8 }}><b>Total GST</b><b>₹{money(totals.gst)}</b></div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px solid #e9eee9", paddingTop: 13 }}><b>Grand total</b><strong style={{ fontSize: 23, color: "#19734a" }}>₹{money(totals.total)}</strong></div>
          </div>
        </section>

        <section style={styles.panel}>
          <h3 style={{ margin: "0 0 12px" }}>Payment</h3>
          <label style={styles.label}>Payment method</label>
          <select style={styles.input} value={paymentMode} onChange={e => setPaymentMode(e.target.value)}>
            <option value="cash">Cash</option><option value="upi">UPI</option><option value="card">Card</option><option value="bank_transfer">Bank transfer</option><option value="credit">Credit / Pay later</option><option value="other">Other</option>
          </select>
          <label style={{ ...styles.label, marginTop: 12 }}>Amount received (₹)</label>
          <input style={styles.input} type="number" min="0" max={totals.total} placeholder={money(totals.total)} value={paid} onChange={e => setPaid(e.target.value)}/>
          <small style={{ display: "block", color: "#7b877e", marginTop: 6 }}>Leave blank to mark the full bill as paid. Enter zero for credit sale.</small>
        </section>

        {/* {customFields.length > 0 && <section style={styles.panel}>
          <h3 style={{ margin: "0 0 12px" }}>Additional sale details</h3>
          {customFields.map(f => <div key={f.id} style={{ marginBottom: 11 }}>
            <label style={styles.label}>{f.label}{f.is_required ? " *" : ""}</label>
            {f.field_type === "dropdown" ? (
              <select style={styles.input} value={customValues[f.field_key] ?? ""} onChange={e => setCustomValues(v => ({ ...v, [f.field_key]: e.target.value }))}>
                <option value="">Select</option>
                {(f.options || []).map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : f.field_type === "checkbox" ? (
              <input type="checkbox" checked={!!customValues[f.field_key]} onChange={e => setCustomValues(v => ({ ...v, [f.field_key]: e.target.checked }))}/>
            ) : f.field_type === "long_text" ? (
              <textarea style={styles.input} value={customValues[f.field_key] ?? ""} onChange={e => setCustomValues(v => ({ ...v, [f.field_key]: e.target.value }))}/>
            ) : (
              <input style={styles.input} type={["number", "decimal", "date", "email"].includes(f.field_type) ? (f.field_type === "decimal" ? "number" : f.field_type) : "text"} value={customValues[f.field_key] ?? ""} onChange={e => setCustomValues(v => ({ ...v, [f.field_key]: e.target.value }))}/>
            )}
          </div>)}
        </section>} */}

        <button disabled={busy || !cart.length} onClick={saveSale} style={{ ...styles.button, padding: 14, fontSize: 15, opacity: busy || !cart.length ? .6 : 1 }}>
          <Receipt size={17} style={{ verticalAlign: "middle", marginRight: 7 }}/>{busy ? "Saving invoice..." : "Complete Sale & Save Invoice"}
        </button>
      </div>
    </div> : <section style={styles.panel}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        <h3 style={{ margin: 0 }}>Sales history</h3>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={{ ...styles.input, width: 260 }} placeholder="Search invoice or customer" value={historySearch} onChange={e => setHistorySearch(e.target.value)}/>
          <button style={styles.secondary} onClick={() => loadSales(historySearch)}><RefreshCw size={16}/></button>
        </div>
      </div>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr style={{ textAlign: "left", color: "#758078" }}>{["Invoice","Date","Customer","Total","Paid","Balance","Status",""].map(h => <th key={h} style={{ padding: 10 }}>{h}</th>)}</tr></thead>
        <tbody>{sales.map(s => <tr key={s.id} style={{ borderTop: "1px solid #edf0ed" }}>
          <td style={{ padding: 10 }}><b>{s.invoice_number}</b></td><td>{s.invoice_date}</td><td>{s.customer_name}</td><td>₹{money(s.grand_total)}</td><td>₹{money(s.paid_amount)}</td><td>₹{money(s.balance_amount)}</td><td><span style={{ color: s.payment_status === "paid" ? "#19734a" : "#a66a16", fontWeight: 650 }}>{s.payment_status}</span></td>
          <td><button style={styles.secondary} onClick={() => openInvoice(s.id)}>View / Print</button></td>
        </tr>)}</tbody>
      </table></div>
      {!sales.length && <p style={{ textAlign: "center", color: "#849087", padding: 20 }}>No sales found.</p>}
    </section>}

    {selectedInvoice && <div style={{ position: "fixed", inset: 0, background: "rgba(15,25,18,.48)", zIndex: 1000, display: "grid", placeItems: "center", padding: 18 }} onClick={() => setSelectedInvoice(null)}>
      <div style={{ background: "white", width: "min(720px, 100%)", maxHeight: "90vh", overflow: "auto", borderRadius: 14, padding: 22 }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}><h2 style={{ margin: 0 }}>{selectedInvoice.invoice_number}</h2><button style={styles.secondary} onClick={() => setSelectedInvoice(null)}>Close</button></div>
        <p>{selectedInvoice.customer_name} · {selectedInvoice.invoice_date}</p>
        <table style={{ width: "100%", borderCollapse: "collapse" }}><thead><tr><th align="left">Product</th><th>Qty</th><th>Rate</th><th>Total</th></tr></thead><tbody>
          {selectedInvoice.items?.map(i => <tr key={i.id}><td style={{ padding: 8 }}>{i.product_name}</td><td align="center">{i.quantity}</td><td align="right">₹{money(i.unit_price)}</td><td align="right">₹{money(i.line_total)}</td></tr>)}
        </tbody></table>
        <div style={{ textAlign: "right", marginTop: 15, lineHeight: 1.9 }}>
          <div>Subtotal: ₹{money(selectedInvoice.subtotal)}</div>
          <div>Discount: ₹{money(selectedInvoice.discount)}</div>
          <div>CGST: ₹{money(selectedInvoice.cgst)}</div>
          <div>SGST: ₹{money(selectedInvoice.sgst)}</div>
          <div>IGST: ₹{money(selectedInvoice.igst)}</div>
          <div>Total GST: ₹{money(selectedInvoice.gst_amount)}</div>
          <b style={{ fontSize: 20 }}>Total: ₹{money(selectedInvoice.grand_total)}</b>
          <div>Paid: ₹{money(selectedInvoice.paid_amount)}</div><div>Balance: ₹{money(selectedInvoice.balance_amount)}</div>
        </div>
        <button style={{ ...styles.button, marginTop: 16 }} onClick={() => printInvoice(selectedInvoice)}><Printer size={16} style={{ verticalAlign: "middle", marginRight: 7 }}/>Print invoice</button>
      </div>
    </div>}
  </div>;
}
