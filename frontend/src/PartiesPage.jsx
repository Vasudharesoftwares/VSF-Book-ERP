import { useEffect, useState } from "react";
import { alerts } from "./utils/alerts";

const API = "http://127.0.0.1:8000/api/v1";


function CustomerDirectory({ tenant }) {
  const API = "http://127.0.0.1:8000/api/v1";
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  async function load(term = search) {
    const response = await fetch(
      `${API}/customers/directory?search=${encodeURIComponent(term)}`,
      {
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Code": tenant
        }
      }
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Could not load customers.");
    }
    setItems(data.customers || []);
  }

  async function refresh() {
    setLoading(true);
    try {
      await load(search);
    } catch (error) {
      await alerts.error(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [tenant]);

  useEffect(() => {
    const timer = setTimeout(() => {
      load(search).catch(error => alerts.error(error));
    }, 300);
    return () => clearTimeout(timer);
  }, [search, tenant]);

  function money(value) {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR"
    }).format(Number(value || 0));
  }

  return (
    <div className="parties-page">
      <style>{`
        .customer-directory { color:#26372d; width:100%; }
        .customer-directory * { box-sizing:border-box; }
        .customer-directory .heading {
          display:flex; justify-content:space-between; align-items:center;
          gap:16px; flex-wrap:wrap; margin-bottom:22px;
        }
        .customer-directory h2 { margin:0; font-size:25px; font-weight:750; }
        .customer-directory p { color:#78867c; font-size:13px; }
        .customer-directory .card {
          background:#fff; border:1px solid #e3eae4; border-radius:13px;
          padding:22px; box-shadow:0 2px 8px rgba(25,55,35,.035);
        }
        .customer-directory button {
          border:1px solid #dce6de; background:#fff; color:#315640;
          border-radius:9px; padding:10px 15px; font-weight:650; cursor:pointer;
        }
        .customer-directory .table-head {
          display:flex; justify-content:space-between; align-items:center;
          gap:14px; flex-wrap:wrap; margin-bottom:17px;
        }
        .customer-directory .table-head h3 { margin:0; font-size:16px; }
        .customer-directory .search { width:min(310px,100%); }
        .customer-directory input {
          width:100%; height:40px; border:1px solid #dce5dd;
          border-radius:8px; padding:9px 12px; font-size:13px;
        }
        .customer-directory .table-wrap { overflow-x:auto; }
        .customer-directory table { width:100%; border-collapse:collapse; font-size:13px; }
        .customer-directory th {
          text-align:left; padding:12px 14px; background:#f5f8f5;
          color:#637268; white-space:nowrap; border-bottom:1px solid #e5ece6;
        }
        .customer-directory td {
          padding:14px; border-bottom:1px solid #edf1ed;
          color:#46564b; white-space:nowrap;
        }
        .customer-directory .empty {
          text-align:center; padding:28px 12px; color:#8a968d;
          white-space:normal;
        }
        @media(max-width:650px) {
          .customer-directory .card { padding:16px; }
          .customer-directory .search { width:100%; }
        }
      `}</style>

      <div className="customer-directory">
        <div className="heading">
          <div>
            <h2>Customers</h2>
            <p>Customer directory and purchase history from saved invoices.</p>
          </div>
          <button type="button" onClick={refresh}>Refresh records</button>
        </div>

        <section className="card">
          <div className="table-head">
            <h3>Customer directory ({items.length})</h3>
            <div className="search">
              <input
                value={search}
                onChange={event => setSearch(event.target.value)}
                placeholder="Search customer or mobile number..."
              />
            </div>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Customer name</th>
                  <th>Mobile number</th>
                  <th>First purchase date</th>
                  <th>Total invoices</th>
                  <th>Total purchase value</th>
                  <th>Outstanding balance</th>
                </tr>
              </thead>
              <tbody>
                {items.map(item => (
                  <tr key={item.id}>
                    <td><strong>{item.customer_name}</strong></td>
                    <td>{item.mobile_number || "—"}</td>
                    <td>{item.first_purchase_date || "—"}</td>
                    <td>{Number(item.total_invoices || 0)}</td>
                    <td>{money(item.total_purchase_value)}</td>
                    <td>{money(item.outstanding_balance)}</td>
                  </tr>
                ))}
                {!items.length && (
                  <tr>
                    <td colSpan="6" className="empty">
                      {loading
                        ? "Loading customers..."
                        : "No invoiced customers found. Customers will appear here automatically when you save an invoice with a name and mobile number."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

function SupplierPartiesPage({ tenant, type }) {
  const moduleKey = type === "customer" ? "customers" : "suppliers";
  const heading = type === "customer" ? "Customers" : "Suppliers";
  const singular = type === "customer" ? "Customer" : "Supplier";

  const [fields, setFields] = useState([]);
  const [values, setValues] = useState({});
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const headers = {
    "Content-Type": "application/json",
    "X-Tenant-Code": tenant
  };

  async function request(path, options = {}) {
    const response = await fetch(API + path, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Request failed.");
    return data;
  }

  async function loadFields() {
    const data = await request(
      `/custom-fields?module_key=${encodeURIComponent(moduleKey)}`
    );
    setFields((data.fields || []).filter(field => field.is_active));
  }

  async function loadItems(term = search) {
    const data = await request(
      `/parties?party_type=${type}&search=${encodeURIComponent(term)}`
    );
    setItems(data.parties || []);
  }

  async function refresh() {
    setLoading(true);
    try {
      await Promise.all([loadFields(), loadItems()]);
    } catch (error) {
      await alerts.error(error);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, [tenant, type]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadItems(search).catch(error => alerts.error(error));
    }, 250);
    return () => clearTimeout(timer);
  }, [search, tenant, type]);

  function change(field, value) {
    setValues(previous => ({ ...previous, [field.field_key]: value }));
  }

  function renderField(field) {
    const value = values[field.field_key] ?? "";
    const id = `party-field-${field.id}`;
    const common = {
      id,
      required: Boolean(field.is_required),
      value,
      onChange: event => change(field, event.target.value)
    };

    switch (field.field_type) {
      case "long_text":
        return <textarea {...common} rows={3} className="party-control party-textarea" />;
      case "number":
        return <input {...common} type="number" step="1" className="party-control" />;
      case "decimal":
        return <input {...common} type="number" step="any" className="party-control" />;
      case "date":
        return <input {...common} type="date" className="party-control" />;
      case "email":
        return <input {...common} type="email" className="party-control" />;
      case "phone":
        return <input {...common} type="tel" className="party-control" />;
      case "dropdown":
        return (
          <select {...common} className="party-control">
            <option value="">Select an option</option>
            {(field.options || []).map(option =>
              <option key={option} value={option}>{option}</option>
            )}
          </select>
        );
      case "multi_select":
        return (
          <select
            id={id}
            multiple
            className="party-control party-multiselect"
            required={Boolean(field.is_required)}
            value={Array.isArray(value) ? value : []}
            onChange={event => change(
              field,
              Array.from(event.target.selectedOptions, option => option.value)
            )}
          >
            {(field.options || []).map(option =>
              <option key={option} value={option}>{option}</option>
            )}
          </select>
        );
      case "checkbox":
        return (
          <input
            id={id}
            type="checkbox"
            className="party-checkbox"
            checked={Boolean(value)}
            onChange={event => change(field, event.target.checked)}
          />
        );
      default:
        return <input {...common} type="text" className="party-control" />;
    }
  }

  async function save(event) {
    event.preventDefault();

    if (!fields.length) {
      await alerts.error(new Error(`Create fields for ${heading} in Settings first.`));
      return;
    }

    const missing = fields.find(field => field.is_required && (
      values[field.field_key] === undefined ||
      values[field.field_key] === "" ||
      values[field.field_key] === null ||
      (Array.isArray(values[field.field_key]) && values[field.field_key].length === 0)
    ));

    if (missing) {
      await alerts.error(new Error(`Please complete: ${missing.label}`));
      return;
    }

    setBusy(true);
    try {
      const identityField =
        fields.find(field =>
          String(field.field_key || "").trim().toLowerCase() === "name" ||
          String(field.label || "").trim().toLowerCase() === "name"
        ) ||
        fields.find(field =>
          ["vendor", "supplier_name", "customer_name"].includes(
            String(field.field_key || "").trim().toLowerCase()
          ) ||
          ["vendor", "supplier name", "customer name"].includes(
            String(field.label || "").trim().toLowerCase()
          )
        );

      if (!identityField) {
        throw new Error(`Please configure a Name or Vendor field for ${heading} in Settings.`);
      }

      const partyName = String(values[identityField.field_key] ?? "").trim();
      if (!partyName) {
        throw new Error(`Please enter ${identityField.label}.`);
      }

      const created = await request("/parties", {
        method: "POST",
        body: JSON.stringify({
          party_type: type,
          name: partyName
        })
      });

      await request(`/custom-field-values/${moduleKey}/${created.party.id}`, {
        method: "PUT",
        body: JSON.stringify({ values })
      });

      setValues({});
      await loadItems(search);
      await alerts.success(`${singular} saved successfully.`);
    } catch (error) {
      await alerts.error(error);
      await loadItems(search).catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="parties-page">
      <style>{`
        .parties-page { color:#26372d; width:100%; }
        .parties-page * { box-sizing:border-box; }
        .party-heading { display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:22px; }
        .party-heading h2 { margin:0; font-size:25px; font-weight:750; letter-spacing:-.4px; }
        .party-heading p { margin:6px 0 0; color:#78867c; font-size:13px; }
        .party-refresh { border:1px solid #dce6de; background:#fff; color:#315640; border-radius:9px; padding:10px 15px; font-weight:650; cursor:pointer; }
        .party-refresh:hover { background:#f3f8f4; }
        .party-card { background:#fff; border:1px solid #e3eae4; border-radius:13px; padding:22px; margin-bottom:18px; box-shadow:0 2px 8px rgba(25,55,35,.035); }
        .party-card-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:18px; }
        .party-card-heading h3 { margin:0; font-size:16px; font-weight:720; }
        .party-card-heading p { margin:5px 0 0; color:#829087; font-size:12px; }
        .party-form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:17px 20px; }
        .party-field { display:flex; flex-direction:column; gap:7px; min-width:0; color:#46564b; font-size:13px; font-weight:650; }
        .party-required { color:#bd4848; margin-left:3px; }
        .party-control { width:100%; min-height:42px; padding:10px 12px; border:1px solid #d8e2da; border-radius:8px; background:#fff; color:#26372d; font:inherit; font-size:14px; outline:none; }
        .party-control:focus { border-color:#4b9668; box-shadow:0 0 0 3px rgba(65,145,92,.12); }
        .party-textarea { min-height:88px; resize:vertical; }
        .party-multiselect { min-height:90px; }
        .party-checkbox { width:18px; height:18px; accent-color:#267449; }
        .party-save { margin-top:20px; border:0; border-radius:9px; padding:11px 19px; background:#207448; color:#fff; font-size:14px; font-weight:700; cursor:pointer; }
        .party-save:hover { background:#185e39; }
        .party-save:disabled { opacity:.6; cursor:wait; }
        .party-table-head { display:flex; justify-content:space-between; align-items:center; gap:14px; flex-wrap:wrap; margin-bottom:17px; }
        .party-table-head h3 { margin:0; font-size:16px; }
        .party-count { display:inline-flex; align-items:center; justify-content:center; min-width:27px; height:25px; padding:0 8px; margin-left:7px; border-radius:20px; background:#edf5ef; color:#267448; font-size:12px; font-weight:700; }
        .party-search { width:min(310px,100%); position:relative; }
        .party-search input { width:100%; height:40px; border:1px solid #dce5dd; border-radius:8px; padding:9px 12px; font-size:13px; outline:none; }
        .party-search input:focus { border-color:#4b9668; box-shadow:0 0 0 3px rgba(65,145,92,.1); }
        .party-table-wrap { overflow-x:auto; }
        .party-table { width:100%; border-collapse:collapse; font-size:13px; }
        .party-table th { text-align:left; padding:12px 14px; background:#f5f8f5; color:#637268; font-weight:700; white-space:nowrap; border-bottom:1px solid #e5ece6; }
        .party-table td { padding:14px; border-bottom:1px solid #edf1ed; color:#46564b; }
        .party-table tbody tr:hover { background:#fafcfb; }
        .party-record { font-weight:650; color:#2c4936; }
        .party-empty { text-align:center; padding:28px 12px !important; color:#8a968d !important; }
        .party-hint { color:#7d8b81; font-size:13px; line-height:1.6; padding:15px; background:#f6f9f6; border:1px dashed #d9e5db; border-radius:9px; }
        @media(max-width:650px) {
          .party-card { padding:16px; }
          .party-form-grid { grid-template-columns:1fr; gap:14px; }
          .party-heading h2 { font-size:22px; }
          .party-search { width:100%; }
        }
      `}</style>

      <div className="party-heading">
        <div>
          <h2>{heading}</h2>
          <p>Manage your {heading.toLowerCase()} using the fields configured in Settings.</p>
        </div>
        <button type="button" className="party-refresh" onClick={refresh}>
          Refresh records
        </button>
      </div>

      <section className="party-card">
        <div className="party-card-heading">
          <div>
            <h3>Add {singular.toLowerCase()}</h3>
            <p>Enter the details below and save the record.</p>
          </div>
        </div>

        {loading ? (
          <p className="party-hint">Loading configured fields...</p>
        ) : fields.length === 0 ? (
          <p className="party-hint">
            No {type} fields configured yet. Open Settings → Dynamic Form Builder → {heading} to add fields.
          </p>
        ) : (
          <form onSubmit={save}>
            <div className="party-form-grid">
              {fields.map(field => (
                <div className="party-field" key={field.id}>
                  <label htmlFor={`party-field-${field.id}`}>
                    {field.label}
                    {field.is_required && <span className="party-required">*</span>}
                  </label>
                  {renderField(field)}
                </div>
              ))}
            </div>
            <button type="submit" className="party-save" disabled={busy}>
              {busy ? "Saving..." : `Save ${singular.toLowerCase()}`}
            </button>
          </form>
        )}
      </section>

      <section className="party-card">
        <div className="party-table-head">
          <h3>{heading} records <span className="party-count">{items.length}</span></h3>
          <div className="party-search">
            <input
              value={search}
              onChange={event => setSearch(event.target.value)}
              placeholder={`Search ${heading.toLowerCase()}...`}
              aria-label={`Search ${heading.toLowerCase()}`}
            />
          </div>
        </div>

        <div className="party-table-wrap">
          <table className="party-table">
            <thead>
              <tr>
                <th>Record</th>
                <th>Supplier Payable</th>
                <th>Supplier Credit</th>
                <th>Created date</th>
              </tr>
            </thead>
            <tbody>
              {items.map(item => (
                <tr key={item.id}>
                  <td className="party-record">{item.name || `${singular} #${item.id}`}</td>
                  <td>₹{Number(item.payable_balance || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                  <td>₹{Number(item.supplier_credit || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                  <td>{item.created_at || "—"}</td>
                </tr>
              ))}
              {!items.length && (
                <tr>
                  <td colSpan="4" className="party-empty">
                    {loading ? "Loading records..." : "No records found."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}


export default function PartiesPage({ tenant, type }) {
  if (type === "customer") {
    return <CustomerDirectory tenant={tenant} />;
  }
  return <SupplierPartiesPage tenant={tenant} type="supplier" />;
}
