
class ApiClient{
  constructor(base, token){
    this.base = base;
    this.token = token;
  }
  _headers(){
    return { 'Content-Type':'application/json', 'Authorization':`Bearer ${this.token}`};
  }
  get(path){ return fetch(this.base+path, {headers:this._headers()}).then(r=>r.json()); }
  post(path, body){ return fetch(this.base+path,{method:'POST',headers:this._headers(),body:JSON.stringify(body)}).then(r=>r.json());}
  put(path, body){ return fetch(this.base+path,{method:'PUT',headers:this._headers(),body:JSON.stringify(body)}).then(r=>r.json());}
}
