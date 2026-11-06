import React,{useEffect,useState} from "react";

const API="http://127.0.0.1:8000/api/v1";

export default function FinanceModulesPage({tenant,mode="GST & Tax"}){
 const gst=mode==="GST & Tax";
 const [tab,setTab]=useState(gst?"GST Dashboard":"Chart of Accounts");
 const [data,setData]=useState(null);
 const [error,setError]=useState("");
 const [busy,setBusy]=useState(false);
 const [accounts,setAccounts]=useState([]);
 const [voucher,setVoucher]=useState({
  voucher_date:new Date().toISOString().slice(0,10),
  voucher_type:"Journal",narration:"",lines:[
   {account_id:"",debit:"",credit:""},
   {account_id:"",debit:"",credit:""}
  ]
 });
 const headers={"Content-Type":"application/json","X-Tenant-Code":tenant};
 async function get(path){
  const r=await fetch(API+path,{headers});
  const d=await r.json();
  if(!r.ok) throw Error(d.detail||"Unable to load data");
  return d;
 }
 async function load(){
  setError("");setBusy(true);
  try{
   let path="";
   if(gst){
    if(tab==="GST Dashboard")path="/gst/dashboard";
    else if(tab==="GST Settings")path="/gst/settings";
    else if(tab==="Tax Rates")path="/gst/tax-rates";
    else if(tab==="HSN/SAC")path="/gst/hsn-summary";
    else if(tab==="Sales Register")path="/gst/register/sales";
    else if(tab==="Purchase Register")path="/gst/register/purchases";
    else if(tab==="Input Tax Credit"||tab==="Output Tax")path="/gst/dashboard";
    else if(tab==="GSTR-1 Preparation")path="/gst/gstr1";
    else if(tab==="GSTR-3B Preparation")path="/gst/gstr3b";
    else path="/gst/dashboard";
   }else{
    if(tab==="Chart of Accounts")path="/accounting/accounts";
    else if(tab==="Journal Vouchers")path="/accounting/vouchers";
    else if(tab==="Trial Balance")path="/accounting/trial-balance";
    else if(tab==="Profit & Loss")path="/accounting/profit-loss";
    else if(tab==="Balance Sheet")path="/accounting/balance-sheet";
    else if(tab==="General Ledger")path="/accounting/accounts";
   }
   const result=await get(path);
   setData(result);
   if(!gst){
    const a=await get("/accounting/accounts");
    setAccounts(a);
   }
  }catch(e){setError(e.message);setData(null);}
  finally{setBusy(false);}
 }
 useEffect(()=>{load();},[tenant,tab,mode]);
 const gstTabs=["GST Dashboard","GST Settings","Tax Rates","HSN/SAC","Sales Register","Purchase Register","Input Tax Credit","Output Tax","GSTR-1 Preparation","GSTR-3B Preparation"];
 const acctTabs=["Chart of Accounts","Journal Vouchers","General Ledger","Trial Balance","Profit & Loss","Balance Sheet"];
 const tabs=gst?gstTabs:acctTabs;
 async function saveSettings(e){
  e.preventDefault();
  try{
   const r=await fetch(API+"/gst/settings",{method:"PUT",headers,body:JSON.stringify(data)});
   if(!r.ok)throw Error("Could not save GST settings");
   alert("GST settings saved");load();
  }catch(e){setError(e.message);}
 }
 async function postVoucher(e){
  e.preventDefault();
  try{
   const body={...voucher,lines:voucher.lines.map(x=>({
    account_id:Number(x.account_id),debit:Number(x.debit||0),
    credit:Number(x.credit||0)
   }))};
   const r=await fetch(API+"/accounting/vouchers",{method:"POST",headers,body:JSON.stringify(body)});
   const d=await r.json();if(!r.ok)throw Error(d.detail||"Voucher failed");
   alert(d.message+" "+d.voucher_no);setTab("Journal Vouchers");
  }catch(e){setError(e.message);}
 }
 const money=n=>new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR"}).format(Number(n||0));
 const pretty=k=>String(k).replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
 return <div style={{color:"#25352e"}}>
  <div style={{marginBottom:20}}>
   <div style={{fontSize:12,fontWeight:700,color:"#54816a"}}>VASUDHARE SALESFORCE / BUSINESS MANAGEMENT</div>
   <h1 style={{margin:"8px 0"}}>{mode}</h1>
   <p style={{color:"#748078"}}>{gst?"GST compliance, tax registers and return preparation.":"Double-entry books, vouchers and financial statements."}</p>
  </div>
  <div style={{display:"flex",gap:8,flexWrap:"wrap",marginBottom:20}}>
   {tabs.map(t=><button key={t} onClick={()=>setTab(t)} style={{
    border:"1px solid #dce5de",borderRadius:8,padding:"10px 13px",
    background:tab===t?"#e5f1e8":"white",color:"#285a3b",
    fontWeight:tab===t?700:500,cursor:"pointer"
   }}>{t}</button>)}
  </div>
  {error&&<div style={{padding:12,background:"#fff0ee",color:"#a33125",borderRadius:8,marginBottom:12}}>{error}</div>}
  {busy?<p>Loading...</p>:null}
  {!busy&&data&&gst&&tab==="GST Dashboard"&&<div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(180px,1fr))",gap:12}}>
   {[
    ["Output GST",data.output_tax],["Input GST",data.input_tax],
    ["Net GST Payable / Credit",data.net_tax],
    ["Sales Taxable Value",data.sales?.taxable],
    ["Purchase Taxable Value",data.purchases?.taxable]
   ].map(([k,v])=><div key={k} style={{background:"white",border:"1px solid #e0e8e1",borderRadius:12,padding:18}}>
    <div style={{color:"#728078",fontSize:13}}>{k}</div><h2>{money(v)}</h2>
   </div>)}
  </div>}
  {!busy&&data&&gst&&tab==="GST Settings"&&<form onSubmit={saveSettings} style={{background:"white",padding:20,borderRadius:12,maxWidth:600}}>
   {["gstin","business_state","state_code","financial_year"].map(k=><label key={k} style={{display:"block",marginBottom:14}}>
    <div style={{marginBottom:5}}>{pretty(k)}</div>
    <input value={data[k]||""} onChange={e=>setData({...data,[k]:e.target.value})} style={{padding:11,width:"100%",boxSizing:"border-box",border:"1px solid #dce5de",borderRadius:7}}/>
   </label>)}
   <button>Save GST Settings</button>
  </form>}
  {!busy&&Array.isArray(data)&&<div style={{overflowX:"auto",background:"white",borderRadius:10,border:"1px solid #e0e8e1"}}>
   {data.length===0?<p style={{padding:20}}>No records available yet.</p>:<table style={{borderCollapse:"collapse",width:"100%",fontSize:13}}>
    <thead><tr>{Object.keys(data[0]).map(k=><th key={k} style={{textAlign:"left",padding:12,background:"#eef4ef"}}>{pretty(k)}</th>)}</tr></thead>
    <tbody>{data.map((row,i)=><tr key={i}>{Object.entries(row).map(([k,v])=><td key={k} style={{padding:11,borderTop:"1px solid #edf0ed"}}>{typeof v==="number"&&/amount|tax|debit|credit|balance|value|net/i.test(k)?money(v):String(v??"")}</td>)}</tr>)}</tbody>
   </table>}
  </div>}
  {!gst&&tab==="Journal Vouchers"&&<form onSubmit={postVoucher} style={{background:"white",padding:18,borderRadius:12}}>
   <h3>New Journal Voucher</h3>
   <label>Date <input type="date" value={voucher.voucher_date} onChange={e=>setVoucher({...voucher,voucher_date:e.target.value})}/></label>
   <label style={{marginLeft:12}}>Type <select value={voucher.voucher_type} onChange={e=>setVoucher({...voucher,voucher_type:e.target.value})}><option>Journal</option><option>Receipt</option><option>Payment</option><option>Contra</option></select></label>
   <p><input placeholder="Narration" value={voucher.narration} onChange={e=>setVoucher({...voucher,narration:e.target.value})} style={{padding:10,width:"90%"}}/></p>
   {voucher.lines.map((line,i)=><div key={i} style={{display:"flex",gap:8,marginBottom:10,flexWrap:"wrap"}}>
    <select value={line.account_id} onChange={e=>setVoucher({...voucher,lines:voucher.lines.map((x,j)=>j===i?{...x,account_id:e.target.value}:x)})}>
     <option value="">Select account</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.code} - {a.name}</option>)}
    </select>
    <input placeholder="Debit" type="number" step="0.01" value={line.debit} onChange={e=>setVoucher({...voucher,lines:voucher.lines.map((x,j)=>j===i?{...x,debit:e.target.value}:x)})}/>
    <input placeholder="Credit" type="number" step="0.01" value={line.credit} onChange={e=>setVoucher({...voucher,lines:voucher.lines.map((x,j)=>j===i?{...x,credit:e.target.value}:x)})}/>
   </div>)}
   <button type="button" onClick={()=>setVoucher({...voucher,lines:[...voucher.lines,{account_id:"",debit:"",credit:""}]})}>Add line</button>
   <button style={{marginLeft:10}}>Post Balanced Voucher</button>
  </form>}
  {!gst&&!["Journal Vouchers"].includes(tab)&&Array.isArray(data)&&tab==="Profit & Loss"&&<h3>Profit & Loss statement</h3>}
  {!gst&&!["Journal Vouchers"].includes(tab)&&Array.isArray(data)&&tab==="Balance Sheet"&&<h3>Balance Sheet</h3>}
  <p style={{fontSize:12,color:"#77847b",marginTop:18}}>Figures are based on available posted transaction records. GST return screens are preparation reports, not government filings.</p>
 </div>;
}
