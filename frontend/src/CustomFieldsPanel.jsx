import {useEffect, useState} from "react";
import {
 Plus, Save, ArrowUp, ArrowDown, Eye, EyeOff,
 RefreshCw, Pencil, Trash2, X, GripVertical,
 Settings2, Layers3, CheckCircle2
} from "lucide-react";

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
 ["email","Email"],["phone","Phone"],["product","Product selector"],
 ["stock_quantity","Stock quantity"],["adjustment_reason","Adjustment reason"]
];

const inputClass = "w-full rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/10";
const labelClass = "mb-2 block text-xs font-semibold tracking-wide text-slate-600";
const buttonBase = "inline-flex items-center justify-center gap-2 rounded-xl px-3.5 py-2.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40";

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
 const [editingId,setEditingId] = useState(null);
 const [editLabel,setEditLabel] = useState("");
 const [editType,setEditType] = useState("text");
 const [editOptions,setEditOptions] = useState("");
 const [editRequired,setEditRequired] = useState(false);

 const headers = {"Content-Type":"application/json","X-Tenant-Code":tenant};

 async function call(path, options={}) {
  const response = await fetch(API+path,{
   ...options,
   headers:{...headers,...(options.headers||{})}
  });
  const data = await response.json().catch(()=>({detail:"Unexpected server response"}));
  if(!response.ok) throw new Error(data.detail||"Request failed");
  return data;
 }

 async function load() {
  setBusy(true);
  setError("");
  try {
   const data = await call("/custom-fields?module_key="+moduleKey);
   setFields(data.fields||[]);
  } catch(e) {
   setError(e.message);
  } finally {
   setBusy(false);
  }
 }

 useEffect(()=>{load();},[tenant,moduleKey]);

 async function addField(e) {
  e.preventDefault();
  setError("");
  setMessage("");
  const choices = options.split("\n").map(x=>x.trim()).filter(Boolean);
  try {
   await call("/custom-fields",{
    method:"POST",
    body:JSON.stringify({
     module_key:moduleKey,label:label.trim(),field_type:type,
     options:choices,is_required:required
    })
   });
   setLabel("");
   setOptions("");
   setType("text");
   setRequired(false);
   setMessage("Field created successfully.");
   await load();
  } catch(e) {
   setError(e.message);
  }
 }

 async function toggle(field) {
  setError("");
  setMessage("");
  try {
   await call("/custom-fields/"+field.id,{
    method:"PUT",
    body:JSON.stringify({is_active:!field.is_active})
   });
   setMessage(field.is_active?"Field deactivated.":"Field activated.");
   await load();
  } catch(e) {
   setError(e.message);
  }
 }

 function startEdit(field) {
  setEditingId(field.id);
  setEditLabel(field.label);
  setEditType(field.field_type);
  setEditOptions((field.options||[]).join("\n"));
  setEditRequired(Boolean(field.is_required));
  setError("");
  setMessage("");
 }

 function cancelEdit() {
  setEditingId(null);
  setEditLabel("");
  setEditOptions("");
  setEditType("text");
  setEditRequired(false);
 }

 async function saveEdit(field) {
  setError("");
  setMessage("");
  const choices = editOptions.split("\n").map(x=>x.trim()).filter(Boolean);
  try {
   await call("/custom-fields/"+field.id,{
    method:"PUT",
    body:JSON.stringify({
     label:editLabel.trim(),
     field_type:editType,
     options:choices,
     is_required:editRequired
    })
   });
   cancelEdit();
   setMessage("Field updated. Existing values remain linked.");
   await load();
  } catch(e) {
   setError(e.message);
  }
 }

 async function deleteField(field) {
  if(!window.confirm(
   `Remove "${field.label}" from active forms? Existing saved values will be preserved in the database. This action cannot be undone from the interface.`
  )) return;
  setError("");
  setMessage("");
  try {
   await call("/custom-fields/"+field.id,{method:"DELETE"});
   setMessage("Field removed from active forms. Historical data preserved.");
   await load();
  } catch(e) {
   setError(e.message);
  }
 }

 async function saveOrder(next) {
  setError("");
  try {
   await call("/custom-fields/reorder?module_key="+encodeURIComponent(moduleKey),{
    method:"PUT",
    body:JSON.stringify({field_ids:next.map(field=>field.id)})
   });
   setFields(next);
   setMessage("Field order saved.");
  } catch(e) {
   setError(e.message);
   await load();
  }
 }

 async function move(index,direction) {
  const next=[...fields];
  const target=index+direction;
  if(target<0||target>=next.length) return;
  [next[index],next[target]]=[next[target],next[index]];
  await saveOrder(next);
 }

 const selectedModule = modules.find(([key])=>key===moduleKey)?.[1] || moduleKey;

 return (
  <div className="mx-auto w-full max-w-7xl space-y-7 pb-10">

   <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
    <div>
     <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-emerald-700">
      <Settings2 size={15}/> Form configuration
     </div>
     <h1 className="text-3xl font-bold tracking-tight text-slate-900">Custom Fields</h1>
     <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
      Configure additional information for each ERP module without changing application code.
     </p>
    </div>
    <div className="flex items-center gap-2 rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-xs font-semibold text-emerald-800">
     <CheckCircle2 size={16}/> Dynamic form builder
    </div>
   </div>

   {error && (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
     {error}
    </div>
   )}
   {message && (
    <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
     {message}
    </div>
   )}

   <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
    <div className="mb-4 flex items-center gap-3">
     <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700">
      <Layers3 size={19}/>
     </div>
     <div>
      <h2 className="text-sm font-bold text-slate-900">Choose a module</h2>
      <p className="mt-1 text-xs text-slate-500">Select where these custom fields will appear.</p>
     </div>
    </div>
    <div className="max-w-xl">
     <select className={inputClass} value={moduleKey} onChange={e=>setModuleKey(e.target.value)}>
      {modules.map(([key,name])=><option key={key} value={key}>{name}</option>)}
     </select>
    </div>
   </section>

   <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
    <div className="border-b border-slate-100 bg-slate-50/70 px-5 py-4 sm:px-6">
     <div className="flex items-center gap-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-700 text-white">
       <Plus size={18}/>
      </div>
      <div>
       <h2 className="text-sm font-bold text-slate-900">Create a new field</h2>
       <p className="mt-1 text-xs text-slate-500">Add a field to {selectedModule}.</p>
      </div>
     </div>
    </div>
    <form className="space-y-5 p-5 sm:p-6" onSubmit={addField}>
     <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
      <label>
       <span className={labelClass}>Field label <span className="text-red-500">*</span></span>
       <input className={inputClass} required maxLength="100" value={label}
        onChange={e=>setLabel(e.target.value)} placeholder="e.g. Book condition"/>
      </label>
      <label>
       <span className={labelClass}>Field type</span>
       <select className={inputClass} value={type} onChange={e=>setType(e.target.value)}>
        {types.map(([key,name])=><option key={key} value={key}>{name}</option>)}
       </select>
      </label>
      {["dropdown","multi_select"].includes(type) && (
       <label className="md:col-span-2">
        <span className={labelClass}>Options <span className="text-red-500">*</span></span>
        <textarea className={inputClass+" min-h-28 resize-y"} required rows="4"
         value={options} onChange={e=>setOptions(e.target.value)}
         placeholder={"New\nUsed\nDamaged"}/>
        <span className="mt-1.5 block text-xs text-slate-400">Enter one option per line.</span>
       </label>
      )}
     </div>
     <div className="flex flex-col gap-4 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
      <label className="flex cursor-pointer items-center gap-3 text-sm text-slate-700">
       <input className="h-4 w-4 accent-emerald-700" type="checkbox"
        checked={required} onChange={e=>setRequired(e.target.checked)}/>
       <span><b className="font-semibold">Required field</b><span className="ml-1 text-slate-400">— users must fill it in</span></span>
      </label>
      <button className={buttonBase+" bg-emerald-700 px-5 py-3 text-white shadow-sm hover:bg-emerald-800"} type="submit" disabled={busy}>
       <Plus size={16}/> Create field
      </button>
     </div>
    </form>
   </section>

   <section className="space-y-4">
    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
     <div>
      <h2 className="text-lg font-bold text-slate-900">Configured fields</h2>
      <p className="mt-1 text-xs text-slate-500">{selectedModule} · {fields.length} field{fields.length===1?"":"s"}</p>
     </div>
     <button className={buttonBase+" border border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:text-emerald-800"}
      type="button" onClick={load} disabled={busy}>
      <RefreshCw size={14} className={busy?"animate-spin":""}/> Refresh
     </button>
    </div>

    {busy ? (
     <div className="rounded-2xl border border-slate-200 bg-white p-12 text-center text-sm text-slate-500">Loading fields...</div>
    ) : fields.length===0 ? (
     <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-5 py-14 text-center">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-400"><Layers3 size={22}/></div>
      <h3 className="text-sm font-bold text-slate-800">No custom fields yet</h3>
      <p className="mt-1 text-xs text-slate-500">Create your first field using the form above.</p>
     </div>
    ) : (
     <div className="space-y-3">
      {fields.map((field,index)=>(
       <article key={field.id} draggable
        onDragStart={e=>e.dataTransfer.setData("text/plain",String(index))}
        onDragOver={e=>e.preventDefault()}
        onDrop={e=>{
         e.preventDefault();
         const from=Number(e.dataTransfer.getData("text/plain"));
         if(!Number.isInteger(from)||from===index||from<0||from>=fields.length)return;
         const next=[...fields];
         const [picked]=next.splice(from,1);
         next.splice(index,0,picked);
         saveOrder(next);
        }}
        className={"overflow-hidden rounded-2xl border bg-white shadow-sm transition hover:shadow-md "+(field.is_active?"border-slate-200":"border-slate-200 opacity-75")}>

        <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:p-5">
         <div className="flex items-center gap-3 sm:w-10">
          <GripVertical className="hidden cursor-grab text-slate-300 sm:block" size={17}/>
          <div className="flex gap-1 sm:flex-col">
           <button className="rounded-lg p-1.5 text-slate-400 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-25"
            type="button" title="Move up" disabled={index===0} onClick={()=>move(index,-1)}><ArrowUp size={15}/></button>
           <button className="rounded-lg p-1.5 text-slate-400 hover:bg-emerald-50 hover:text-emerald-700 disabled:opacity-25"
            type="button" title="Move down" disabled={index===fields.length-1} onClick={()=>move(index,1)}><ArrowDown size={15}/></button>
          </div>
         </div>

         <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
           <h3 className="text-sm font-bold text-slate-900">{field.label}</h3>
           <span className={"rounded-full px-2.5 py-1 text-[10px] font-bold "+(field.is_active?"bg-emerald-50 text-emerald-700":"bg-slate-100 text-slate-500")}>
            {field.is_active?"ACTIVE":"INACTIVE"}
           </span>
           {field.is_required && <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[10px] font-bold text-amber-700">REQUIRED</span>}
          </div>
          <p className="mt-1.5 break-words text-xs capitalize text-slate-500">
           {field.field_type.replaceAll("_"," ")}{(field.options||[]).length?" · "+field.options.join(", "):""}
          </p>
         </div>

         <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <button className={buttonBase+" border border-slate-200 bg-white text-slate-700 hover:border-emerald-300 hover:text-emerald-800"}
           type="button" onClick={()=>editingId===field.id?cancelEdit():startEdit(field)}>
           {editingId===field.id?<X size={14}/>:<Pencil size={14}/>}
           {editingId===field.id?"Close":"Edit"}
          </button>
          <button className={buttonBase+" border border-slate-200 bg-white text-slate-600 hover:border-emerald-300 hover:text-emerald-800"}
           type="button" onClick={()=>toggle(field)}>
           {field.is_active?<EyeOff size={14}/>:<Eye size={14}/>}
           {field.is_active?"Deactivate":"Activate"}
          </button>
          <button className={buttonBase+" border border-red-100 bg-red-50 text-red-600 hover:bg-red-100"}
           type="button" onClick={()=>deleteField(field)}>
           <Trash2 size={14}/> Delete
          </button>
         </div>
        </div>

        {editingId===field.id && (
         <div className="border-t border-emerald-100 bg-emerald-50/30 p-4 sm:p-6">
          <div className="mb-5">
           <h4 className="text-sm font-bold text-slate-900">Edit field configuration</h4>
           <p className="mt-1 text-xs text-slate-500">Your existing saved values will remain associated with this field.</p>
          </div>
          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
           <label>
            <span className={labelClass}>Field label</span>
            <input className={inputClass} required maxLength="100" value={editLabel}
             onChange={e=>setEditLabel(e.target.value)}/>
           </label>
           <label>
            <span className={labelClass}>Field type</span>
            <select className={inputClass} value={editType} onChange={e=>setEditType(e.target.value)}>
             {types.map(([key,name])=><option key={key} value={key}>{name}</option>)}
            </select>
           </label>
           {["dropdown","multi_select"].includes(editType) && (
            <label className="md:col-span-2">
             <span className={labelClass}>Options — one per line</span>
             <textarea className={inputClass+" min-h-28 resize-y"} rows="4" value={editOptions}
              onChange={e=>setEditOptions(e.target.value)}/>
            </label>
           )}
          </div>
          <div className="mt-5 flex flex-col gap-4 border-t border-emerald-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
           <label className="flex items-center gap-3 text-sm text-slate-700">
            <input className="h-4 w-4 accent-emerald-700" type="checkbox" checked={editRequired}
             onChange={e=>setEditRequired(e.target.checked)}/>
            Required field
           </label>
           <div className="flex flex-wrap gap-2">
            <button className={buttonBase+" border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}
             type="button" onClick={cancelEdit}><X size={14}/> Cancel</button>
            <button className={buttonBase+" bg-emerald-700 px-5 text-white hover:bg-emerald-800"}
             type="button" onClick={()=>saveEdit(field)}><Save size={14}/> Save changes</button>
           </div>
          </div>
         </div>
        )}
       </article>
      ))}
     </div>
    )}
   </section>
  </div>
 );
}
