
import {useEffect,useState} from "react";
import {Plus,RefreshCw,Save,X,Edit,Trash2} from "lucide-react";
import CustomFieldsForm from "./components/CustomFieldsForm";
import {alerts} from "./utils/alerts";

const API="http://127.0.0.1:8000/api/v1";

export default function DynamicProductsPage({tenant}) {
 const [products,setProducts]=useState([]);
 const [fields,setFields]=useState([]);
 const [values,setValues]=useState({});
 const [savedValues,setSavedValues]=useState({});
 const [showForm,setShowForm]=useState(false);
 const [editId,setEditId]=useState(null);
 const [loading,setLoading]=useState(false);
 const [gstRate,setGstRate]=useState("0");
 const [hsnCode,setHsnCode]=useState("");
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
   const [p,f]=await Promise.all([
    call("/products?limit=500"),
    call("/custom-fields?module_key=products")
   ]);
   const active=(f.fields||[]).filter(x=>x.is_active);
   setProducts(p.products||[]);
   setFields(active);
   const all={};
   await Promise.all((p.products||[]).map(async item=>{
    try {
     const result=await call(`/custom-field-values/products/${item.id}`);
     all[item.id]=result.values||{};
    } catch {all[item.id]={};}
   }));
   setSavedValues(all);
  } catch(e) {await alerts.error(e);}
  finally {setLoading(false);}
 }

 useEffect(()=>{load();},[tenant]);

 async function save(e) {
  e.preventDefault();
  try {
   if(!fields.length)throw new Error("First create product fields in Settings → Dynamic Form Builder.");

   const nameField = fields.find(field =>
    String(field.label || "").trim().toLowerCase().includes("name") ||
    String(field.field_key || "").trim().toLowerCase().includes("name")
   );
   if(!nameField)throw new Error("Please configure a Name field in the Books & Products Dynamic Form Builder.");
   const productName = String(values[nameField.field_key] ?? "").trim();
   if(!productName)throw new Error("Please enter the book name.");

   const priceField = fields.find(field =>
    ["price","selling price"].includes(String(field.label || "").trim().toLowerCase()) ||
    ["price","selling_price"].includes(String(field.field_key || "").trim().toLowerCase())
   );
   const sellingPrice = priceField ? Number(values[priceField.field_key] ?? 0) : 0;
   if(!Number.isFinite(sellingPrice) || sellingPrice < 0)
    throw new Error("Please enter a valid non-negative selling price.");

   const gst = Number(gstRate || 0);
   if(!Number.isFinite(gst) || gst < 0 || gst > 100)
    throw new Error("Enter a valid GST rate between 0 and 100.");
   const hsn = String(hsnCode || "").trim();

   const stockField = fields.find(field =>
    ["stock","opening stock"].includes(String(field.label || "").trim().toLowerCase()) ||
    ["stock","opening_stock"].includes(String(field.field_key || "").trim().toLowerCase())
   );
   const openingStock = stockField ? Number(values[stockField.field_key] ?? 0) : 0;
   if(!Number.isFinite(openingStock) || openingStock < 0)
    throw new Error("Please enter a valid non-negative opening stock.");

   const configuredValues = Object.fromEntries(
    fields
     .filter(field => Object.prototype.hasOwnProperty.call(values, field.field_key))
     .map(field => [field.field_key, values[field.field_key]])
   );

   if(editId) {
    await call(`/products/${editId}`,{
     method:"PUT",
     body:JSON.stringify({name:productName,selling_price:sellingPrice,gst_rate:gst,hsn_code:hsn})
    });
    await call(`/custom-field-values/products/${editId}`,{
     method:"PUT",body:JSON.stringify({values:configuredValues})
    });
    await alerts.success("Product details updated");
   } else {
    const stamp=Date.now();
    const created=await call("/products",{
     method:"POST",
     body:JSON.stringify({
      sku:`VSF-${stamp}`,
      name:productName,
      product_type:"other",
      unit:"PCS",mrp:0,purchase_price:0,selling_price:sellingPrice,
      gst_rate:gst,hsn_code:hsn,reorder_level:0
     })
    });
    const productId = created.product?.id ?? created.id;
    await call(`/custom-field-values/products/${productId}`,{
     method:"PUT",body:JSON.stringify({values:configuredValues})
    });
    if(openingStock > 0) {
     await call("/inventory/adjust",{
      method:"POST",
      body:JSON.stringify({
       product_id:productId,
       quantity_change:openingStock,
       reason:"Opening stock"
      })
     });
    }
    await alerts.success("Product created");
   }
   setShowForm(false);setEditId(null);setValues({});
   setGstRate("0");setHsnCode("");
   await load();
  } catch(e) {await alerts.error(e);}
 }

 function startEdit(id) {
  const product = products.find(item => item.id === id);
  setEditId(id);
  setValues(savedValues[id]||{});
  setGstRate(String(product?.gst_rate ?? 0));
  setHsnCode(String(product?.hsn_code ?? ""));
  setShowForm(true);
 }

 async function deleteProduct(product) {
  try {
   const result = await alerts.confirm(
    "Deactivate this product?",
    `"${product.name}" will be removed from active product lists. Historical sales, purchases and stock records will be preserved.`
   );

   if (!result.isConfirmed) return;

   await call(`/products/${product.id}`, {method:"DELETE"});

   await alerts.success("Product deactivated successfully");
   setShowForm(false);
   setEditId(null);
   setValues({});
   await load();
  } catch(e) {
   await alerts.error(e);
  }
 }

 return <div className="page-content">
  <div className="welcome-row">
   <div><div className="eyebrow">CATALOGUE MANAGEMENT</div>
    <h1>Books & Products</h1>
    <p>Product information is controlled by your Dynamic Form Builder.</p>
   </div>
   <button className="primary-action" onClick={()=>{
    setEditId(null);setValues({});
    setGstRate("0");setHsnCode("");
    setShowForm(!showForm);
   }}>
    {showForm?<X size={17}/>:<Plus size={17}/>} {showForm?"Close":"Add Product"}
   </button>
  </div>

  {showForm&&<form className="data-panel product-form" onSubmit={save}>
   <h2>{editId?"Edit product details":"New product"}</h2>
   {fields.length===0
    ? <p className="empty-state">No product fields configured. Create them in Settings → Dynamic Form Builder → Books & Products.</p>
    : <CustomFieldsForm tenant={tenant} moduleKey="products"
       entityId={editId||undefined} showSave={false}
       onValuesChange={setValues}/>
   }
   {fields.length>0&&<div className="form-actions">
    <button className="primary-action" type="submit">
     <Save size={16}/> {editId?"Save changes":"Save product"}
    </button>
    {editId&&<>
     <button className="secondary-action" type="button" onClick={()=>{
      setShowForm(false);setEditId(null);setValues({});
     }}>
      <X size={16}/> Cancel
     </button>
     <button className="secondary-action" type="button"
      onClick={()=>deleteProduct(products.find(p=>p.id===editId))}
      style={{color:"#b42318"}}>
      <Trash2 size={16}/> Delete product
     </button>
    </>}
   </div>}
   {fields.length>0&&<div style={{
     display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(220px,1fr))",
     gap:12,marginTop:16,padding:14,
     border:"1px solid #dfe8e1",borderRadius:10
   }}>
    <label style={{display:"grid",gap:6,fontWeight:600}}>
     GST Rate (%)
     <input type="number" min="0" max="100" step="0.01"
      value={gstRate}
      onChange={e=>setGstRate(e.target.value)}
      placeholder="Example: 5, 12, 18 or 28"
      style={{padding:10,border:"1px solid #cfd9d1",borderRadius:7}}/>
    </label>
    <label style={{display:"grid",gap:6,fontWeight:600}}>
     HSN Code
     <input type="text" value={hsnCode}
      onChange={e=>setHsnCode(e.target.value)}
      placeholder="Enter product HSN code"
      style={{padding:10,border:"1px solid #cfd9d1",borderRadius:7}}/>
    </label>
   </div>}
  </form>}

  <div className="data-toolbar">
   <span>{products.length} products</span>
   <button className="secondary-action" onClick={load}><RefreshCw size={16}/> Refresh</button>
  </div>

  <div className="data-panel table-panel">
   <div className="panel-heading"><h2>Product catalogue</h2></div>
   {loading?<p className="empty-state">Loading products...</p>:!products.length
    ?<p className="empty-state">No products found. Add your first product.</p>
    :<div className="table-scroll"><table className="erp-table">
      <thead><tr>
       {fields.map(f=><th key={f.id}>{f.label}</th>)}
       <th>Actions</th>
      </tr></thead>
      <tbody>{products.map(p=><tr key={p.id}>
       {fields.map(f=><td key={f.id}>
        {String(savedValues[p.id]?.[f.field_key] ??
          (String(f.label || "").trim().toLowerCase().includes("name") ||
           String(f.field_key || "").trim().toLowerCase().includes("name")
            ? p.name : "—"))}
       </td>)}
       <td>
        <div className="form-actions">
         <button className="secondary-action" onClick={()=>startEdit(p.id)}>
          <Edit size={15}/> Edit
         </button>
         <button className="secondary-action" onClick={()=>deleteProduct(p)}
          style={{color:"#b42318"}}>
          <Trash2 size={15}/> Delete
         </button>
        </div>
       </td>
      </tr>)}</tbody>
     </table></div>}
  </div>
 </div>;
}
