// One history selection drives usage, models and observed quota curves.
let v3Kind='primary',v3Reset='',v3Account='',v3Scope='all',v3Chart='bar';
function v3Query(){return '/api/data?kind='+v3Kind+'&reset='+encodeURIComponent(v3Reset)+'&usage_reset='+encodeURIComponent(v3Reset)+'&codex_account='+encodeURIComponent(v3Account)+'&scope='+v3Scope;}
function v3Rates(registry){for(const [model,row]of Object.entries(registry?.rates||{}))if(Array.isArray(row)&&row.length===3&&row.every(n=>Number.isFinite(n)&&n>=0))rates[model]=row;el('rates').innerHTML=Object.entries(rates).map(([model,row])=>'<tr><td>'+esc(model)+'</td>'+row.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('');}
const v3Num=n=>!Number.isFinite(n)?'—':Math.abs(n)>0&&Math.abs(n)<.01?n.toFixed(5):new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(n);
const v3Color=(id,i)=>id==='unresolved'?'#8190a8':id==='unreported'?'#9bb2ff':palette[i%palette.length];
const v3Label=id=>id==='self'?'自己':id==='others'?'其他成员合计':id==='unreported'?'其他（估算）':id==='unresolved'?'暂无法归属':id;
function v3WindowLabel(w){const tag=w.basis==='actual_reset'?'实际重置窗口':w.basis==='rolling_activity'?'最近用量':w.basis==='daily_totals_no_intraday_timing'?'每日汇总':'活动时段（未确认重置）';return date(w.start)+' — '+date(w.end)+' · '+tag;}
function v3Download(name,text,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function v3Detail(){const e=data?.explorer;if(!e)return [];return e.details.map(r=>({...r,device:r.device_id,period_start:e.start,period_end:e.end,codex_account:data.codex_account}));}
function v3Export(json=false){const e=data.explorer,details=v3Detail();if(json)return v3Download('codex-usage-history.json',JSON.stringify({exported_at:new Date().toISOString(),codex_account:data.codex_account,scope:e.scope,history:e,details},null,2),'application/json');const columns=['members','device','model','period_start','period_end','input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens','standard_credits','relative_share_percent','priced','basis'];const cell=v=>'"'+String(v??'').replace(/^[=+@-]/,"'$&").replaceAll('"','""')+'"';v3Download('codex-usage-models.csv','\ufeff'+[columns,...details.map(r=>columns.map(k=>r[k]))].map(r=>r.map(cell).join(',')).join('\r\n'),'text/csv;charset=utf-8');}
function v3ChartSvg(rows,keys,start,end,unit){
 const span=end-start;if(!(span>0))return '<text x="30" y="90" fill="#9aaec5">此时段没有可绘制的时间记录</text>';
 const bins=Array.from({length:24},(_,i)=>({at:start+i*span/24,values:Object.fromEntries(keys.map(k=>[k,0]))}));
 for(const row of rows||[]){const l=Date.parse(row.at),r=Date.parse(row.end);if(r<=l)continue;for(const b of bins){const overlap=Math.max(0,Math.min(r,b.at+span/24)-Math.max(l,b.at))/(r-l);for(const k of keys)b.values[k]+=overlap*(row.groups?.[k]||0);}}
 const max=Math.max(1e-9,...bins.map(b=>Object.values(b.values).reduce((a,b)=>a+b,0)));let svg='';
 keys.forEach((key,k)=>{let path='';bins.forEach((b,i)=>{const x=45+i*30,y=210-170*b.values[key]/max;
  if(v3Chart==='line')path+=(i?' L':'M')+x+','+y;
  else{const before=keys.slice(0,k).reduce((a,id)=>a+b.values[id],0);svg+='<rect x="'+x+'" y="'+(210-170*(before+b.values[key])/max)+'" width="25" height="'+(170*b.values[key]/max)+'" fill="'+v3Color(key,k)+'"><title>'+esc(date(new Date(b.at).toISOString())+' '+v3Label(key)+' '+v3Num(b.values[key])+' '+unit)+'</title></rect>';}
 });if(path)svg+='<path d="'+path+'" fill="none" stroke="'+v3Color(key,k)+'" stroke-width="2"/>';});
 svg+='<text x="8" y="20" fill="#9aaec5" font-size="12">'+esc(unit)+'；上限 '+v3Num(max)+'</text>';
 for(let i=0;i<=6;i++)svg+='<text x="'+(45+i*115)+'" y="245" text-anchor="middle" fill="#9aaec5" font-size="11">'+esc(new Date(start+i*span/6).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}))+'</text>';
 return svg;
}
function v3CurveSvg(curves,start,end){
 let svg='';for(const [i,c]of curves.entries()){let path='',previous=null;
  for(const p of c.points){const time=Date.parse(p.at),x=45+690*(time-start)/Math.max(1,end-start),y=20+190*(100-p.remaining)/100;
   const resetChanged=previous&&previous.resets_at!==p.resets_at;path+=(previous&&!resetChanged?' L':' M')+x+','+y;
   svg+='<circle cx="'+x+'" cy="'+y+'" r="3.5" fill="'+v3Color(c.id,i)+'"><title>'+esc(c.label+' '+date(p.at)+' 剩余 '+v3Num(p.remaining)+'%')+'</title></circle>';previous=p;
  }
  if(path&&!['unidentified_device','unidentified_legacy_archive'].includes(c.basis))svg+='<path d="'+path+'" fill="none" stroke="'+v3Color(c.id,i)+'" stroke-width="2"/>';
 }
 for(const n of [0,25,50,75,100])svg+='<text x="5" y="'+(24+190*(100-n)/100)+'" fill="#9aaec5" font-size="11">'+n+'%</text>';
 for(let i=0;i<=6;i++)svg+='<text x="'+(45+i*115)+'" y="245" text-anchor="middle" fill="#9aaec5" font-size="11">'+esc(new Date(start+i*(end-start)/6).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}))+'</text>';
 return svg+(curves.length?'':'<text x="55" y="95" fill="#9aaec5">这个时段未保存额度快照；历史用量和模型折算仍可查看。</text>');
}
function v3Render(){
 const e=data?.explorer;if(!e)return;v3Reset=String(e.reset);
 const ws=e.windows||[],wi=ws.findIndex(w=>String(w.reset)===String(e.reset));
 el('v3-window').innerHTML=ws.map(w=>'<option value="'+esc(w.reset)+'" '+(String(w.reset)===String(e.reset)?'selected':'')+'>'+esc(v3WindowLabel(w))+'</option>').join('');
 el('v3-prev').disabled=wi<0||wi>=ws.length-1;el('v3-next').disabled=wi<=0;
 el('v3-period').textContent=date(e.start)+' — '+date(e.end)+'；已自动隐藏没有活动、没有额度消耗证据的窗口。'+(e.basis==='daily_totals_no_intraday_timing'?'这里只能确定每日汇总，未虚构 5h 明细。':e.basis==='activity_time_block'?'这是有实际活动的 5h 时间段，未冒充官方重置窗口。':'');
 let metric=el('v3-chart-metric').value,view,unit;
 if(metric==='tokens'){view=e.tokens;unit='token';}
 else if(metric==='quota'){
  const h=data.history,valid=e.scope==='account'&&String(h?.reset)===String(e.reset);
  const a=valid?h.attribution:null;view=a?{groups:{...a.groups,...(a.other_percent>0?{unreported:a.other_percent}:{}),...(a.unresolved_percent>0?{unresolved:a.unresolved_percent}:{})},rows:(a.rows||[]).map(r=>({...r,groups:{...r.groups,unreported:r.other||0,unresolved:r.unresolved||0}}))}:{groups:{},rows:[]};unit='额度百分点（经验估算）';
 }else{view=e.credits;unit='相对额度 / 标准积分';}
 const entries=Object.entries(view.groups||{}).filter(([,n])=>n>0),sum=entries.reduce((n,[,v])=>n+v,0);let offset=0;
 const gradient=entries.map(([k,v],i)=>{const from=offset;offset+=100*v/Math.max(1e-12,sum);return v3Color(k,i)+' '+from+'% '+offset+'%';});
 el('v3-pie').innerHTML='<div role="img" aria-label="成员相对消耗分布" style="width:190px;height:190px;border-radius:50%;background:'+(sum?'conic-gradient('+gradient.join(',')+')':'#293548')+'"></div><div>'+entries.map(([id,n],i)=>'<p><i class="swatch" style="background:'+v3Color(id,i)+'"></i>'+esc(v3Label(id))+'：'+v3Num(n)+' '+esc(unit)+' · '+v3Num(100*n/sum)+'%</p>').join('')+(entries.length?'':'<p>此口径暂无可折算数据。可切换实际 token；已保存的额度曲线仍显示在下方。</p>')+'</div>';
 el('v3-estimation').textContent=e.pricing_notice+' '+(e.credits.unpriced_tokens>0?'另有 '+fmt(e.credits.unpriced_tokens)+' token 的模型未配置权重，未按零计价。':'')+(metric==='quota'?'官方账号扣减与设备估算分开；此口径需选择对应账号的实际重置窗口。':'');
 const start=Math.max(Date.parse(e.start),Date.parse(el('v3-from').value)||-Infinity),end=Math.min(Date.parse(e.end),Date.parse(el('v3-to').value)||Infinity);
 el('v3-activity').innerHTML=v3ChartSvg(view.rows,entries.map(([id])=>id),start,end,unit);
 // Observed curves are independent of token/credit/chart mode and calibration.
 const picker=el('v3-curve'),prior=picker.value,curves=e.curves||[];
 picker.innerHTML='<option value="all">全部已保存额度曲线（分开绘制）</option>'+curves.map(c=>'<option value="'+esc(c.id)+'">'+esc(c.label)+'</option>').join('');
 picker.value=curves.some(c=>c.id===prior)?prior:'all';
 const shown=picker.value==='all'?curves:curves.filter(c=>c.id===picker.value);
 el('v3-quota').innerHTML=v3CurveSvg(shown,start,end);
 el('v3-curve-legend').innerHTML=shown.map((c,i)=>'<span><i class="swatch" style="background:'+v3Color(c.id,i)+'"></i>'+esc(c.label)+' · '+c.points.length+' 个快照</span>').join(' / ');
 el('v3-model-rows').innerHTML=v3Detail().map(r=>'<tr><td>'+esc(r.members||r.device_id)+'</td><td>'+esc(r.device_id)+'</td><td>'+esc(r.model)+'</td>'+['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens'].map(k=>'<td>'+fmt(r[k])+'</td>').join('')+'<td>'+(r.standard_credits===null?'未配置权重':v3Num(r.standard_credits))+'</td><td>'+(r.relative_share_percent===null?'—':v3Num(r.relative_share_percent)+'%')+'</td></tr>').join('')||'<tr><td colspan="10">此窗口没有保存模型分钟明细。每日模型汇总可在下方设备模型表查看；不会把整日用量硬塞进这 5h。</td></tr>';
 el('v3-model-coverage').textContent='上表与当前所选时段一致。管理员可见每台设备模型；普通成员仅见自己的模型，其他成员只作消耗合计。'+e.retention_notice;
}
document.querySelector('.trend').insertAdjacentHTML('beforebegin',`<section id="v3-history" class="panel" style="margin-bottom:20px"><h2>历史额度、成员与模型消耗</h2><div class="toolbar"><select id="v3-kind"><option value="primary">5h 历史窗口</option><option value="secondary">周额度历史（按实际重置）</option></select><button id="v3-prev">← 更早</button><select id="v3-window"></select><button id="v3-next">较新 →</button><select id="v3-chart-scope"><option value="all">全部可见设备</option><option value="account">所选账号</option></select><select id="v3-chart-metric"><option value="credits">相对额度（标准积分）</option><option value="tokens">实际 token</option><option value="quota">额度百分点（经验估算）</option></select><select id="v3-chart"><option value="bar">柱状图</option><option value="line">折线图</option></select><label>图表起点<input id="v3-from" type="datetime-local"></label><label>终点<input id="v3-to" type="datetime-local"></label><button id="v3-json">导出 JSON</button><button id="v3-csv">导出模型 CSV</button></div><p id="v3-period" class="small"></p><p id="v3-estimation" class="small"></p><div id="v3-pie" style="display:flex;align-items:center;gap:24px;flex-wrap:wrap"></div><svg id="v3-activity" viewBox="0 0 800 260" role="img" aria-label="成员消耗柱状或折线图"></svg><h3>实际记录的剩余额度曲线</h3><select id="v3-curve"></select><p id="v3-curve-legend" class="small"></p><svg id="v3-quota" viewBox="0 0 800 260" role="img" aria-label="每个账号与设备实际记录的剩余额度曲线"></svg><p class="small">曲线直接来自已记录快照，不以校准通过为显示条件。不同账号、账号未标识的旧记录分开绘制，不拼接成同一账号账单。单个快照也显示圆点；重置处断线。</p><h3>当前窗口：成员、设备与模型</h3><p id="v3-model-coverage" class="small"></p><div class="tablewrap"><table><thead><tr><th>成员</th><th>设备</th><th>模型</th><th>输入</th><th>缓存</th><th>输出</th><th>推理</th><th>总 token</th><th>相对额度 / 标准积分</th><th>相对消耗占比</th></tr></thead><tbody id="v3-model-rows"></tbody></table></div></section>`);
const accountPicker=document.createElement('select');accountPicker.id='v3-codex-account';accountPicker.setAttribute('aria-label','选择 Codex 账号');el('v3-kind').before(accountPicker);
function v3Change(){v3Reset='';el('v3-from').value='';el('v3-to').value='';load();}
accountPicker.onchange=()=>{v3Account=accountPicker.value;v3Change();};
el('v3-kind').onchange=e=>{v3Kind=e.target.value;v3Change();};
el('v3-chart-scope').onchange=e=>{v3Scope=e.target.value;v3Change();};
el('v3-window').onchange=e=>{v3Reset=e.target.value;el('v3-from').value='';el('v3-to').value='';load();};
for(const [id,step]of [['v3-prev',1],['v3-next',-1]])el(id).onclick=()=>{const ws=data.explorer.windows,i=ws.findIndex(w=>String(w.reset)===String(data.explorer.reset));if(ws[i+step]){v3Reset=String(ws[i+step].reset);el('v3-from').value='';el('v3-to').value='';load();}};
el('v3-chart-metric').onchange=()=>{if(el('v3-chart-metric').value==='quota'&&v3Scope!=='account'){v3Scope='account';el('v3-chart-scope').value='account';v3Change();}else v3Render();};
el('v3-chart').onchange=e=>{v3Chart=e.target.value;v3Render();};el('v3-curve').onchange=v3Render;
for(const id of ['v3-from','v3-to'])el(id).onchange=v3Render;
el('v3-json').onclick=()=>v3Export(true);el('v3-csv').onclick=()=>v3Export(false);
function renderDeviceOverview(){
 if(!data?.device_overview)return;let note=el('v3-device-overview-notice');if(!note){note=document.createElement('p');note.id='v3-device-overview-notice';note.className='small';el('devices').before(note);}
 note.textContent=data.role==='admin'?'设备总览显示全部设备的已上传累计记录；下方历史区可按账号、时段和模型比较。':'自己的绑定设备始终可见；其他成员只显示所选账号的消耗合计。';
 [...el('devices').children].forEach((card,i)=>{const d=data.devices[i];if(!d?.account_labels)return;const p=document.createElement('p');p.className='small';p.textContent='账号归属：'+d.account_labels.join(' / ');card.append(p);});
}
const originalRender=render;render=function(){if(data?.codex_accounts){accountPicker.innerHTML=data.codex_accounts.map(a=>'<option value="'+esc(a.id)+'" '+(a.id===data.codex_account?'selected':'')+'>'+esc(a.label)+'</option>').join('');v3Account=data.codex_account;}v3Rates(data?.model_rates);originalRender();v3Render();renderDeviceOverview();};
el('quota-svg').closest('section').hidden=true;el('quota-attribution').closest('section').hidden=true;
load();
