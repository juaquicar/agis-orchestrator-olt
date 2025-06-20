// js/app.js
import { API } from './api.js';

let selectedOntId = null;

// 1. Inicializar el mapa centrado en España
const map = L.map('map').setView([40.4168, -3.7038], 6);

// 2. Capa base OpenStreetMap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// 3. MarkerClusterGroup para ONTs ubicados
const cluster = L.markerClusterGroup();
map.addLayer(cluster);

// Referencia al <ul> de ONTs sin ubicación
const unlocatedList = document.getElementById('unlocated-list');

// 4. Función para cargar ONTs ubicados (en el mapa) y no ubicados (en la lista)
async function loadData() {
  try {
    // 4.1. BBOX del viewport actual
    const b = map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(',');

    // 4.2. Cargar y dibujar ONTs ubicados
    const geoResp = await API.get('/geo', { bbox });
    cluster.clearLayers();
    const locatedIds = [];

    geoResp.features.forEach(feature => {
      const [lng, lat] = feature.geometry.coordinates;
      const { ont_id, vendor_ont_id } = feature.properties;
      locatedIds.push(ont_id);

      // marcador arrastrable
      const marker = L.marker([lat, lng], { draggable: true });
      marker.on('dragend', async (e) => {
        const { lat, lng } = e.target.getLatLng();
        try {
          await API.patch(`/onts/${ont_id}`, { lat, lon: lng });
          loadData();
        } catch {
          alert('Error al actualizar ubicación');
        }
      });

      // popup con vendor_ont_id + botón asignar CTO
      marker.bindPopup(`
        <b>ONT: ${vendor_ont_id}</b><br/>
        <button onclick="assignCto(${ont_id})">Asignar/Quitar CTO</button>
      `);

      cluster.addLayer(marker);
    });

    // 4.3. Cargar listado completo y filtrar los no ubicados
    const listResp = await API.get('/onts');
    const unlocated = listResp.items.filter(item => !locatedIds.includes(item.id));

    // 4.4. Pintar la lista en el sidebar
    unlocatedList.innerHTML = '';
    unlocated.forEach(item => {
      const li = document.createElement('li');
      li.textContent = item.vendor_ont_id;
      li.dataset.id = item.id;
      if (item.id == selectedOntId) li.classList.add('selected');
      li.addEventListener('click', () => {
        selectedOntId = item.id;
        unlocatedList.querySelectorAll('li').forEach(el => el.classList.remove('selected'));
        li.classList.add('selected');
      });
      unlocatedList.appendChild(li);
    });

  } catch (err) {
    console.error(err);
    alert('No se pudieron cargar los ONTs.');
  }
}

// 5. Click en el mapa para ubicar la ONT seleccionada
map.on('click', async (e) => {
  if (!selectedOntId) return;
  const { lat, lng } = e.latlng;
  try {
    await API.patch(`/onts/${selectedOntId}`, { lat, lon: lng });
    selectedOntId = null;
    loadData();
  } catch {
    alert('Error al ubicar ONT');
  }
});

// 6. Función global para asignar o quitar CTO
window.assignCto = async function(ontId) {
  const cto = prompt('UUID del CTO (vacío para quitar):');
  if (cto === null) return;
  try {
    await API.patch(`/onts/${ontId}`, { cto_uuid: cto || null });
    loadData();
  } catch {
    alert('Error al actualizar CTO');
  }
};

// 7. Recargar al mover o hacer zoom, y carga inicial
map.on('moveend', loadData);
loadData();
