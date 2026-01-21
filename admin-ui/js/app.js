import {
  API,
  getCTOGeoJSON,
  getOltList,
  getPonList,
  getOntGeo,
  getUnlocatedOnts,
  getUnlocatedGroups,
  searchOnts
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

let ontMarkerById = new Map(); // ontId -> Leaflet marker


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

    div.innerHTML = `
      ${escapeHtml(o.vendor_ont_id)}
      ${badge}
      <div class="tree-meta" style="margin-top:2px;">
        OLT ${escapeHtml(o.olt_name)} · PON ${escapeHtml(o.pon_id)}
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

// ───────────────── Estado ─────────────────
const PAGE_SIZE = 200;

let selectedOntId = null;
let mode = null; // 'locate' o 'assign'

let ctoDict = {};

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

  const geo = await getCTOGeoJSON();
  L.geoJSON(geo, {
    pointToLayer: (f, latlng) => L.marker(latlng, { icon: ctoIcon }),
    onEachFeature: (f, layer) => {
      const { nombre, uuid } = f.properties;
      ctoDict[uuid] = { nombre, latlng: layer.getLatLng() };
      layer.bindPopup(`<b>CTO:</b> ${escapeHtml(nombre)}`);
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
      div.innerHTML = `${escapeHtml(o.vendor_ont_id)} <span class="tree-meta">[${escapeHtml(oltId)}]</span>`;

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

// ───────────────── Bootstrap ─────────────────
(async function bootstrap() {
  showLoading('Inicializando…');
  try {
    await loadCtos();
    await initMapFilters();

    // Buscador ONTs
    await initOntSearch();

    // Árbol ONTs sin ubicar
    await loadUnlocatedTree();

    setStatus('Mapa: selecciona OLT + PON para cargar ONTs');
  } catch (err) {
    console.error(err);
    alert('Error inicializando la UI');
    setStatus('Error inicializando la UI');
  } finally {
    hideLoading();
  }
})();

