// js/app.js – Flujo de ubicación, asignación y desasignación de CTO para ONTs
// ----------------------------------------------------------------------------
import { API } from './api.js';
import { getCTOGeoJSON } from './api.js';

let selectedOntId = null;
let mode = null; // 'locate' o 'assign'
let ctoDict = {};

// 1. Inicializar mapa -------------------------------------------------------
const map = L.map('map').setView([40.4168, -3.7038], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 22,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// 2. Capas ------------------------------------------------------------------
const ontCluster = L.markerClusterGroup().addTo(map);
const ctoLayer   = L.layerGroup().addTo(map);
const linkLayer  = L.layerGroup().addTo(map);

// 3. Sidebar ----------------------------------------------------------------
const unlocatedList = document.getElementById('unlocated-list');

// ─────────────────────────── CTOs ─────────────────────────────────────────
async function loadCtos() {
  ctoLayer.clearLayers();
  ctoDict = {};

  const geo = await getCTOGeoJSON();
  L.geoJSON(geo, {
    pointToLayer: (f, latlng) =>
      L.circleMarker(latlng, { radius: 6, fillOpacity: 0.5 }),
    onEachFeature: (f, layer) => {
      const { nombre, uuid } = f.properties;
      ctoDict[uuid] = { nombre, latlng: layer.getLatLng() };
      layer.bindPopup(`<b>CTO:</b> ${nombre}`);
      layer.on('click', () => handleCtoClick(uuid));
    }
  }).addTo(ctoLayer);
}

async function handleCtoClick(uuid) {
  if (!selectedOntId || mode !== 'assign') return;
  try {
    await API.patch(`/onts/${selectedOntId}`, { cto_uuid: uuid });
  } catch (err) {
    console.error('PATCH cto_uuid falló', err);
    alert('Error asignando CTO');
  }
  resetSelection();
  await reloadAll();
}

async function unassignCto(ontId) {
  try {
    await API.patch(`/onts/${ontId}`, { cto_uuid: null });
  } catch (err) {
    console.error('PATCH desasociar CTO falló', err);
    alert('Error desasociando CTO');
  }
  await reloadAll();
}

window.unassignCto = unassignCto;

function resetSelection() {
  selectedOntId = null;
  mode = null;
  unlocatedList.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
}

// ─────────────────────────── ONTs ─────────────────────────────────────────
async function loadOnts() {
  const b = map.getBounds();
  const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(',');

  // (1) GeoJSON de ONTs visibles
  const geoResp = await API.get('/geo', { bbox });
  // (2) Lista completa de ONTs
  const allResp = await API.get('/onts', { limit: 1000 });
  const byId = Object.fromEntries(allResp.items.map(o => [o.id, o]));

  ontCluster.clearLayers();
  linkLayer.clearLayers();

  // Marcadores y líneas
  geoResp.features.forEach(f => {
    const [lng, lat] = f.geometry.coordinates;
    const { ont_id } = f.properties;
    const detail = byId[ont_id] || {};
    const cto_uuid = detail.cto_uuid;

    const marker = L.marker([lat, lng], { draggable: true });
    marker.on('dragend', async e => {
      const { lat: newLat, lng: newLon } = e.target.getLatLng();
      try {
        await API.patch(`/onts/${ont_id}`, { lat: newLat, lon: newLon });
      } catch (err) {
        console.error(err);
        alert('Error al mover ONT');
      }
      await reloadAll();
    });

    // Popup con info y botones de asignar/desasignar CTO
    let html = `<b>ONT:</b> ${detail.vendor_ont_id}`;
    if (cto_uuid && ctoDict[cto_uuid]) {
      html += `<br/><b>CTO:</b> ${ctoDict[cto_uuid].nombre}`;
      html += `<br/><button onclick="unassignCto('${ont_id}')">Desasociar CTO</button>`;
    } else {
      html += `<br/><button onclick="assignCto('${ont_id}')">Asignar CTO</button>`;
    }
    marker.bindPopup(html);
    ontCluster.addLayer(marker);

    // Línea de unión si está asociada
    if (cto_uuid && ctoDict[cto_uuid]) {
      linkLayer.addLayer(L.polyline([
        [lat, lng],
        ctoDict[cto_uuid].latlng
      ], { weight: 1, dashArray: '4,2' }));
    }
  });

  // Lista lateral: ONTs que no aparecen en /geo
  const locatedIds = new Set(geoResp.features.map(f => f.properties.ont_id));
  const unlocated = allResp.items.filter(o => !locatedIds.has(o.id));
  renderUnlocatedList(unlocated);
}

function renderUnlocatedList(list) {
  unlocatedList.innerHTML = '';
  list.forEach(o => {
    const li = document.createElement('li');
    li.textContent = o.vendor_ont_id;
    li.dataset.id = o.id;
    li.addEventListener('click', () => {
      resetSelection();
      selectedOntId = o.id;
      mode = 'locate';
      li.classList.add('selected');
      alert('ONT seleccionada. Haz click en el mapa para ubicarla.');
    });
    unlocatedList.appendChild(li);
  });
}

// Botón global para asignar CTO
window.assignCto = ontId => {
  resetSelection();
  selectedOntId = ontId;
  mode = 'assign';
  alert('Ahora pulsa sobre un marcador CTO para asociarla.');
};

// Click en mapa: ubicación de ONT
map.on('click', async e => {
  if (!selectedOntId || mode !== 'locate') return;
  const { lat, lng } = e.latlng;
  try {
    await API.patch(`/onts/${selectedOntId}`, { lat, lon: lng });
  } catch (err) {
    console.error(err);
    alert('Error ubicando ONT');
  }
  resetSelection();
  await reloadAll();
});

// Recarga al mover o hacer zoom
map.on('moveend', loadOnts);

// Inicialización
async function reloadAll() {
  await loadCtos();
  await loadOnts();
}
reloadAll();