import {useEffect,useState} from "react";
import CustomFieldsPanel from "./CustomFieldsPanel";
import {
 LayoutDashboard,BookOpen,Boxes,ShoppingCart,Receipt,Users,Truck,
 Calculator,ChartNoAxesCombined,Settings,Bell,Search,Menu,
 ChevronDown,ArrowUpRight,IndianRupee,Package,ClipboardList,
 ShieldCheck,CircleHelp,Plus,RefreshCw,Save,X,AlertTriangle
} from "lucide-react";

const API="http://127.0.0.1:8000/api/v1";

const groups=[
 ["OVERVIEW",[["Dashboard",LayoutDashboard]]],
 ["BOOKSTORE OPERATIONS",[
  ["Books & Products",BookOpen],["Inventory",Boxes],
  ["Purchases",ShoppingCart],["Sales & Billing",Receipt],
  ["Customers",Users],["Suppliers",Truck]]],
 ["FINANCE & INSIGHTS",[
  ["GST & Tax",Calculator],["Accounting",IndianRupee],
  ["Reports",ChartNoAxesCombined]]],
 ["ADMINISTRATION",[
  ["Staff & Permissions",ShieldCheck],["Settings",Settings]]]
];

const blankProduct={
 sku:"",product_type:"book",name:"",isbn10:"",isbn13:"",
 barcode:"",author:"",publisher:"",edition:"",language:"",
 subject:"",class_grade:"",board:"",binding:"",hsn_code:"",
 unit:"PCS",mrp:0,purchase_price:0,selling_price:0,
 gst_rate:0,reorder_level:0,shelf_location:"",description:""
};

