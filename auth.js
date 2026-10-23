(() => {
  const key='codex-usage-login-v1';
  const nativeFetch=window.fetch.bind(window);
  let saved;
  try{saved=JSON.parse(sessionStorage.getItem(key)||localStorage.getItem(key)||'null');}catch{}
  const configured=window.USAGE_API_BASE||'';
  if(configured&&saved?.base!==configured.replace(/\/$/,''))saved=null;
  const token=saved?.token;
  function reset(){sessionStorage.removeItem(key);localStorage.removeItem(key);location.reload();}
  window.fetch=async(input,options={})=>{
    if(typeof input!=='string'||!input.startsWith('/api/'))return nativeFetch(input,options);
    if(!token)return new Response(JSON.stringify({error:'请登录'}),{status:401});
    const headers=new Headers(options.headers);headers.set('Authorization','Bearer '+token);
    const response=await nativeFetch(saved.base+input,{...options,headers,credentials:'omit',redirect:'error'});
    if(response.status===401)reset();return response;
  };
  if(token){
    const logout=document.createElement('button');logout.textContent='退出登录';
    logout.onclick=async()=>{try{await fetch('/api/auth/logout',{method:'POST'});}catch{}reset();};
    document.querySelector('header').append(logout);return;
  }
  document.querySelector('main').hidden=true;
  document.body.insertAdjacentHTML('afterbegin',`<section class="panel" style="max-width:440px;margin:10vh auto;padding:28px"><h1>登录 Codex 用量看板</h1><p class="small">登录后按账号权限查看统计。</p><form id="login-form" style="display:grid;gap:14px"><label>服务器地址<input style="width:100%;box-sizing:border-box" id="login-base" type="url" required placeholder="https://你的后端.onrender.com"></label><label>账号<input style="width:100%;box-sizing:border-box" id="login-name" autocomplete="username" required></label><label>密码<input style="width:100%;box-sizing:border-box" id="login-password" type="password" autocomplete="current-password" required minlength="12" maxlength="256"></label><label><input id="login-remember" type="checkbox"> 在这台电脑记住登录（24 小时）</label><button type="submit">登录</button><details><summary>第一次启用服务</summary><p class="small">仅服务所有者首次设置管理员时使用。</p><input id="setup-key" type="password" placeholder="一次性初始化密钥" autocomplete="off"><button id="setup-admin" type="button">创建首个管理员</button></details><div class="small" id="login-status" role="status"></div></form></section>`);
  const el=id=>document.getElementById(id);
  el('login-base').value=configured;
  if(configured)el('login-base').readOnly=true;
  async function submit(setup){
    const status=el('login-status');status.textContent='正在连接…';
    try{
      const url=new URL(el('login-base').value.trim());
      if((url.protocol!=='https:'&&!(['127.0.0.1','localhost'].includes(url.hostname)&&url.protocol==='http:'))||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw Error('请填写 HTTPS 服务器根地址');
      const base=url.origin;
      const response=await nativeFetch(base+(setup?'/api/setup':'/api/auth/login'),{method:'POST',headers:{'Content-Type':'application/json',...(setup?{Authorization:'Bearer '+el('setup-key').value}:{})},body:JSON.stringify({username:el('login-name').value.trim(),password:el('login-password').value}),credentials:'omit',redirect:'error'});
      const value=await response.json();if(!response.ok)throw Error(value.error||'连接失败');
      if(setup){el('setup-key').value='';status.textContent='管理员已创建，请点击登录。';return;}
      const storage=el('login-remember').checked?localStorage:sessionStorage;
      sessionStorage.removeItem(key);localStorage.removeItem(key);storage.setItem(key,JSON.stringify({base,token:value.token}));location.reload();
    }catch(e){status.textContent=e instanceof TypeError?'无法连接服务器，请检查地址或稍后再试。免费服务首次唤醒可能需要约一分钟。':e.message;}
  }
  el('login-form').onsubmit=e=>{e.preventDefault();submit(false);};el('setup-admin').onclick=()=>submit(true);
})();
