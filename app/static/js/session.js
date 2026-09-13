// Cookies HttpOnly live on the server. This client helper is not authorization.
(() => {
  const original = window.fetch.bind(window);
  window.fetch = async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    const headers = new Headers(options.headers || {});
    if (['POST','PUT','PATCH','DELETE'].includes(method)) headers.set('X-C1-Request','1');
    const response = await original(url, {...options, headers, credentials:'same-origin'});
    if (response.status === 401 && !String(url).includes('/api/auth/') && location.pathname !== '/') location.assign('/');
    return response;
  };
  window.c1Logout = async () => {
    await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    localStorage.removeItem('c1_demo_session');location.assign('/');
  };
})();