export default function App(){
 const [active,setActive]=useState("Dashboard");
 const [menuOpen,setMenuOpen]=useState(false);
 const [status,setStatus]=useState("Checking");
 const [tenant,setTenant]=useState("DEMO-01");
 const [products,setProducts]=useState([]);
 const [inventory,setInventory]=useState([]);
 const [search,setSearch]=useState("");
 const [loading,setLoading]=useState(false);
 const [error,setError]=useState("");
 const [message,setMessage]=useState("");
 const [showForm,setShowForm]=useState(false);
 const [form,setForm]=useState(blankProduct);
 const [adjustProduct,setAdjustProduct]=useState("");
 const [adjustment,setAdjustment]=useState({quantity_change:"",reason:"Stock count correction"});

 const headers={"Content-Type":"application/json","X-Tenant-Code":tenant};

 async function request(path,options={}){
  const response=await fetch(API+path,{
   ...options,
   headers:{...headers,...(options.headers||{})}
  });
  const data=await response.json().catch(()=>({detail:"Unexpected server response"}));
  if(!response.ok) throw new Error(data.detail||"Request failed");
  return data;
 }

 async function loadProducts(){
  setLoading(true);setError("");
  try{
   const data=await request("/products?limit=500");
   setProducts(data.products||[]);
  }catch(e){setError(e.message);}
  finally{setLoading(false);}
 }

 async function loadInventory(){
  setLoading(true);setError("");
  try{
   const data=await request("/inventory");
   setInventory(data.inventory||[]);
  }catch(e){setError(e.message);}
  finally{setLoading(false);}
 }

 async function checkHealth(){
  try{
   const r=await fetch(API+"/health");
   const d=await r.json();
   setStatus(d.status==="healthy"?"Connected":"Check databases");
  }catch{setStatus("Backend not started");}
 }

 useEffect(()=>{checkHealth();},[]);
 useEffect(()=>{
  if(active==="Books & Products") loadProducts();
  if(active==="Inventory") loadInventory();
 },[active,tenant]);

 async function saveProduct(e){
  e.preventDefault();setError("");setMessage("");
  try{
   const body={...form,
    mrp:Number(form.mrp),purchase_price:Number(form.purchase_price),
    selling_price:Number(form.selling_price),gst_rate:Number(form.gst_rate),
    reorder_level:Number(form.reorder_level)
   };
   await request("/products",{method:"POST",body:JSON.stringify(body)});
   setMessage("Product saved successfully.");
   setForm(blankProduct);setShowForm(false);
   await loadProducts();
  }catch(e){setError(e.message);}
 }

 async function saveAdjustment(e){
  e.preventDefault();setError("");setMessage("");
  try{
   await request("/inventory/adjust",{method:"POST",body:JSON.stringify({
    product_id:Number(adjustProduct),
    quantity_change:Number(adjustment.quantity_change),
    reason:adjustment.reason
   })});
   setMessage("Stock adjustment saved.");
   setAdjustment({quantity_change:"",reason:"Stock count correction"});
   await loadInventory();
  }catch(e){setError(e.message);}
 }

 const filteredProducts=products.filter(p=>
  [p.name,p.sku,p.isbn10,p.isbn13,p.barcode,p.author,p.publisher]
   .some(v=>String(v||"").toLowerCase().includes(search.toLowerCase()))
 );
 const filteredInventory=inventory.filter(p=>
  [p.name,p.sku,p.barcode,p.isbn13]
   .some(v=>String(v||"").toLowerCase().includes(search.toLowerCase()))
 );

 const cards=[
  ["Books & Products","Manage books, ISBNs, authors, publishers and stationery.",BookOpen],
  ["Inventory","Stock levels, barcode labels, shelves and transfers.",Boxes],
  ["Purchases","Purchase orders, supplier bills and goods receipts.",ShoppingCart],
  ["Sales & Billing","Retail POS, GST invoices, payments and returns.",Receipt],
  ["Customers","Customer profiles, credit and loyalty records.",Users],
  ["Suppliers","Publisher and distributor accounts.",Truck],
  ["GST & Tax","Tax rates, HSN and GST summaries.",Calculator],
  ["Accounting","Ledgers, vouchers, cash and bank accounts.",IndianRupee]
 ];

 return <div className="app-shell">
  <aside className={`sidebar ${menuOpen?"sidebar-open":""}`}>
   <div className="brand">
    <div className="brand-mark">V</div>
    <div><strong>VASUDHARE SALESFORCE</strong></div>
   </div>
   <nav>{groups.map(([heading,items])=><div className="nav-group" key={heading}>
    <div className="nav-heading">{heading}</div>
    {items.map(([name,Icon])=><button key={name}
     className={`nav-item ${active===name?"active":""}`}
     onClick={()=>{setActive(name);setMenuOpen(false);setSearch("");setError("");setMessage("");}}>
     <Icon size={18}/><span>{name}</span>
     {name==="Sales & Billing"&&<span className="nav-tag">POS</span>}
    </button>)}</div>)}</nav>
   <div className="sidebar-bottom">
    <div className="help-card"><CircleHelp size={18}/>
     <div><b>Need help?</b><small>Support & guidance</small></div>
    </div>
    <div className="profile"><div className="avatar">VS</div>
     <div><b>Administrator</b><small>Admin account</small></div>
     <ChevronDown size={15}/>
    </div>
   </div>
  </aside>

  <main className="main-area">
   <header className="topbar">
    <button className="mobile-menu" onClick={()=>setMenuOpen(!menuOpen)}><Menu/></button>
    <div className="breadcrumb">VASUDHARE SALESFORCE <span>/</span> {active}</div>
    <div className="top-actions">
     <div className="system-status"><i className={status==="Connected"?"online":""}/>{status}</div>
     <select className="tenant-select" value={tenant} onChange={e=>{setTenant(e.target.value);setMessage("");setError("");}}>
      <option value="DEMO-01">Demo 1</option>
      <option value="DEMO-02">Demo 2</option>
     </select>
     <button className="icon-button" onClick={()=>active==="Inventory"?loadInventory():loadProducts()} title="Refresh"><RefreshCw size={17}/></button>
     <button className="icon-button"><Bell size={19}/></button>
     <div className="top-avatar">VS</div>
    </div>
   </header>

   <section className="page-content">
    {active==="Books & Products" ? <>
     <div className="welcome-row">
      <div><div className="eyebrow">CATALOGUE MANAGEMENT</div>
       <h1>Books & Products</h1><p>Add and manage books, stationery and supplies.</p>
      </div>
      <button className="primary-action" onClick={()=>{setShowForm(!showForm);setError("");}}>
       {showForm?<X size={17}/>:<Plus size={17}/>} {showForm?"Close":"Add Product"}
      </button>
     </div>

     {showForm&&<form className="data-panel product-form" onSubmit={saveProduct}>
      <h2>New product</h2>
      <div className="form-grid">
       <label>Product name *<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
       <label>SKU *<input required value={form.sku} onChange={e=>setForm({...form,sku:e.target.value})}/></label>
       <label>Product type<select value={form.product_type} onChange={e=>setForm({...form,product_type:e.target.value})}>
        <option value="book">Book</option><option value="stationery">Stationery</option>
        <option value="school_supply">School supply</option><option value="office_supply">Office supply</option><option value="other">Other</option>
       </select></label>
       <label>ISBN-13<input value={form.isbn13} onChange={e=>setForm({...form,isbn13:e.target.value})}/></label>
       <label>ISBN-10<input value={form.isbn10} onChange={e=>setForm({...form,isbn10:e.target.value})}/></label>
       <label>Barcode<input value={form.barcode} onChange={e=>setForm({...form,barcode:e.target.value})}/></label>
       <label>Author<input value={form.author} onChange={e=>setForm({...form,author:e.target.value})}/></label>
       <label>Publisher / Brand<input value={form.publisher} onChange={e=>setForm({...form,publisher:e.target.value})}/></label>
       <label>Edition<input value={form.edition} onChange={e=>setForm({...form,edition:e.target.value})}/></label>
       <label>Class / Grade<input value={form.class_grade} onChange={e=>setForm({...form,class_grade:e.target.value})}/></label>
       <label>Subject<input value={form.subject} onChange={e=>setForm({...form,subject:e.target.value})}/></label>
       <label>Board / Curriculum<input value={form.board} onChange={e=>setForm({...form,board:e.target.value})}/></label>
       <label>HSN code<input value={form.hsn_code} onChange={e=>setForm({...form,hsn_code:e.target.value})}/></label>
       <label>MRP (₹)<input type="number" min="0" step="0.01" value={form.mrp} onChange={e=>setForm({...form,mrp:e.target.value})}/></label>
       <label>Purchase price (₹)<input type="number" min="0" step="0.01" value={form.purchase_price} onChange={e=>setForm({...form,purchase_price:e.target.value})}/></label>
       <label>Selling price (₹)<input type="number" min="0" step="0.01" value={form.selling_price} onChange={e=>setForm({...form,selling_price:e.target.value})}/></label>
       <label>GST rate (%)<input type="number" min="0" step="0.01" value={form.gst_rate} onChange={e=>setForm({...form,gst_rate:e.target.value})}/></label>
       <label>Minimum stock alert<input type="number" min="0" step="1" value={form.reorder_level} onChange={e=>setForm({...form,reorder_level:e.target.value})}/></label>
       <label>Shelf / Rack<input value={form.shelf_location} onChange={e=>setForm({...form,shelf_location:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="primary-action" type="submit"><Save size={16}/> Save product</button></div>
     </form>}

     <div className="data-toolbar">
      <div className="search-field"><Search size={18}/><input placeholder="Search name, SKU, ISBN, barcode, author..." value={search} onChange={e=>setSearch(e.target.value)}/></div>
      <button className="secondary-action" onClick={loadProducts}><RefreshCw size={16}/> Refresh</button>
     </div>
     {error&&<div className="error-message"><AlertTriangle size={17}/>{error}</div>}
     {message&&<div className="success-message">{message}</div>}
     <div className="data-panel table-panel">
      <div className="panel-heading"><h2>Product catalogue</h2><span>{filteredProducts.length} products</span></div>
      {loading?<p className="empty-state">Loading products...</p>:filteredProducts.length===0?
       <p className="empty-state">No products found. Add your first book or product.</p>:
       <div className="table-scroll"><table className="erp-table">
        <thead><tr><th>Product</th><th>SKU</th><th>Type</th><th>ISBN / Barcode</th><th>MRP</th><th>Selling price</th></tr></thead>
        <tbody>{filteredProducts.map(p=><tr key={p.id}>
         <td><b>{p.name}</b><small>{p.author||p.publisher||""}</small></td>
         <td>{p.sku}</td><td>{p.product_type.replaceAll("_"," ")}</td>
         <td>{p.isbn13||p.isbn10||p.barcode||"—"}</td>
         <td>₹{Number(p.mrp).toFixed(2)}</td>
         <td>₹{Number(p.selling_price).toFixed(2)}</td>
        </tr>)}</tbody>
 </table></div>}
     </div>
    </> : active==="Inventory" ? <>
     <div className="welcome-row">
      <div><div className="eyebrow">STOCK CONTROL</div>
       <h1>Inventory</h1><p>Monitor stock levels and record stock corrections.</p>
      </div>
      <button className="secondary-action" onClick={loadInventory}><RefreshCw size={16}/> Refresh stock</button>
     </div>
     {error&&<div className="error-message"><AlertTriangle size={17}/>{error}</div>}
     {message&&<div className="success-message">{message}</div>}
     <div className="inventory-summary">
      <div className="data-panel"><small>Stock items</small><strong>{inventory.length}</strong></div>
      <div className="data-panel"><small>Low-stock items</small><strong>{inventory.filter(p=>p.low_stock).length}</strong></div>
     </div>
     <form className="data-panel adjustment-form" onSubmit={saveAdjustment}>
      <h2>Adjust stock</h2>
      <div className="form-grid">
       <label>Product<select required value={adjustProduct} onChange={e=>setAdjustProduct(e.target.value)}>
        <option value="">Select product</option>
        {inventory.map(p=><option key={p.product_id} value={p.product_id}>{p.name} ({p.sku}) — Current: {p.quantity}</option>)}
       </select></label>
       <label>Quantity change (+ add / − remove)<input required type="number" step="0.01" value={adjustment.quantity_change} onChange={e=>setAdjustment({...adjustment,quantity_change:e.target.value})}/></label>
       <label>Reason<input required value={adjustment.reason} onChange={e=>setAdjustment({...adjustment,reason:e.target.value})}/></label>
      </div>
      <div className="form-actions"><button className="primary-action" type="submit"><Save size={16}/> Save adjustment</button></div>
     </form>
     <div className="data-toolbar">
      <div className="search-field"><Search size={18}/><input placeholder="Search inventory..." value={search} onChange={e=>setSearch(e.target.value)}/></div>
     </div>
     <div className="data-panel table-panel">
      <div className="panel-heading"><h2>Current stock</h2><span>{filteredInventory.length} items</span></div>
      {loading?<p className="empty-state">Loading inventory...</p>:filteredInventory.length===0?
       <p className="empty-state">No stock records yet. Add products first.</p>:
       <div className="table-scroll"><table className="erp-table">
        <thead><tr><th>Product</th><th>SKU</th><th>Barcode</th><th>Available stock</th><th>Reorder level</th><th>Status</th></tr></thead>
        <tbody>{filteredInventory.map(p=><tr key={p.product_id}>
         <td><b>{p.name}</b><small>{p.shelf_location||""}</small></td>
         <td>{p.sku}</td><td>{p.barcode||"—"}</td>
         <td><b>{p.quantity} {p.unit}</b></td><td>{p.reorder_level}</td>
         <td>{p.low_stock?<span className="stock-warning">Low stock</span>:<span className="stock-ok">In stock</span>}</td>
        </tr>)}</tbody>
       </table></div>}
     </div>
    </> : active==="Settings" ? <CustomFieldsPanel tenant={tenant}/> : <>
     <div className="welcome-row"><div>
      <div className="eyebrow">BUSINESS MANAGEMENT</div>
      <h1>{active}</h1><p>Manage your business operations from one place.</p>
     </div></div>
     <div className="notice"><div className="notice-icon"><ShieldCheck size={20}/></div>
      <div><b>Workspace status</b><p>Choose Books & Products or Inventory to start managing your catalogue and stock.</p></div>
     </div>
     <div className="section-title"><div><h2>Business modules</h2><p>Select a module to continue.</p></div></div>
     <div className="module-grid">{cards.map(([name,desc,Icon])=><button className="module-card" key={name} onClick={()=>setActive(name)}>
      <div className="module-icon"><Icon size={21}/></div><div className="module-copy"><b>{name}</b><p>{desc}</p></div><ArrowUpRight className="module-arrow" size={17}/>
     </button>)}</div>
    </>}
   </section>
  </main>
 </div>;
}
