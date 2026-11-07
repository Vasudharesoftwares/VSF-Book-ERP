import { useEffect, useMemo, useState } from "react";
import {
  BarChart3, Download, Printer, RefreshCw, FileSpreadsheet,
  CalendarDays, AlertCircle
} from "lucide-react";

const API = "http://127.0.0.1:8000/api/v1";

const REPORTS = [
  { id: "sales", label: "Sales Register", path: "/gst/register/sales", dates: true },
  { id: "purchases", label: "Purchase Register", path: "/gst/register/purchases", dates: true },
  { id: "gst", label: "GST Summary", path: "/gst/dashboard", dates: false },
  { id: "hsn", label: "HSN Summary", path: "/gst/hsn-summary", dates: false },
  { id: "trial", label: "Trial Balance", path: "/accounting/trial-balance", dates: false },
  { id: "pl", label: "Profit & Loss", path: "/accounting/profit-loss", dates: false },
  { id: "balance", label: "Balance Sheet", path: "/accounting/balance-sheet", dates: false }
];

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
};
const monthStart = () => `${today().slice(0,8)}01`;
const money = value => Number(value || 0).toLocaleString("en-IN", {
  minimumFractionDigits: 2, maximumFractionDigits: 2
});
const title = key => key.replaceAll("_"," ").replace(/\b\w/g, c => c.toUpperCase());

export default function ReportsPage({ tenant }) {
  const [report, setReport] = useState("sales");
  const [fromDate, setFromDate] = useState(monthStart);
  const [toDate, setToDate] = useState(today);
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const selected = REPORTS.find(r => r.id === report);

  async function loadReport() {
    setLoading(true);
    setError("");
    setSummary(null);
    try {
      let path = selected.path;
      if (selected.dates) {
        const params = new URLSearchParams();
        if (fromDate) params.set("from_date", fromDate);
        if (toDate) params.set("to_date", toDate);
        path += `?${params.toString()}`;
      }
      const response = await fetch(API + path, {
        headers: { "X-Tenant-Code": tenant }
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Could not load report");

      if (report === "gst") {
        setSummary(data);
        setRows([
          { section: "Outward Supplies", ...(data.sales || {}) },
          { section: "Inward Supplies", ...(data.purchases || {}) }
        ]);
      } else {
        setRows(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      setRows([]);
      setError(e.message || "Report could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadReport(); }, [report, tenant]);

  const totals = useMemo(() => {
    const sum = key => rows.reduce((total, row) => total + Number(row[key] || 0), 0);
    return {
      count: rows.length,
      taxable: sum("taxable_amount") + sum("taxable_value"),
      tax: sum("total_tax") + sum("tax_value"),
      total: sum("grand_total")
    };
  }, [rows]);

  const columns = useMemo(() => {
    if (!rows.length) return [];
    return Object.keys(rows[0]).filter(key => key !== "id");
  }, [rows]);

  function exportCsv() {
    if (!rows.length) return;
    const csvCell = value => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [
      columns.map(title).map(csvCell).join(","),
      ...rows.map(row => columns.map(key => csvCell(row[key])).join(","))
    ].join("\n");
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report}_${tenant.toLowerCase()}_${today()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="reports-page">
      <div className="welcome-row">
        <div>
          <div className="eyebrow">FINANCE & INSIGHTS</div>
          <h1>Reports & BI</h1>
          <p>Business reports and financial summaries · {tenant}</p>
        </div>
        <button className="secondary-action" onClick={loadReport} disabled={loading}>
          <RefreshCw size={15}/> Refresh
        </button>
      </div>

      <div className="data-panel reports-filter">
        <div className="reports-filter-title">
          <div><BarChart3 size={19}/><b>Report selection</b></div>
          <span>{selected?.dates ? "Date-filtered report" : "Current available report"}</span>
        </div>
        <div className="reports-controls">
          <label>Choose report
            <select value={report} onChange={e => setReport(e.target.value)}>
              {REPORTS.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label>From date
            <input type="date" value={fromDate} max={toDate || undefined}
              onChange={e => setFromDate(e.target.value)} disabled={!selected?.dates}/>
          </label>
          <label>To date
            <input type="date" value={toDate} min={fromDate || undefined}
              onChange={e => setToDate(e.target.value)} disabled={!selected?.dates}/>
          </label>
          <button className="primary-action" onClick={loadReport} disabled={loading}>
            <CalendarDays size={15}/> Apply
          </button>
        </div>
        {!selected?.dates && (
          <p className="reports-note">
            This report currently returns all available records. Date filtering is not yet supported by its backend endpoint.
          </p>
        )}
      </div>

      {error && <div className="error-message"><AlertCircle size={17}/>{error}</div>}

      {report === "gst" && summary && (
        <div className="stats-grid reports-stats">
          <div className="stat-card"><div className="stat-top">Output Tax</div><strong>₹{money(summary.output_tax)}</strong><small>Sales tax</small></div>
          <div className="stat-card"><div className="stat-top">Input Tax</div><strong>₹{money(summary.input_tax)}</strong><small>Purchase tax</small></div>
          <div className="stat-card"><div className="stat-top">Net Tax</div><strong>₹{money(summary.net_tax)}</strong><small>Output less input tax</small></div>
          <div className="stat-card"><div className="stat-top">Sales Invoices</div><strong>{summary.sales?.invoices || 0}</strong><small>Current invoice workflow</small></div>
        </div>
      )}

      {report !== "gst" && (
        <div className="stats-grid reports-stats">
          <div className="stat-card"><div className="stat-top">Records</div><strong>{totals.count}</strong><small>Rows returned</small></div>
          <div className="stat-card"><div className="stat-top">Taxable Value</div><strong>₹{money(totals.taxable)}</strong><small>Where supplied by report</small></div>
          <div className="stat-card"><div className="stat-top">Tax Amount</div><strong>₹{money(totals.tax)}</strong><small>Where supplied by report</small></div>
          <div className="stat-card"><div className="stat-top">Invoice Total</div><strong>₹{money(totals.total)}</strong><small>Where supplied by report</small></div>
        </div>
      )}

      <div className="data-panel reports-table-panel">
        <div className="panel-heading">
          <div>
            <h2>{selected?.label}</h2>
            <span>{rows.length} records · {tenant}</span>
          </div>
          <div className="reports-actions">
            <button className="secondary-action" onClick={exportCsv} disabled={!rows.length}>
              <Download size={15}/> Export CSV
            </button>
            <button className="secondary-action" onClick={() => window.print()}>
              <Printer size={15}/> Print
            </button>
          </div>
        </div>
        {loading ? <div className="empty-state">Loading report…</div> :
          error ? <div className="empty-state">Correct the error above and refresh the report.</div> :
          rows.length === 0 ? <div className="empty-state"><FileSpreadsheet size={24}/><p>No records found for this report.</p></div> :
          <div className="table-scroll">
            <table className="erp-table reports-table">
              <thead><tr>{columns.map(key => <th key={key}>{title(key)}</th>)}</tr></thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={row.id ?? index}>
                    {columns.map(key => {
                      const value = row[key];
                      const numeric = typeof value === "number";
                      return <td key={key}>{numeric && /amount|tax|debit|credit|balance|total|net|value|opening/i.test(key)
                        ? `₹${money(value)}` : value == null || value === "" ? "—" : String(value)}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        }
      </div>
      <p className="reports-disclaimer">
        Reports display data returned by the current ERP endpoints. Verify accounting balances and GST summaries before using them for statutory filing or final financial decisions.
      </p>
    </div>
  );
}
