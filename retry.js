// Retry only idempotent reads; never repeat login, key rotation or account changes.
(() => {
  const original=window.fetch.bind(window);
  window.fetch=async(input,options={})=>{
    const url=typeof input==='string'?new URL(input,location.href):null;
    const method=String(options.method||'GET').toUpperCase();
    const eligible=url&&url.origin==='https://codex-usage-api.onrender.com'&&method==='GET'&&['/health','/api/data'].includes(url.pathname);
    if(!eligible)return original(input,options);
    for(let attempt=0;attempt<3;attempt++){
      try{
        const timeout=AbortSignal.timeout(30000),signal=options.signal?AbortSignal.any([options.signal,timeout]):timeout;
        const response=await original(input,{...options,signal});
        if(![502,503,504].includes(response.status)||attempt===2)return response;
        await response.body?.cancel();
      }catch(error){if(attempt===2||options.signal?.aborted)throw error;}
      await new Promise(resolve=>setTimeout(resolve,[2000,5000][attempt]));
    }
  };
})();
