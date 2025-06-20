// js/api.js
class ApiClient {
  constructor(base) {
    this.base = base;
  }

  _headers() {
    return {
      'Content-Type': 'application/json'
    };
  }

  async get(path) {
    const res = await fetch(this.base + path, {
      headers: this._headers()
    });
    if (!res.ok) {
      throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
    }
    return await res.json();
  }

  async patch(path, body) {
    const res = await fetch(this.base + path, {
      method: 'PATCH',
      headers: this._headers(),
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      throw new Error(`PATCH ${path} failed: ${res.status} ${res.statusText}`);
    }
    return await res.json();
  }

  // Si necesitas más métodos (POST, PUT…), añádelos aquí
}

export const API = new ApiClient('/api');
