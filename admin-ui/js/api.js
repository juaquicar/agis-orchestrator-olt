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

      const usp = new URLSearchParams();
      for (const [k, v] of Object.entries(params || {})) {
        // No incluir valores undefined / null
        if (v === undefined || v === null) continue;
        // Opcional: si quieres ignorar strings vacíos también:
        if (typeof v === 'string' && v.trim() === '') continue;

        usp.append(k, String(v));
      }

      const q = usp.toString();
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


// UI: búsqueda de ONTs (por vendor_ont_id / serial)
export function searchOnts({ q, olt_id = null, pon_id = null, only_unlocated = 1, limit = 50, offset = 0 }) {
  const params = { q, only_unlocated, limit, offset };
  if (olt_id) params.olt_id = olt_id;
  if (pon_id) params.pon_id = pon_id;
  return API.get('/ui/onts/search', params);
}


//
// UI: CSV import/export ONTs
//
export async function downloadOntsCsv() {
  const res = await fetch('/api/ui/onts/csv');
  if (!res.ok) throw new Error(`GET /ui/onts/csv failed: ${res.status} ${res.statusText}`);
  return await res.blob();
}

export async function importOntsCsv(file) {
  const fd = new FormData();
  fd.append('file', file);

  const res = await fetch('/api/ui/onts/csv/import', {
    method: 'POST',
    body: fd,
  });
  if (!res.ok) {
    const txt = await res.text().catch(() => '');
    throw new Error(`POST /ui/onts/csv/import failed: ${res.status} ${res.statusText} ${txt}`);
  }
  return await res.json();
}
