import FinanceModulesPage from "./FinanceModulesPage";
import SalesBillingPage from "./SalesBillingPage";
import DynamicProductsPage from "./DynamicProductsPage";
import DynamicInventoryPage from "./DynamicInventoryPage";
import PartiesPage from "./PartiesPage";
import PurchasesPage from "./PurchasesPage";
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
 const [active,setActive] = useState(() => {
    const saved = localStorage.getItem("vsf_active_module");
    return saved || "Dashboard";
  });
   useEffect(()=>{localStorage.setItem("vsf_active_module",active);},[active]);
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
     onClick={()=>{localStorage.setItem("vsf_active_module",name);setActive(name);setMenuOpen(false);setSearch("");setError("");setMessage("");}}>
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
    {active==="Purchases" ? <PurchasesPage tenant={tenant}/> : active==="Sales & Billing" ? <SalesBillingPage tenant={tenant}/> : active==="Books & Products" ? <DynamicProductsPage tenant={tenant}/> : active==="Inventory" ? <DynamicInventoryPage tenant={tenant}/> : ["Customers","Suppliers"].includes(active) ? <PartiesPage tenant={tenant} type={active==="Customers" ? "customer" : "supplier"}/> : active==="GST & Tax" ? <FinanceModulesPage tenant={tenant} mode="GST & Tax"/> : active==="Accounting" ? <FinanceModulesPage tenant={tenant} mode="Accounting"/> : active==="Settings" ? <CustomFieldsPanel tenant={tenant}/> : <>
     <div className="welcome-row"><div>
      <div className="eyebrow">BUSINESS MANAGEMENT</div>
      <h1>{active}</h1><p>Manage your business operations from one place.</p>
     </div></div>
     <div className="notice"><div className="notice-icon"><ShieldCheck size={20}/></div>
      <div><b>Workspace status</b><p>Choose Books & Products or Inventory to start managing your catalogue and stock.</p></div>
     </div>
     <div className="section-title"><div><h2>Business modules</h2><p>Select a module to continue.</p></div></div>
     <div className="module-grid">{cards.map(([name,desc,Icon])=><button className="module-card" key={name} onClick={()=>{localStorage.setItem("vsf_active_module",name);setActive(name)}}>
      <div className="module-icon"><Icon size={21}/></div><div className="module-copy"><b>{name}</b><p>{desc}</p></div><ArrowUpRight className="module-arrow" size={17}/>
     </button>)}</div>
    </>}
   </section>
  </main>
 </div>;
}
