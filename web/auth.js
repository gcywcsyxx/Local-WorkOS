(() => {
  'use strict';
  const main=document.querySelector('main'), form=document.querySelector('form');
  const message=document.querySelector('#message'), button=form.querySelector('button');
  async function payload(response) {
    try { return await response.json(); } catch { throw new Error('登录服务暂时不可用，请稍后重试。'); }
  }
  async function freshChallenge() {
    const response=await fetch('/auth/challenge',{credentials:'same-origin',cache:'no-store'});
    const data=await payload(response);
    if(!response.ok || typeof data.csrf!=='string' || data.csrf.length<24) throw new Error(data.error || '无法获取登录挑战，请稍后重试。');
    document.querySelector('#csrf').value=data.csrf;
    return data.csrf;
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault(); button.disabled=true; message.textContent='正在验证…';
    const setup=main.dataset.mode==='setup', password=form.elements.password.value;
    const body=JSON.stringify({username:form.elements.username.value,password,remember:form.elements.remember.checked});
    try {
      let response,data;
      for(let attempt=0;attempt<(setup?1:2);attempt++) {
        const csrf=setup?document.querySelector('#csrf').value:await freshChallenge();
        response=await fetch(setup?'/auth/setup':'/auth/login',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body});
        data=await payload(response);
        if(!setup && response.status===409 && data.code==='login_challenge_expired' && attempt===0) continue;
        break;
      }
      if(!response.ok) {
        if(data.code==='login_challenge_expired') throw new Error('浏览器未能保存本站登录 Cookie。请允许本站 Cookie，并关闭其他正在提交登录的标签页后重试。');
        throw new Error(data.error||'登录失败');
      }
      form.elements.password.value='';
      if(setup) {
        form.hidden=true; message.textContent='密码已保存（仅保存加盐哈希）。现在可以打开公网地址，用已配置的账号登录。';
        document.querySelector('#public-link').hidden=false;
      } else window.location.assign('/');
    } catch(error) { message.textContent=error.message; } finally { button.disabled=false; }
  });
})();
