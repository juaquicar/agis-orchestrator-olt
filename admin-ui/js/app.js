import {
  API,
  getCTOGeoJSON,
  getOltList,
  getPonList,
  getOntGeo,
  getUnlocatedOnts,
  getUnlocatedGroups,
  searchOnts,
  downloadOntsCsv,
  importOntsCsv
} from './api.js';

// ───────────────── DOM refs ─────────────────
const mapOltSelectEl = document.getElementById('map-olt-select');
const mapPonSelectEl = document.getElementById('map-pon-select');

const unlocatedTreeEl = document.getElementById('unlocated-tree');
const unlocatedCountEl = document.getElementById('unlocated-count');

const loadingOverlay = document.getElementById('loading-overlay');
const loadingText = document.getElementById('loading-text');
const statusText = document.getElementById('status-text');

const ontSearchQEl = document.getElementById('ont-search-q');
const ontSearchOnlyUnlocatedEl = document.getElementById('ont-search-only-unlocated');
const ontSearchResultsEl = document.getElementById('ont-search-results');


const btnOntsCsvDownloadEl = document.getElementById('btn-onts-csv-download');
const ontsCsvFileEl = document.getElementById('onts-csv-file');
const btnOntsCsvUploadEl = document.getElementById('btn-onts-csv-upload');
const ontsCsvResultEl = document.getElementById('onts-csv-result');

const ctoSearchQEl = document.getElementById('cto-search-q');
const ctoSearchResultsEl = document.getElementById('cto-search-results');


let ontMarkerById = new Map(); // ontId -> Leaflet marker
let ctoDict = {};
let ctoMarkerByUuid = new Map(); // uuid -> Leaflet marker
let _ctoSearchHighlight = null;  // círculo temporal


