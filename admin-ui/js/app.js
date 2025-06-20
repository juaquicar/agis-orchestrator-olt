// js/app.js
import { API } from './api.js';

// 1. Inicializar el mapa centrado en España
const map = L.map('map').setView([40.4168, -3.7038], 6);

// 2. Capa base de OpenStreetMap
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// 3. Crear MarkerClusterGroup para agrupar ONTs
const cluster = L.markerClusterGroup();
map.addLayer(cluster);

// 4. Función para cargar y dibujar las ONTs
async function loadONTs() {
  try {
    const data = await API.get('/onts');
    console.log('Respuesta /api/onts:', data);
    cluster.clearLayers();

    // Mapear data.items a GeoJSON
    const features = data.items.map(f => ({
      type: 'Feature',
      geometry: f.geom || { type: 'Point', coordinates: [0, 0] },
      properties: {
        ont_id: f.id,
        vendor_ont_id: f.vendor_ont_id,
        cto_uuid: f.cto_uuid
      }
    }));

    const geojson = {
      type: 'FeatureCollection',
      features
    };

    L.geoJSON(geojson, {
      pointToLayer: (_, latlng) => L.marker(latlng),
      onEachFeature: (feature, layer) => {
        const { ont_id, cto_uuid } = feature.properties;
        const ctoText = cto_uuid ? `CTO: ${cto_uuid}` : 'CTO sin asignar';
        layer.bindPopup(`
          <b>ONT ${ont_id}</b><br/>
          ${ctoText}<br/>
          <button onclick="assignCto('${ont_id}')">
            Asignar/Quitar CTO
          </button>
        `);
      }
    }).addTo(cluster);

  } catch (err) {
    console.error('Error cargando ONTs:', err);
    alert('No se pudieron cargar las ONTs. Revisa la consola.');
  }
}

// 5. Añadir controles de Leaflet.Draw
const drawControl = new L.Control.Draw({
  draw: {
    marker: true,
    polygon: false,
    polyline: false,
    rectangle: false,
    circle: false
  },
  edit: { featureGroup: cluster }
});
map.addControl(drawControl);

// Manejar creación de nuevos marcadores
map.on(L.Draw.Event.CREATED, async (e) => {
  const { lat, lng } = e.layer.getLatLng();
  const ontId = prompt('Introduce el ID interno de la ONT:');
  if (!ontId) return;

  try {
    await API.patch(`/onts/${ontId}`, { lat, lon: lng });
    alert('Posición guardada');
    loadONTs();
  } catch (err) {
    console.error(err);
    alert('Error al guardar posición');
  }
});

// Manejar movimiento/edición de marcadores
map.on(L.Draw.Event.EDITED, async (e) => {
  for (const layer of Object.values(e.layers._layers)) {
    const { ont_id } = layer.feature.properties;
    const { lat, lng } = layer.getLatLng();
    try {
      await API.patch(`/onts/${ont_id}`, { lat, lon: lng });
    } catch (err) {
      console.error(`Error moviendo ONT ${ont_id}:`, err);
    }
  }
  loadONTs();
});

// 6. Función global para asignar o quitar CTO
window.assignCto = async function(ontId) {
  const cto = prompt('UUID del CTO (vacío para quitar):');
  if (cto === null) return;

  try {
    await API.patch(`/onts/${ontId}`, { cto_uuid: cto || null });
    alert('CTO actualizado');
    loadONTs();
  } catch (err) {
    console.error(err);
    alert('Error al actualizar CTO');
  }
};

// 7. Carga inicial de ONTs al arrancar la página
loadONTs();
