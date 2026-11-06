import {useEffect, useState} from "react";
import {Plus, Save, ArrowUp, ArrowDown, Eye, EyeOff, RefreshCw} from "lucide-react";

const API = "http://127.0.0.1:8000/api/v1";
const modules = [
 ["products","Books & Products"],["inventory","Inventory"],
 ["purchases","Purchases"],["sales","Sales & Billing"],
 ["customers","Customers"],["suppliers","Suppliers"],
 ["gst","GST & Tax"],["accounting","Accounting"],
 ["staff","Staff & Permissions"],["reports","Reports"]
];
const types = [
 ["text","Text"],["long_text","Long text"],["number","Whole number"],
 ["decimal","Decimal"],["date","Date"],["dropdown","Dropdown"],
 ["multi_select","Multi-select"],["checkbox","Checkbox"],
 ["email","Email"],["phone","Phone"]
];

export default function CustomFieldsPanel({tenant}) {
 const [moduleKey,setModuleKey] = useState("products");
 const [fields,setFields] = useState([]);
 const [label,setLabel] = useState("");
 const [type,setType] = useState("text");
 const [options,setOptions] = useState("");
 const [required,setRequired] = useState(false);
 const [busy,setBusy] = useState(false);
 const [error,setError] = useState("");
 const [message,setMessage] = useState("");

 const headers = {"Content-Type":"application/json","X-Tenant-Code":tenant};

 async function call(path, options={}) {
  const response = await fetch(API+path,{...options,headers:{...headers,...(options.headers||{})}});
  const data = await response.json().catch(()=>({detail:"Unexpected server response"}));
  if(!response.ok) throw new Error(data.detail||"Request failed");
  return data;
 }

 async function load() {
  setBusy(true);setError("");setMessage("");
  try {
   const data = await call("/custom-fields?module_key="+moduleKey);
   setFields(data.fields||[]);
  } catch(e) {setError(e.message);}
  finally {setBusy(false);}
 }

 useEffect(()=>{load();},[tenant,moduleKey]);

 async function addField(e) {
  e.preventDefault();setError("");setMessage("");
  const choices = options.split("\n").map(x=>x.trim()).filter(Boolean);
  try {
   await call("/custom-fields",{method:"POST",body:JSON.stringify({
    module_key:moduleKey,label:label.trim(),field_type:type,
    options:choices,is_required:required
   })});
   setLabel("");setOptions("");setRequired(false);
   setMessage("Field created.");
   await load();
  } catch(e) {setError(e.message);}
 }

 async function toggle(field) {
  try {
   await call("/custom-fields/"+field.id,{method:"PUT",body:JSON.stringify({is_active:!field.is_active})});
   await load();
  } catch(e) {setError(e.message);}
 }

 async function move(index, direction) {
  const next=[...fields];
  const target=index+direction;
  if(target<0||target>=next.length) return;
  [next[index],next[target]]=[next[target],next[index]];
  setFields(next);
  try {
   await call("/custom-fields/reorder?module_key="+moduleKey,{
    method:"PUT",body:JSON.stringify({field_ids:next.map(x=>x.id)})
   });
  } catch(e) {setError(e.message);await load();}
 }

 return <div className="custom-builder">
  <div className="welcome-row">
   <div><div className="eyebrow">FORM CUSTOMISATION</div>
    <h1>Custom Fields</h1>
    <p>Create fields for your bookstore without changing the application code.</p>
   </div>
  </div>

  <div className="data-panel">
   <h2>Choose module</h2>
   <select className="custom-module-select" value={moduleKey} onChange={e=>setModuleKey(e.target.value)}>
    {modules.map(([key,name])=><option key={key} value={key}>{name}</option>)}
   </select>
  </div>

  <form className="data-panel" onSubmit={addField}>
   <h2><Plus size={17}/> Create a field</h2>
   <div className="form-grid">
    <label>Field label *
     <input required maxLength="100" value={label} onChange={e=>setLabel(e.target.value)} placeholder="Example: Book condition"/>
    </label>
    <label>Field type
     <select value={type} onChange={e=>setType(e.target.value)}>
      {types.map(([key,name])=><option key={key} value={key}>{name}</option>)}
     </select>
    </label>
    {["dropdown","multi_select"].includes(type)&&
     <label className="custom-options">Options (one per line) *
      <textarea required rows="4" value={options} onChange={e=>setOptions(e.target.value)} placeholder={"New\nUsed\nDamaged"}/>
     </label>}
   </div>
   <label className="custom-required">
    <input type="checkbox" checked={required} onChange={e=>setRequired(e.target.checked)}/>
    This field is required
   </label>
   <div className="form-actions">
    <button className="primary-action" type="submit"><Save size={16}/> Create field</button>
   </div>
  </form>

  {error&&<div className="error-message">{error}</div>}
  {message&&<div className="success-message">{message}</div>}

  <div className="data-panel">
   <div className="panel-heading">
    <h2>Fields in this module</h2>
    <button className="secondary-action" type="button" onClick={load}><RefreshCw size={15}/> Refresh</button>
   </div>
   {busy?<p className="empty-state">Loading fields...</p>:fields.length===0?
    <p className="empty-state">No custom fields created for this module yet.</p>:
    <div className="custom-field-list">
     {fields.map((field,index)=><div className={`custom-field-row ${field.is_active?"":"custom-field-disabled"}`} key={field.id}>
      <div className="custom-field-order">
       <button type="button" title="Move up" disabled={index===0} onClick={()=>move(index,-1)}><ArrowUp size={15}/></button>
       <button type="button" title="Move down" disabled={index===fields.length-1} onClick={()=>move(index,1)}><ArrowDown size={15}/></button>
      </div>
      <div className="custom-field-info">
       <b>{field.label}</b>
       <small>{field.field_type.replace("_"," ")} · {field.is_required?"Required":"Optional"}{field.options.length?" · "+field.options.join(", "):""}</small>
      </div>
      <button className="secondary-action" type="button" onClick={()=>toggle(field)}>
       {field.is_active?<><EyeOff size={15}/> Deactivate</>:<><Eye size={15}/> Activate</>}
      </button>
     </div>)}
    </div>}
  </div>
 </div>;
}
