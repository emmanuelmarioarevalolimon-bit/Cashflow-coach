(() => {
  let register = false;
  const $ = id => document.getElementById(id);
  $('switchAuth').addEventListener('click', () => {
    register=!register; $('registerFields').hidden=!register;
    $('submitAuth').textContent=register?'Crear empresa y entrar':'Iniciar sesión';
    $('switchAuth').textContent=register?'Ya tengo una cuenta':'Crear una cuenta del prototipo';
    $('password').autocomplete=register?'new-password':'current-password';
  });
  $('authForm').addEventListener('submit',async e=>{
    e.preventDefault();$('error').hidden=true;$('submitAuth').disabled=true;
    try{
      const body={email:$('email').value,password:$('password').value};
      if(register){body.company=$('company').value;body.currency=$('currency').value;}
      const r=await fetch('/api/auth/'+(register?'register':'login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const d=await r.json();
      if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));
      // Compatibility only; the backend verifies an independent HttpOnly session.
      localStorage.setItem('c1_demo_session','active');location.assign('/workspace');
    }catch(e){$('error').textContent=e.message;$('error').hidden=false;}
    finally{$('submitAuth').disabled=false;}
  });
})();
