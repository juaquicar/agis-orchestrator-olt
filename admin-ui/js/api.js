// js/api.js

class ApiClient {
  constructor(base) {
    this.base = base;
  }

  _headers() {
    return { 'Content-Type': 'application/json' };
  }

  async get(path, params = {}) {
    let url = this.base + path;
    const q = new URLSearchParams(params).toString();
    if (q) url += `?${q}`;
    const res = await fetch(url, { headers: this._headers() });
    if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
    return await res.json();
  }

  async patch(path, body) {
    const res = await fetch(this.base + path, {
      method: 'PATCH',
      headers: this._headers(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`PATCH ${path} failed: ${res.status} ${res.statusText}`);
    return await res.json();
  }
}

// IMPORTANTE: el admin-ui llama al API vía nginx en /api
export const API = new ApiClient('/api');

// CTOs (AGIS passthrough)
export function getCTOGeoJSON() {
  return API.get('/ctos/geojson');
}

// UI: OLTs / PONs
export function getOltList() {
  return API.get('/ui/olts');
}

export function getPonList(oltId) {
  return API.get(`/ui/olts/${encodeURIComponent(oltId)}/pons`);
}

// UI: ONTs en mapa (GeoJSON)
export function getOntGeo({ bbox, olt_id, pon_id }) {
  // aquí NO mandamos params opcionales; queremos forzar OLT+PON en mapa
  return API.get('/ui/onts/geo', { bbox, olt_id, pon_id });
}

// UI: ONTs sin ubicar paginadas (por OLT+PON)
export function getUnlocatedOnts({ olt_id, pon_id, limit = 200, offset = 0 }) {
  return API.get('/ui/onts', { olt_id, pon_id, only_unlocated: 1, limit, offset });
}

// UI: Árbol OLT->PON con counts de ONTs sin ubicar
export function getUnlocatedGroups() {
  return API.get('/ui/unlocated/groups');
}