// ───────────────── UI helpers ─────────────────
function showLoading(msg = 'Cargando…') {
  if (!loadingOverlay || !loadingText) return;
  loadingText.textContent = msg;
  loadingOverlay.classList.remove('hidden');
}
function hideLoading() {
  if (!loadingOverlay) return;
  loadingOverlay.classList.add('hidden');
}
function setStatus(text) {
  if (!statusText) return;
  statusText.textContent = text;
}
function escapeHtml(str) {
  return String(str ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function getONTBounds() {
  if (!ontCluster) return null;
  if (!ontCluster.getLayers || ontCluster.getLayers().length === 0) return null;

  const b = ontCluster.getBounds();
  return (b && b.isValid && b.isValid()) ? b : null;
}

function fitToONTs() {
  const b = getONTBounds();
  if (b) map.fitBounds(b.pad(0.15));
}



function debounce(fn, ms = 250) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function renderSearchResults(items) {
  if (!ontSearchResultsEl) return;
  ontSearchResultsEl.innerHTML = '';

  if (!items.length) {
    ontSearchResultsEl.innerHTML = `<div class="muted" style="padding:6px 0;">Sin resultados</div>`;
    return;
  }

  for (const o of items) {
    const div = document.createElement('div');
    div.className = 'ont-item';
    const located = (o.lat != null && o.lon != null);
    const badge = located
      ? `<span class="tree-meta">[ubicada]</span>`
      : `<span class="tree-meta">[sin ubicar]</span>`;

    const serialTxt = (o.serial != null && String(o.serial).trim() !== '')
      ? escapeHtml(o.serial)
      : '<span class="muted">—</span>';

    const descTxt = (o.description != null && String(o.description).trim() !== '')
      ? escapeHtml(o.description)
      : '<span class="muted">—</span>';

    div.innerHTML = `
      ${escapeHtml(o.vendor_ont_id)}
      ${badge}
      <div class="tree-meta" style="margin-top:2px;">
        OLT ${escapeHtml(o.olt_name)} · PON ${escapeHtml(o.pon_id)}
      </div>
      <div class="tree-meta" style="margin-top:2px;">
        <span><b>SN</b> ${serialTxt}</span>
        &nbsp;·&nbsp;
        <span><b>Desc</b> ${descTxt}</span>
      </div>
    `;


    div.addEventListener('click', async () => {
      resetSelection();
      div.classList.add('selected');

      // Si NO está ubicada: modo locate
      if (!located) {
        selectedOntId = o.id;
        mode = 'locate';
        await ensureMapFilter(o.olt_id, o.olt_name, o.pon_id, o.pon_id);
        alert('ONT seleccionada. Haz click en el mapa para ubicarla.');
        return;
      }

      // Si está ubicada: ir a mapa y abrir popup
      await ensureMapFilter(o.olt_id, o.olt_name, o.pon_id, o.pon_id);

      // centra mapa y abre popup
      map.setView([o.lat, o.lon], Math.max(map.getZoom(), 18));

      // asegúrate de tener markers cargados y abrir popup
      await reloadMapOnly();
      const mk = ontMarkerById.get(String(o.id));
      if (mk) {
        // cluster: “saca” el marker si está agrupado
        ontCluster.zoomToShowLayer(mk, () => mk.openPopup());
      }
    });

    ontSearchResultsEl.appendChild(div);
  }
}



function highlightCto(latlng) {
  if (_ctoSearchHighlight) {
    try { map.removeLayer(_ctoSearchHighlight); } catch (e) {}
    _ctoSearchHighlight = null;
  }
  _ctoSearchHighlight = L.circle(latlng, { radius: 25, weight: 2, fillOpacity: 0.08 });
  _ctoSearchHighlight.addTo(map);
  setTimeout(() => {
    if (_ctoSearchHighlight) {
      try { map.removeLayer(_ctoSearchHighlight); } catch (e) {}
      _ctoSearchHighlight = null;
    }
  }, 1800);
}

function renderCtoSearchResults(items) {
  if (!ctoSearchResultsEl) return;
  ctoSearchResultsEl.innerHTML = '';

  if (!items.length) {
    ctoSearchResultsEl.innerHTML = `<div class="muted" style="padding:6px 0;">Sin resultados</div>`;
    return;
  }

  for (const c of items) {
    const div = document.createElement('div');
    // Reutiliza estilo existente (mismo look&feel que ONTs)
    div.className = 'ont-item';

    div.innerHTML = `
      ${escapeHtml(c.nombre || '')}
      <div class="tree-meta" style="margin-top:2px;">
        UUID ${escapeHtml(c.uuid)}
      </div>
    `;

    div.addEventListener('click', () => {
      const mk = ctoMarkerByUuid.get(c.uuid);
      const ll = c.latlng || (mk ? mk.getLatLng() : null);
      if (!ll) return;

      map.setView(ll, Math.max(map.getZoom(), 18));
      if (mk && mk.openPopup) mk.openPopup();

      highlightCto(ll);
    });

    ctoSearchResultsEl.appendChild(div);
  }
}


async function initOntSearch() {
  if (!ontSearchQEl || !ontSearchResultsEl || !ontSearchOnlyUnlocatedEl) return;

  const run = debounce(async () => {
    const q = (ontSearchQEl.value || '').trim();
    if (q.length < 2) {
      ontSearchResultsEl.innerHTML = '';
      return;
    }

    const only_unlocated = ontSearchOnlyUnlocatedEl.checked ? 1 : 0;

    showLoading('Buscando ONTs…');
    try {
      const resp = await searchOnts({
        q,
        only_unlocated,
        limit: 50,
        offset: 0
      });
      const items = Array.isArray(resp?.items) ? resp.items : [];
      renderSearchResults(items);
    } catch (err) {
      console.error(err);
      ontSearchResultsEl.innerHTML = `<div class="muted" style="padding:6px 0;">Error buscando</div>`;
    } finally {
      hideLoading();
    }
  }, 250);

  ontSearchQEl.addEventListener('input', run);
  ontSearchOnlyUnlocatedEl.addEventListener('change', run);
}


function scoreCtoMatch(q, uuid, nombre) {
  const ql = q.toLowerCase();
  const u = String(uuid || '').toLowerCase();
  const n = String(nombre || '').toLowerCase();

  if (u === ql) return 0;           // match exacto UUID
  if (u.startsWith(ql)) return 1;   // prefijo UUID
  if (u.includes(ql)) return 2;     // contiene UUID
  if (n.startsWith(ql)) return 3;   // prefijo nombre
  if (n.includes(ql)) return 4;     // contiene nombre
  return 999;
}

async function initCtoSearch() {
  if (!ctoSearchQEl || !ctoSearchResultsEl) return;

  const run = debounce(() => {
    const q = (ctoSearchQEl.value || '').trim();
    if (q.length < 2) {
      ctoSearchResultsEl.innerHTML = '';
      return;
    }

    // buscamos SOLO sobre lo ya renderizado / indexado en ctoDict
    const out = [];
    for (const [uuid, obj] of Object.entries(ctoDict || {})) {
      const nombre = obj?.nombre || '';
      const sc = scoreCtoMatch(q, uuid, nombre);
      if (sc < 999) out.push({ uuid, nombre, latlng: obj?.latlng, _sc: sc });
    }

    out.sort((a, b) => (a._sc - b._sc) || String(a.nombre).localeCompare(String(b.nombre)));
    renderCtoSearchResults(out.slice(0, 80));
  }, 200);

  ctoSearchQEl.addEventListener('input', run);
}


function getCTOBounds() {
  if (!ctoLayer) return null;

  const bounds = L.latLngBounds([]);
  let any = false;

  // Recorre lo que haya dentro: puede ser GeoJSON layer, marker, featureGroup, etc.
  ctoLayer.eachLayer((lyr) => {
    if (!lyr) return;

    // Si es un marker
    if (typeof lyr.getLatLng === 'function') {
      bounds.extend(lyr.getLatLng());
      any = true;
      return;
    }

    // Si es GeoJSON / FeatureGroup / LayerGroup con bounds
    if (typeof lyr.getBounds === 'function') {
      const b = lyr.getBounds();
      if (b && b.isValid && b.isValid()) {
        bounds.extend(b);
        any = true;
      }
      return;
    }
  });

  return (any && bounds.isValid()) ? bounds : null;
}

function fitToCTOs() {
  const b = getCTOBounds();
  if (b) map.fitBounds(b.pad(0.15));
}



// ───────────────── Estado ─────────────────
const PAGE_SIZE = 200;

let selectedOntId = null;
let mode = null; // 'locate' o 'assign'


let mapOltId = null;
let mapOltName = null;
let mapPonId = null;
let mapPonName = null;

const groupState = new Map(); // `${olt_id}::${pon_id}` -> { offset, done }

// ───────────────── Leaflet ─────────────────
const ctoIcon = L.icon({
  iconUrl: 'https://agis-eu.stratosgs.com/static/main/img/legend_v2/CA.svg',
  iconSize: [25, 25],
  iconAnchor: [12, 12],
  shadowUrl: 'https://unpkg.com/leaflet@1.9.3/dist/images/marker-shadow.png',
  shadowSize: [30, 30],
  shadowAnchor: [12, 12]
});

const map = L.map('map').setView([40.4168, -3.7038], 6);
L.tileLayer('https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png', {
  maxZoom: 22,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

const ontCluster = L.markerClusterGroup().addTo(map);
const ctoLayer = L.layerGroup().addTo(map);
const linkLayer = L.layerGroup().addTo(map);

function bboxFromMap() {
  const b = map.getBounds();
  return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(',');
}

function clearMapOntLayers() {
  ontCluster.clearLayers();
  linkLayer.clearLayers();
  ontMarkerById = new Map();
}

function resetSelection() {
  selectedOntId = null;
  mode = null;
  if (unlocatedTreeEl) {
    unlocatedTreeEl.querySelectorAll('.ont-item.selected')
      .forEach(el => el.classList.remove('selected'));
  }
}

// ───────────────── CTOs ─────────────────
async function loadCtos() {
  ctoLayer.clearLayers();
  ctoDict = {};
  ctoMarkerByUuid = new Map();

  const geo = await getCTOGeoJSON();
  L.geoJSON(geo, {
    pointToLayer: (f, latlng) => L.marker(latlng, { icon: ctoIcon }),
    onEachFeature: (f, layer) => {
      const { nombre, uuid } = f.properties;

      // index para búsqueda
      ctoDict[uuid] = { nombre, latlng: layer.getLatLng() };
      ctoMarkerByUuid.set(uuid, layer);

      layer.bindPopup(
        `<b>CTO:</b> ${escapeHtml(nombre)} <br> <b>UUID</b>: ${escapeHtml(uuid)}`
      );
      layer.on('click', () => handleCtoClick(uuid));
    }
  }).addTo(ctoLayer);
}


async function handleCtoClick(uuid) {
  if (!selectedOntId || mode !== 'assign') return;
  try {
    await API.patch(`/onts/${selectedOntId}`, { cto_uuid: uuid });
  } catch (err) {
    console.error(err);
    alert('Error asignando CTO');
    return;
  }
  resetSelection();
  await loadUnlocatedTree();
  await reloadMapOnly();
}

window.unassignCto = async (ontId) => {
  try {
    await API.patch(`/onts/${ontId}`, { cto_uuid: null });
  } catch (err) {
    console.error(err);
    alert('Error desasociando CTO');
    return;
  }
  await loadUnlocatedTree();
  await reloadMapOnly();
};

window.assignCto = (ontId) => {
  resetSelection();
  selectedOntId = ontId;
  mode = 'assign';
  alert('Pulsa sobre una CTO para asociarla.');
};

// Click en mapa para ubicar ONT
map.on('click', async e => {
  if (!selectedOntId || mode !== 'locate') return;
  const { lat, lng } = e.latlng;
  try {
    await API.patch(`/onts/${selectedOntId}`, { lat, lon: lng });
  } catch (err) {
    console.error(err);
    alert('Error ubicando ONT');
    return;
  }
  resetSelection();
  await loadUnlocatedTree();
  await reloadMapOnly();
});

// ───────────────── Filtros MAPA (solo carga con OLT+PON) ─────────────────
async function initMapFilters() {
  if (!mapOltSelectEl || !mapPonSelectEl) {
    console.error('[admin-ui] faltan #map-olt-select o #map-pon-select en el DOM');
    return;
  }

  // PON deshabilitado hasta seleccionar OLT
  mapPonSelectEl.disabled = true;
  mapPonSelectEl.innerHTML = `<option value="">-- Selecciona PON --</option>`;

  showLoading('Cargando OLTs (mapa)…');
  try {
    const resp = await getOltList();
    const items = Array.isArray(resp?.items) ? resp.items : [];

    mapOltSelectEl.innerHTML = `<option value="">-- Selecciona OLT --</option>`;
    for (const o of items) {
      const opt = document.createElement('option');
      opt.value = o.id;
      opt.textContent = o.name ?? String(o.id);
      mapOltSelectEl.appendChild(opt);
    }
  } finally {
    hideLoading();
  }

  mapOltSelectEl.addEventListener('change', async () => {
    mapOltId = mapOltSelectEl.value || null;
    mapOltName = mapOltId
      ? (mapOltSelectEl.options[mapOltSelectEl.selectedIndex]?.textContent || String(mapOltId))
      : null;

    // reset PON
    mapPonId = null;
    mapPonName = null;

    mapPonSelectEl.disabled = true;
    mapPonSelectEl.innerHTML = `<option value="">-- Selecciona PON --</option>`;

    clearMapOntLayers();

    if (!mapOltId) {
      setStatus('Mapa: selecciona OLT + PON para cargar ONTs');
      return;
    }

    showLoading('Cargando PONs (mapa)…');
    try {
      const resp = await getPonList(mapOltId);
      const items = Array.isArray(resp?.items) ? resp.items : [];

      mapPonSelectEl.innerHTML = `<option value="">-- Selecciona PON --</option>`;
      for (const p of items) {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = p.name ?? String(p.id);
        mapPonSelectEl.appendChild(opt);
      }
      mapPonSelectEl.disabled = false;
      setStatus(`Mapa: OLT ${mapOltName} | Selecciona PON`);
    } catch (err) {
      console.error(err);
      alert('Error cargando PONs');
      setStatus(`Mapa: OLT ${mapOltName} | Error cargando PONs`);
    } finally {
      hideLoading();
    }
  });

  mapPonSelectEl.addEventListener('change', async () => {
    mapPonId = mapPonSelectEl.value || null;
    mapPonName = mapPonId
      ? (mapPonSelectEl.options[mapPonSelectEl.selectedIndex]?.textContent || String(mapPonId))
      : null;

    clearMapOntLayers();

    if (!mapOltId || !mapPonId) {
      setStatus(`Mapa: OLT ${mapOltName || '-'} | Selecciona PON`);
      return;
    }

    await reloadMapOnly();
  });
}

// ───────────────── ONTs ubicadas en MAPA ─────────────────
async function reloadMapOnly() {
  // PROTECCIÓN: solo cargar si hay filtro completo
  if (!mapOltId || !mapPonId) {
    clearMapOntLayers();
    return;
  }

  showLoading('Cargando ONTs ubicadas (mapa)…');
  try {
    const bbox = bboxFromMap();
    const geo = await getOntGeo({ bbox, olt_id: mapOltId, pon_id: mapPonId });

    clearMapOntLayers();

    const features = geo?.features || [];
    let loadedCount = 0;

    for (const f of features) {
      const p = f.properties || {};
      const [lng, lat] = f.geometry.coordinates;
      const ontId = p.ont_id ?? p.id;
      if (!ontId) continue;

      const marker = L.marker([lat, lng], { draggable: true });
      ontMarkerById.set(String(ontId), marker);


      marker.on('dragend', async e => {
        const { lat: newLat, lng: newLon } = e.target.getLatLng();
        try {
          await API.patch(`/onts/${ontId}`, { lat: newLat, lon: newLon });
        } catch (err) {
          console.error(err);
          alert('Error al mover ONT');
          return;
        }
        await reloadMapOnly();
      });

      const oltName = p.olt_name ?? p.olt_id ?? mapOltName ?? '';
      const ponName = p.pon_id ?? mapPonName ?? mapPonId ?? '';

      let html = `<b>OLT:</b> ${escapeHtml(oltName)} <span style="color:#666">[${escapeHtml(p.olt_id)}]</span><br/>`;
      html += `<b>PON:</b> ${escapeHtml(ponName)}<br/>`;
      html += `<b>ONT:</b> ${escapeHtml(p.vendor_ont_id ?? '')}<br/>`;
        html += `<b>Serial:</b> ${escapeHtml(p.serial ?? '')}<br/>`;
        html += `<b>Descripción:</b> ${escapeHtml(p.description ?? '')}<br/>`;

      const cto_uuid = p.cto_uuid ?? null;
      if (cto_uuid && ctoDict[cto_uuid]) {
        html += `<b>CTO:</b> ${escapeHtml(ctoDict[cto_uuid].nombre)}<br/>`;
        html += `<button onclick="unassignCto('${ontId}')">Desasociar CTO</button>`;
      } else {
        html += `<button onclick="assignCto('${ontId}')">Asignar CTO</button>`;
      }

      marker.bindPopup(html);
      ontCluster.addLayer(marker);
      loadedCount += 1;

      if (cto_uuid && ctoDict[cto_uuid]) {
        linkLayer.addLayer(
          L.polyline([[lat, lng], ctoDict[cto_uuid].latlng], { weight: 1, dashArray: '4,2' })
        );
      }
    }

    setStatus(`Mapa: OLT ${mapOltName} | PON ${mapPonName} | ONTs visibles: ${loadedCount}`);
  } catch (err) {
    console.error(err);
    alert('Error cargando ONTs en mapa');
    setStatus(`Mapa: error cargando ONTs (OLT ${mapOltName || '-'} / PON ${mapPonName || '-'})`);
  } finally {
    hideLoading();
  }
}

// Recarga por movimiento SOLO si hay OLT+PON seleccionadas
map.on('moveend', async () => {
  if (!mapOltId || !mapPonId) return;
  await reloadMapOnly();
});

// ───────────────── Árbol UNLOCATED (independiente) ─────────────────
function groupKey(oltId, ponId) {
  return `${oltId}::${ponId}`;
}

async function ensureMapFilter(oltId, oltName, ponId, ponName) {
  // Aplica filtros al mapa y recarga, sin depender de que el usuario toque selects.
  if (!mapOltSelectEl || !mapPonSelectEl) return;

  // Si ya está, nada
  if (mapOltId === oltId && mapPonId === ponId) return;

  // set OLT
  mapOltId = oltId;
  mapOltName = oltName;
  mapOltSelectEl.value = oltId;

  // cargar PONs de esa OLT y setear PON
  mapPonSelectEl.disabled = true;
  mapPonSelectEl.innerHTML = `<option value="">-- Selecciona PON --</option>`;

  showLoading('Cargando PONs (mapa)…');
  try {
    const resp = await getPonList(oltId);
    const items = Array.isArray(resp?.items) ? resp.items : [];

    mapPonSelectEl.innerHTML = `<option value="">-- Selecciona PON --</option>`;
    for (const p of items) {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name ?? String(p.id);
      mapPonSelectEl.appendChild(opt);
    }
    mapPonSelectEl.disabled = false;

    mapPonId = ponId;
    mapPonName = ponName;
    mapPonSelectEl.value = ponId;
  } catch (err) {
    console.error(err);
  } finally {
    hideLoading();
  }

  await reloadMapOnly();
}

async function loadPonUnlocatedPage(oltId, oltName, ponId, ponName, container, reset = false) {
  const key = groupKey(oltId, ponId);

  if (reset || !groupState.has(key)) {
    groupState.set(key, { offset: 0, done: false });
    container.innerHTML = '';
  }

  const st = groupState.get(key);
  if (st.done) return;

  showLoading(`Cargando ONTs sin ubicar (${oltName} / PON ${ponName})…`);
  try {
    const resp = await getUnlocatedOnts({ olt_id: oltId, pon_id: ponId, limit: PAGE_SIZE, offset: st.offset });
    const items = resp?.items || [];

    st.offset += items.length;
    if (items.length < PAGE_SIZE) st.done = true;

    for (const o of items) {
      const div = document.createElement('div');
      div.className = 'ont-item';
        const serialTxt = (o.serial != null && String(o.serial).trim() !== '')
          ? escapeHtml(o.serial)
          : '<span class="muted">—</span>';

        const descTxt = (o.description != null && String(o.description).trim() !== '')
          ? escapeHtml(o.description)
          : '<span class="muted">—</span>';

        div.innerHTML = `
          ${escapeHtml(o.vendor_ont_id)} <span class="tree-meta">[${escapeHtml(oltId)}]</span>
          <div class="tree-meta" style="margin-top:2px;">
            <span><b>SN</b> ${serialTxt}</span>
            &nbsp;·&nbsp;
            <span><b>Desc</b> ${descTxt}</span>
          </div>
        `;

      div.addEventListener('click', async () => {
        resetSelection();
        div.classList.add('selected');

        // Selección para ubicar
        selectedOntId = o.id;
        mode = 'locate';

        // Muy importante: al pinchar una ONT, “hacemos aparecer” su contexto en el mapa
        await ensureMapFilter(oltId, oltName, ponId, ponName);

        alert('ONT seleccionada. Haz click en el mapa para ubicarla.');
      });

      container.appendChild(div);
    }

    let btn = container.querySelector('button.load-more');
    if (!btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'load-more';
      btn.textContent = 'Cargar más…';
      btn.addEventListener('click', async () => {
        await loadPonUnlocatedPage(oltId, oltName, ponId, ponName, container, false);
      });
      container.appendChild(btn);
    }

    btn.disabled = st.done;
    btn.textContent = st.done ? 'No hay más' : 'Cargar más…';
  } finally {
    hideLoading();
  }
}

async function loadUnlocatedTree() {
  if (!unlocatedTreeEl) return;

  groupState.clear();
  unlocatedTreeEl.innerHTML = '';

  showLoading('Cargando árbol de ONTs sin ubicar…');
  try {
    const resp = await getUnlocatedGroups();
    const items = Array.isArray(resp?.items) ? resp.items : [];

    const totalAll = items.reduce((acc, o) => acc + (o.count || 0), 0);
    if (unlocatedCountEl) unlocatedCountEl.textContent = totalAll ? `(${totalAll})` : '';

    for (const olt of items) {
      const oltDetails = document.createElement('details');
      oltDetails.className = 'tree-olt';

      const oltSummary = document.createElement('summary');
      oltSummary.innerHTML =
        `${escapeHtml(olt.olt_name)} <span class="tree-meta">(${olt.count}) [${escapeHtml(olt.olt_id)}]</span>`;
      oltDetails.appendChild(oltSummary);

      for (const pon of (olt.pons || [])) {
        const ponDetails = document.createElement('details');
        ponDetails.className = 'tree-pon';

        const ponSummary = document.createElement('summary');
        ponSummary.innerHTML =
          `PON ${escapeHtml(pon.name)} <span class="tree-meta">(${pon.count})</span>`;
        ponDetails.appendChild(ponSummary);

        const body = document.createElement('div');
        ponDetails.appendChild(body);

        ponDetails.addEventListener('toggle', async () => {
          if (!ponDetails.open) return;
          await loadPonUnlocatedPage(olt.olt_id, olt.olt_name, pon.id, pon.name, body, true);
        });

        oltDetails.appendChild(ponDetails);
      }

      unlocatedTreeEl.appendChild(oltDetails);
    }
  } catch (err) {
    console.error(err);
    alert('Error cargando árbol de ONTs sin ubicar');
  } finally {
    hideLoading();
  }
}

// -------------

async function initCsvControls() {
  if (!btnOntsCsvDownloadEl) return;

  btnOntsCsvDownloadEl.addEventListener('click', async () => {
    showLoading('Generando CSV…');
    try {
      const blob = await downloadOntsCsv();
      const url = URL.createObjectURL(blob);

      const a = document.createElement('a');
      const ts = new Date().toISOString().replaceAll(':', '').replaceAll('-', '').split('.')[0];
      a.href = url;
      a.download = `onts_${ts}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();

      URL.revokeObjectURL(url);
      if (ontsCsvResultEl) ontsCsvResultEl.textContent = 'CSV descargado.';
    } catch (err) {
      console.error(err);
      if (ontsCsvResultEl) ontsCsvResultEl.textContent = 'Error descargando CSV.';
      alert('Error descargando CSV');
    } finally {
      hideLoading();
    }
  });

  if (btnOntsCsvUploadEl && ontsCsvFileEl) {
    btnOntsCsvUploadEl.addEventListener('click', async () => {
      const file = ontsCsvFileEl.files && ontsCsvFileEl.files[0];
      if (!file) {
        alert('Selecciona un CSV primero.');
        return;
      }

      showLoading('Importando CSV…');
      try {
        const resp = await importOntsCsv(file);

        const errCount = Array.isArray(resp?.errors) ? resp.errors.length : 0;
        const msg = `Importación: procesadas=${resp.processed ?? 0}, insertadas=${resp.inserted ?? 0}, actualizadas=${resp.updated ?? 0}, omitidas=${resp.skipped ?? 0}, errores=${errCount}`;
        if (ontsCsvResultEl) ontsCsvResultEl.textContent = msg;

        if (errCount) {
          console.warn('Errores import CSV', resp.errors);
          alert(`Importación completada con ${errCount} errores. Revisa consola.`);
        }

        await loadUnlocatedTree();
        await reloadMapOnly();
      } catch (err) {
        console.error(err);
        if (ontsCsvResultEl) ontsCsvResultEl.textContent = 'Error importando CSV.';
        alert('Error importando CSV');
      } finally {
        hideLoading();
      }
    });
  }
}


// ───────────────── Bootstrap ─────────────────
(async function bootstrap() {
  showLoading('Inicializando…');
  try {
    await loadCtos();
    fitToCTOs();

    // Buscador CTOs (frontend-only sobre ctoDict/ctoLayer)
    await initCtoSearch();


    await initMapFilters();

    // Buscador ONTs
    await initOntSearch();

    // Árbol ONTs sin ubicar
    await loadUnlocatedTree();

    // Export CSV
    await initCsvControls();


    setStatus('Mapa: selecciona OLT + PON para cargar ONTs');
  } catch (err) {
    console.error(err);
    alert('Error inicializando la UI');
    setStatus('Error inicializando la UI');
  } finally {
    hideLoading();
  }
})();


// ───────────────── Plugins Leaflet (geocoder / fullscreen / locate / full view) ─────────────────
let _searchMarker = null;

function fitToData() {
  const bounds = L.latLngBounds([]);
  let any = false;

  // CTOs
  try {
    const ctos = ctoLayer.getLayers ? ctoLayer.getLayers() : [];
    for (const lyr of ctos) {
      if (lyr && lyr.getLatLng) {
        bounds.extend(lyr.getLatLng());
        any = true;
      }
    }
  } catch (e) {}

  // ONTs visibles (cluster)
  try {
    if (ontCluster && ontCluster.getLayers && ontCluster.getLayers().length) {
      const b = ontCluster.getBounds();
      if (b && b.isValid && b.isValid()) {
        bounds.extend(b);
        any = true;
      }
    }
  } catch (e) {}

  if (any && bounds.isValid()) {
    map.fitBounds(bounds.pad(0.15));
  } else {
    // fallback: vista España (tu default actual)
    // fallback: encuadrar CTOs si existen; si no, España
    const b = getCTOBounds();
    if (b) {
      map.fitBounds(b.pad(0.15));
    } else {
      map.setView([40.4168, -3.7038], 6);
    }

  }
}

function addLeafletPlugins() {
  // Escala métrica
  L.control.scale({ imperial: false }).addTo(map);

  // Fullscreen
  if (L.Control && L.Control.Fullscreen) {
    map.addControl(new L.Control.Fullscreen({ position: 'topleft' }));
  }

  // Geocoder (Nominatim)
  if (L.Control && L.Control.Geocoder) {
    const geocoder = L.Control.geocoder({
      position: 'topleft',
      defaultMarkGeocode: false,
      geocoder: L.Control.Geocoder.nominatim(),
      placeholder: 'Buscar dirección…'
    }).addTo(map);

    geocoder.on('markgeocode', (e) => {
      const g = e.geocode;
      if (!g) return;

      // encuadra el bbox si existe; si no, centra
      if (g.bbox) {
        map.fitBounds(g.bbox, { padding: [20, 20] });
      } else if (g.center) {
        map.setView(g.center, Math.max(map.getZoom(), 16));
      }

      // marcador temporal de resultado
      if (_searchMarker) map.removeLayer(_searchMarker);
      const center = g.center || (g.bbox ? g.bbox.getCenter() : null);
      if (center) {
        _searchMarker = L.marker(center);
        _searchMarker.addTo(map).bindPopup(g.name || 'Resultado').openPopup();
      }
    });
  }

  // Locate (Mi ubicación)
  // Nota: en HTTP o en algunos navegadores, geolocalización puede estar bloqueada; en HTTPS suele ir bien.
  if (L.control && L.control.locate) {
    L.control.locate({
      position: 'topleft',
      flyTo: true,
      keepCurrentZoomLevel: false,
      strings: { title: 'Mi ubicación' },
      locateOptions: { enableHighAccuracy: true }
    }).addTo(map);
  }

  // Full view / encuadrar datos
// Botón encuadrar CTOs
if (L.easyButton) {


  // Botón encuadrar ONTs (visibles)
  L.easyButton({
    position: 'topleft',
    states: [{
      stateName: 'fit-onts',
      title: 'Encuadrar CTOs visibles',
      icon: 'ON',
      onClick: () => {
        const b = getONTBounds();
        if (b) map.fitBounds(b.pad(0.15));
        else fitToCTOs(); // fallback útil: si no hay ONTs cargadas, vuelve a CTOs
      }
    }]
  }).addTo(map);
} else {
    // Fallback simple sin easyButton (por si no cargara el plugin)
    const FitControl = L.Control.extend({
      options: { position: 'topleft' },
      onAdd: function () {
        const div = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
        const a = L.DomUtil.create('a', '', div);
        a.href = '#';
        a.title = 'Encuadrar CTOs + ONTs';
        a.innerHTML = '⤢';
        L.DomEvent.disableClickPropagation(div);
        L.DomEvent.on(a, 'click', (e) => {
          L.DomEvent.preventDefault(e);
          fitToData();
        });
        return div;
      }
    });
    map.addControl(new FitControl());
  }
}

// Llamar una sola vez tras inicializar el mapa/capas
addLeafletPlugins();



// ───────────────── Sidebar derecho: collapse/expand ─────────────────
function initRightSidebarCollapse() {
  const right = document.getElementById('sidebar-right');
  const btn = document.getElementById('btn-unlocated-toggle');
  if (!right || !btn) return;

  const KEY = 'ui.sidebarRight.collapsed';

  const apply = (collapsed) => {
    right.classList.toggle('collapsed', collapsed);
    btn.setAttribute('aria-label', collapsed ? 'Expandir panel ONTs sin ubicar' : 'Colapsar panel ONTs sin ubicar');
    btn.setAttribute('title', collapsed ? 'Expandir' : 'Colapsar');
  };

  // Estado inicial desde localStorage
  const saved = localStorage.getItem(KEY);
  if (saved === '1') apply(true);

  btn.addEventListener('click', () => {
    const collapsed = !right.classList.contains('collapsed');
    apply(collapsed);
    localStorage.setItem(KEY, collapsed ? '1' : '0');
  });
}

// Ejecuta cuando el DOM está listo (en módulos suele estarlo, pero lo hacemos seguro)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initRightSidebarCollapse);
} else {
  initRightSidebarCollapse();
}
