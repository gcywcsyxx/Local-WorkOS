const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const script=fs.readFileSync(path.join(__dirname,'../web/auth.js'),'utf8');
const a='fresh-challenge-A-0123456789012345',b='fresh-challenge-B-0123456789012345';
const expired={status:409,data:{code:'login_challenge_expired',error:'expired'}};
async function run(responses,setup=false){
  let submit; const calls=[],redirects=[];
  const csrf={value:'stale-page-challenge'},message={textContent:''},button={disabled:false},link={hidden:true};
  const form={elements:{username:{value:'workos-user'},password:{value:'synthetic-only-password'},remember:{checked:true}},querySelector:()=>button,addEventListener:(_,handler)=>{submit=handler;},hidden:false};
  const nodes={'main':{dataset:{mode:setup?'setup':'login'}},'form':form,'#message':message,'#csrf':csrf,'#public-link':link};
  const fetch=async(url,options)=>{calls.push({url,options});const item=responses.shift();assert.ok(item,'unexpected extra request');return {status:item.status,ok:item.status>=200&&item.status<300,json:async()=>item.data};};
  vm.runInNewContext(script,{document:{querySelector:key=>nodes[key]},window:{location:{assign:url=>redirects.push(url)}},fetch,JSON,Error});
  await submit({preventDefault(){}});assert.equal(responses.length,0);assert.equal(button.disabled,false);return {calls,redirects,csrf,message,form,link};
}
(async()=>{
  let result=await run([{status:200,data:{csrf:a}},{status:200,data:{ok:true}}]);
  assert.deepEqual(result.calls.map(x=>x.url),['/auth/challenge','/auth/login']);
  assert.equal(result.calls[1].options.headers['X-CSRF-Token'],a);assert.equal(result.calls[0].options.credentials,'same-origin');assert.equal(result.calls[0].options.cache,'no-store');assert.deepEqual(result.redirects,['/']);
  result=await run([{status:200,data:{csrf:a}},expired,{status:200,data:{csrf:b}},{status:200,data:{ok:true}}]);
  assert.deepEqual(result.calls.map(x=>x.url),['/auth/challenge','/auth/login','/auth/challenge','/auth/login']);assert.equal(result.calls[3].options.headers['X-CSRF-Token'],b);assert.deepEqual(result.redirects,['/']);
  result=await run([{status:200,data:{csrf:a}},{status:403,data:{error:'incorrect password'}}]);
  assert.equal(result.calls.length,2);assert.equal(result.form.elements.password.value,'synthetic-only-password');assert.match(result.message.textContent,/incorrect password/);
  result=await run([{status:200,data:{csrf:a}},expired,{status:200,data:{csrf:b}},expired]);
  assert.equal(result.calls.length,4);assert.match(result.message.textContent,/Cookie/);assert.equal(result.redirects.length,0);
  result=await run([{status:200,data:{ok:true}}],true);assert.deepEqual(result.calls.map(x=>x.url),['/auth/setup']);assert.equal(result.form.hidden,true);assert.equal(result.link.hidden,false);
  console.log('PASS: 5 frontend login recovery scenarios');
})().catch(error=>{console.error(error);process.exitCode=1;});
