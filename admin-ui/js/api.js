// js/api.js
class ApiClient {
  constructor(base) {
    this.base = base;
  }

  _headers() {
    return { 'Content-Type': 'application/json' };
  }

  // Ahora acepta opcionalmente un objeto params para query string
  async get(path, params = {}) {
    let url = this.base + path;
    const q = new URLSearchParams(params).toString();
    if (q) url += `?${q}`;
    const res = await fetch(url, { headers: this._headers() });
    if (!res.ok) {
      throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
    }
    return await res.json();
  }

  async patch(path, body) {
    const res = await fetch(this.base + path, {
      method: 'PATCH',
      headers: this._headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      throw new Error(`PATCH ${path} failed: ${res.status} ${res.statusText}`);
    }
    return await res.json();
  }
}

export const API = new ApiClient('/api');


export function getCTOList() {
  return API.get('/ctos/list');
}
export function getCTOGeoJSON() {
  return API.get('/ctos/geojson');
}