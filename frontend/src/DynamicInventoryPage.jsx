
import {useEffect,useState} from "react";
import {RefreshCw,Save} from "lucide-react";
import CustomFieldsForm from "./components/CustomFieldsForm";
import {alerts} from "./utils/alerts";

const API="http://127.0.0.1:8000/api/v1";

export default function DynamicInventoryPage({tenant}) {
 const [inventory,setInventory]=useState([]);
 const [fields,setFields]=useState([]);
 const [values,setValues]=useState({});
 const [loading,setLoading]=useState(false);
 const headers={"Content-Type":"application/json","X-Tenant-Code":tenant};

 async function call(path,options={}) {
  const r=await fetch(API+path,{...options,headers:{...headers,...(options.headers||{})}});
  const d=await r.json().catch(()=>({detail:"Unexpected server response"}));
  if(!r.ok)throw new Error(d.detail||"Request failed");
  return d;
 }

 async function load() {
  setLoading(true);
  try {
   const [stock,defs]=await Promise.all([
    call("/inventory"),
    call("/custom-fields?module_key=inventory")
   ]);
   setInventory(stock.inventory||[]);
   setFields((defs.fields||[]).filter(f=>f.is_active));
  } catch(e) {await alerts.error(e);}
  finally {setLoading(false);}
 }

 useEffect(()=>{load();},[tenant]);

 async function save(e) {
  e.preventDefault();
  try {
   const productField=fields.find(f=>f.field_type==="product");
   const quantityField=fields.find(f=>f.field_type==="stock_quantity");
   const reasonField=fields.find(f=>f.field_type==="adjustment_reason");
   if(!productField||!quantityField||!reasonField) {
    throw new Error("In Settings → Dynamic Form Builder → Inventory, create one Product selector, one Stock quantity and one Adjustment reason field.");
   }
   const productId=Number(values[productField.field_key]);
   const quantity=Number(values[quantityField.field_key]);
   const reason=String(values[reasonField.field_key]||"").trim();
   if(!productId||!Number.isFinite(quantity)||quantity===0||!reason) {
    throw new Error("Please complete all required inventory fields. Quantity cannot be zero.");
   }
   await call("/inventory/adjust",{
    method:"POST",
    body:JSON.stringify({
     product_id:productId,
     quantity_change:quantity,
     reason
    })
   });
   await alerts.success("Stock adjustment saved");
   setValues({});
   await load();
  } catch(e) {await alerts.error(e);}
 }

 return <div className="page-content">
  <div className="welcome-row">
   <div><div className="eyebrow">STOCK CONTROL</div>
    <h1>Inventory</h1>
    <p>Configure stock adjustment fields in Dynamic Form Builder.</p>
   </div>
   <button className="secondary-action" onClick={load}><RefreshCw size={16}/> Refresh</button>
  </div>

  <div className="inventory-summary">
   <div className="data-panel"><small>Stock items</small><strong>{inventory.length}</strong></div>
   <div className="data-panel"><small>Low-stock items</small><strong>{inventory.filter(p=>p.low_stock).length}</strong></div>
  </div>

  <form className="data-panel adjustment-form" onSubmit={save}>
   <h2>Adjust stock</h2>
   {fields.length===0
    ?<p className="empty-state">No inventory fields configured. Open Settings → Dynamic Form Builder → Inventory.</p>
    :<CustomFieldsForm tenant={tenant} moduleKey="inventory"
       showSave={false} onValuesChange={setValues}/>
   }
   {fields.length>0&&<div className="form-actions">
    <button className="primary-action" type="submit"><Save size={16}/> Save adjustment</button>
   </div>}
  </form>

  <div className="data-panel table-panel">
   <div className="panel-heading"><h2>Current stock</h2><span>{inventory.length} items</span></div>
   {loading?<p className="empty-state">Loading inventory...</p>:!inventory.length
    ?<p className="empty-state">No stock records yet. Add products first.</p>
    :<div className="table-scroll"><table className="erp-table">
      <thead><tr><th>Product</th><th>Stock balance</th><th>Stock status</th></tr></thead>
      <tbody>{inventory.map(p=><tr key={p.product_id}>
       <td>{p.name}</td>
       <td>{p.quantity} {p.unit}</td>
       <td>{p.low_stock?<span className="stock-warning">Low stock</span>:<span className="stock-ok">In stock</span>}</td>
      </tr>)}</tbody>
     </table></div>}
  </div>
 </div>;
}
