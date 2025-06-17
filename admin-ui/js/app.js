
const API = new ApiClient('/api', 'DEV-TOKEN'); // << cambia por JWT real
const map = L.map('map').setView([40.4,-3.7],11);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OSM'}).addTo(map);
const cluster = L.markerClusterGroup().addTo(map);

function refresh(){
  const bbox = map.getBounds().toBBoxString();
  API.get('/geo?bbox='+bbox).then(data=>{
    cluster.clearLayers();
    L.geoJSON(data.features,{
      onEachFeature:(f,l)=>{ l.bindPopup('ONT '+f.properties.id); }
    }).addTo(cluster);
  });
}
map.on('moveend', refresh);
refresh();
