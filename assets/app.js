const filters = { name: '', type: '', references: '' };
const markers = new Map();
let markerLabelMode = false;
let restaurants = [];
let selectedRestaurantId = null;
let map = null;
let mapsLibraries = null;
let locationMarker = null;
let locationPosition = null;
let GoogleMapClass = null;
let mapConfiguration = null;

const typeColor = {
  'Restaurant': '#dc2626', 'Bars': '#7c3aed', 'Coffee Shops': '#92400e',
  'Dessert': '#db2777', 'Fast Food': '#ea580c', 'Hidden / Speakeasy': '#111827'
};
const typeIcon = {
  'Restaurant': 'restaurant', 'Bars': 'bar', 'Coffee Shops': 'cafe',
  'Dessert': 'ice-cream', 'Fast Food': 'fast-food', 'Hidden / Speakeasy': 'danger'
};
const referenceLabels = {
  'instagram.com': 'Instagram', 'tiktok.com': 'TikTok',
  'guide.michelin.com': 'Michelin', 'jamesbeard.org': 'James Beard',
  'ny.itsfound.com': 'Itsfound', 'atlasobscura.com': 'Atlas Obscura',
  'theinfatuation.com': 'Infatuation'
};

const themeMediaQuery = window.matchMedia?.('(prefers-color-scheme: dark)');

function savedTheme() {
  try {
    const value = localStorage.getItem('restfinder-theme');
    return value === 'light' || value === 'dark' ? value : null;
  } catch (_) {
    return null;
  }
}

function currentTheme() {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

function updateThemeControl(theme) {
  const button = document.getElementById('theme-toggle');
  if (!button) return;
  const nextTheme = theme === 'dark' ? 'light' : 'dark';
  button.setAttribute('aria-label', `Switch to ${nextTheme} mode`);
  button.title = `Switch to ${nextTheme} mode`;
  button.querySelector('i').className = `fa-solid ${theme === 'dark' ? 'fa-sun' : 'fa-moon'}`;
}

function createGoogleMap(center, zoom) {
  if (!GoogleMapClass || !mapConfiguration || !mapsLibraries) return;
  markers.forEach(marker => { marker.map = null; });
  markers.clear();
  if (locationMarker) locationMarker.map = null;

  const mapElement = document.getElementById('map');
  mapElement.replaceChildren();
  map = new GoogleMapClass(mapElement, {
    center,
    zoom,
    mapId: mapConfiguration.google_map_id || 'DEMO_MAP_ID',
    colorScheme: currentTheme() === 'light' ? mapsLibraries.ColorScheme.LIGHT : mapsLibraries.ColorScheme.DARK,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: false
  });
  map.addListener('idle', renderAll);
  if (locationPosition) {
    locationMarker = new mapsLibraries.AdvancedMarkerElement({
      map, position: locationPosition, title: 'Your current location'
    });
  } else {
    locationMarker = null;
  }
  renderAll();
}

function applyTheme(theme, remember = false) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]').content = theme === 'light' ? '#ffffff' : '#111827';
  updateThemeControl(theme);
  if (remember) {
    try { localStorage.setItem('restfinder-theme', theme); } catch (_) {}
  }
  if (map) {
    const center = map.getCenter()?.toJSON();
    const zoom = map.getZoom();
    if (center && zoom != null) createGoogleMap(center, zoom);
  }
}

function configureTheme() {
  updateThemeControl(currentTheme());
  document.getElementById('theme-toggle').addEventListener('click', () => {
    applyTheme(currentTheme() === 'dark' ? 'light' : 'dark', true);
  });
  themeMediaQuery?.addEventListener('change', event => {
    if (!savedTheme()) applyTheme(event.matches ? 'dark' : 'light');
  });
}

function escapeHtml(value) {
  return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
  })[character]);
}

function referenceLabel(value) {
  try {
    const url = new URL(value);
    if (['http:', 'https:'].includes(url.protocol)) {
      const hostname = url.hostname.replace(/^www\./, '').replace(/^archive\./, '').replace(/^web\./, '');
      return referenceLabels[hostname] || hostname;
    }
  } catch (_) {}
  return value;
}

function referenceHtml(item) {
  const value = item.reference || '';
  try {
    const url = new URL(value);
    if (['http:', 'https:'].includes(url.protocol)) {
      return `<a class="reference" href="${escapeHtml(url.href)}" target="_blank" rel="noopener">${escapeHtml(referenceLabel(value))}</a>`;
    }
  } catch (_) {}
  return `<span class="reference">${escapeHtml(value)}</span>`;
}

function referencesHtml(items) {
  return (items || []).map(referenceHtml).join(', ');
}

function googleMapsUrl(restaurant) {
  const location = restaurant.address || `${restaurant.lat},${restaurant.lon}`;
  const query = encodeURIComponent(`${restaurant.name} ${location}`);
  const place = restaurant.google_place_id ? `&query_place_id=${encodeURIComponent(restaurant.google_place_id)}` : '';
  return `https://www.google.com/maps/search/?api=1&query=${query}${place}`;
}

function googleMapsFallbackHtml(restaurant) {
  return `<a class="google-maps-fallback" href="${googleMapsUrl(restaurant)}" target="_blank" rel="noopener">Open in Maps</a>`;
}

function referenceSearchText(restaurant) {
  return (restaurant.references || []).map(item => {
    const value = item.reference || '';
    return `${referenceLabel(value)} ${value}`;
  }).join(' ').toLowerCase();
}

function filteredRestaurants() {
  return restaurants.filter(restaurant => {
    const inBounds = !map || !map.getBounds() || map.getBounds().contains({ lat: restaurant.lat, lng: restaurant.lon });
    return inBounds
      && (!filters.name || (restaurant.name || '').toLowerCase().includes(filters.name))
      && (!filters.type || (restaurant.type || 'unclassified').toLowerCase().includes(filters.type))
      && (!filters.references || referenceSearchText(restaurant).includes(filters.references));
  });
}

function markerContent(restaurant, withLabel) {
  const root = document.createElement('div');
  root.className = 'map-pin-marker';
  const color = typeColor[restaurant.type] || typeColor.Restaurant;
  const icon = typeIcon[restaurant.type] || typeIcon.Restaurant;
  root.innerHTML = `${withLabel ? `<span class="pin-label">${escapeHtml(restaurant.name)}</span>` : ''}<span class="map-pin" style="--pin-color:${color}" aria-hidden="true"><img src="assets/maki/${icon}.svg" alt=""></span>`;
  return root;
}

function sourceSuffix(restaurant, field) {
  return restaurant.detail_sources?.[field] === 'overture'
    ? ' <span class="source-label">via Overture</span>' : '';
}

function metadataRow(icon, value) {
  return `<div class="metadata-row"><span class="metadata-icon" aria-hidden="true"><i class="fa-solid ${icon}"></i></span><span class="metadata-value">${value}</span></div>`;
}

function closeDetails() {
  document.getElementById('details').hidden = true;
  selectedRestaurantId = null;
  document.querySelectorAll('tbody tr').forEach(row => row.classList.remove('selected'));
}

async function renderGoogleDetails(host, restaurant) {
  if (!restaurant.google_place_id || !mapsLibraries) {
    host.innerHTML = googleMapsFallbackHtml(restaurant);
    return;
  }
  try {
    await Promise.race([
      customElements.whenDefined('gmp-place-details'),
      new Promise((_, reject) => setTimeout(() => reject(new Error('Places UI Kit did not load')), 5000))
    ]);
    host.innerHTML = `
      <gmp-place-details>
        <gmp-place-details-place-request place="${escapeHtml(restaurant.google_place_id)}"></gmp-place-details-place-request>
        <gmp-place-content-config>
          <gmp-place-address></gmp-place-address><gmp-place-type></gmp-place-type>
          <gmp-place-price></gmp-place-price><gmp-place-open-now-status></gmp-place-open-now-status>
          <gmp-place-opening-hours></gmp-place-opening-hours><gmp-place-website></gmp-place-website>
          <gmp-place-phone-number></gmp-place-phone-number><gmp-place-attribution></gmp-place-attribution>
        </gmp-place-content-config>
      </gmp-place-details>`;
  } catch (error) {
    console.error('Could not render Google place details', error);
    host.innerHTML = googleMapsFallbackHtml(restaurant);
  }
}

function showDetails(restaurant) {
  selectedRestaurantId = restaurant.id;
  document.querySelectorAll('tbody tr').forEach(row => row.classList.toggle('selected', row.dataset.id === restaurant.id));
  const details = document.getElementById('details');
  const mentionMetadata = restaurant.references.length
    ? metadataRow('fa-bookmark', referencesHtml(restaurant.references)) : '';
  const metadata = restaurant.google_place_id ? mentionMetadata : [
    metadataRow('fa-utensils', escapeHtml(restaurant.type || 'Unclassified')),
    restaurant.cuisine ? metadataRow('fa-bowl-food', `${escapeHtml(restaurant.cuisine)}${sourceSuffix(restaurant, 'cuisine')}`) : '',
    restaurant.place_category ? metadataRow('fa-tag', escapeHtml(restaurant.place_category)) : '',
    metadataRow('fa-location-dot', `${escapeHtml(restaurant.address || `${restaurant.lat}, ${restaurant.lon}`)}${sourceSuffix(restaurant, 'address')}`),
    restaurant.phone ? metadataRow('fa-phone', `<a href="tel:${escapeHtml(restaurant.phone)}">${escapeHtml(restaurant.phone)}</a>${sourceSuffix(restaurant, 'phone')}`) : '',
    restaurant.website ? metadataRow('fa-globe', `<a href="${escapeHtml(restaurant.website)}" target="_blank" rel="noopener">Website</a>${sourceSuffix(restaurant, 'website')}`) : '',
    restaurant.operating_status ? metadataRow('fa-circle-info', `${escapeHtml(restaurant.operating_status.replaceAll('_', ' '))}${sourceSuffix(restaurant, 'operating_status')}`) : '',
    mentionMetadata
  ].join('');
  details.innerHTML = `
    <div class="details-header">
      <div class="details-title"><h2>${escapeHtml(restaurant.name)}</h2></div>
      <a class="icon-button" href="${googleMapsUrl(restaurant)}" target="_blank" rel="noopener" aria-label="Open in Google Maps" title="Open in Google Maps"><i class="fa-solid fa-arrow-up-right-from-square"></i></a>
      <button class="icon-button" type="button" data-close-details aria-label="Close details"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="details-body"><div class="detail-grid">${metadata}</div><div class="google-details" data-google-details></div></div>`;
  details.hidden = false;
  details.querySelector('[data-close-details]').addEventListener('click', closeDetails);
  renderGoogleDetails(details.querySelector('[data-google-details]'), restaurant);
}

function selectRestaurant(id) {
  const restaurant = restaurants.find(item => item.id === id);
  if (!restaurant) return;
  showDetails(restaurant);
}

function filterInput(key) {
  return `<div class="filter"><input data-filter="${key}" value="${escapeHtml(filters[key])}" placeholder="Filter…" aria-label="Filter ${key}"></div>`;
}

function renderTable() {
  const visible = filteredRestaurants();
  const wrap = document.getElementById('table-wrap');
  if (!restaurants.length) {
    wrap.innerHTML = '<div class="empty">No referenced restaurants have been published yet.</div>';
    return;
  }
  let html = `<table><thead><tr><th>#<span id="status" class="status">${restaurants.length} places</span></th><th>Name${filterInput('name')}</th><th>Type${filterInput('type')}</th><th>Mentions${filterInput('references')}</th></tr></thead><tbody>`;
  visible.forEach((restaurant, index) => {
    html += `<tr class="${restaurant.id === selectedRestaurantId ? 'selected' : ''}" data-id="${escapeHtml(restaurant.id)}"><td>${index + 1}</td><td title="${escapeHtml(restaurant.name)}"><span class="restaurant-name">${escapeHtml(restaurant.name)}</span><a class="map-link" href="${googleMapsUrl(restaurant)}" target="_blank" rel="noopener" aria-label="Open ${escapeHtml(restaurant.name)} in Google Maps"><i class="fa-solid fa-arrow-up-right-from-square"></i></a></td><td>${escapeHtml(restaurant.type || 'Unclassified')}</td><td>${referencesHtml(restaurant.references)}</td></tr>`;
  });
  wrap.innerHTML = `${html}</tbody></table>`;
  wrap.querySelectorAll('input[data-filter]').forEach(input => input.addEventListener('input', event => {
    filters[event.target.dataset.filter] = event.target.value.trim().toLowerCase();
    renderAll();
    const replacement = document.querySelector(`input[data-filter="${event.target.dataset.filter}"]`);
    replacement?.focus(); replacement?.setSelectionRange(replacement.value.length, replacement.value.length);
  }));
  wrap.querySelectorAll('tbody tr').forEach(row => row.addEventListener('click', event => {
    if (!event.target.closest('a')) selectRestaurant(row.dataset.id);
  }));
}

function renderMarkers() {
  if (!map || !mapsLibraries) return;
  const visible = filteredRestaurants();
  const showLabels = visible.length < 50;
  if (showLabels !== markerLabelMode) {
    markers.forEach(marker => { marker.map = null; });
    markers.clear();
    markerLabelMode = showLabels;
  }
  const visibleIds = new Set(visible.map(restaurant => restaurant.id));
  markers.forEach((marker, id) => {
    if (!visibleIds.has(id)) { marker.map = null; markers.delete(id); }
  });
  visible.forEach(restaurant => {
    if (markers.has(restaurant.id)) return;
    const marker = new mapsLibraries.AdvancedMarkerElement({
      map,
      position: { lat: restaurant.lat, lng: restaurant.lon },
      content: markerContent(restaurant, showLabels),
      title: `${restaurant.type || 'Unclassified'}: ${restaurant.name}`
    });
    marker.addListener('click', () => showDetails(restaurant));
    markers.set(restaurant.id, marker);
  });
}

function renderAll() {
  renderMarkers();
  renderTable();
}

function finishLocationRequest() {
  const button = document.getElementById('locate-me');
  button.disabled = false;
  button.querySelector('i').className = 'fa-solid fa-location-crosshairs';
}

function configureLocation() {
  const button = document.getElementById('locate-me');
  const status = document.getElementById('address-search-status');
  button.addEventListener('click', () => {
    if (!navigator.geolocation || !map) {
      status.textContent = map ? 'Location services are unavailable.' : 'The map is unavailable.';
      return;
    }
    button.disabled = true;
    button.querySelector('i').className = 'fa-solid fa-spinner fa-spin';
    navigator.geolocation.getCurrentPosition(position => {
      const { latitude, longitude } = position.coords;
      if (locationMarker) locationMarker.map = null;
      locationPosition = { lat: latitude, lng: longitude };
      locationMarker = new mapsLibraries.AdvancedMarkerElement({
        map, position: locationPosition, title: 'Your current location'
      });
      map.panTo({ lat: latitude, lng: longitude });
      map.setZoom(18);
      status.textContent = 'Map centered on your current location.';
      finishLocationRequest();
    }, error => {
      status.textContent = ({
        1: 'Location permission was denied.',
        2: 'Your current location is unavailable.',
        3: 'Finding your location timed out.'
      })[error.code] || 'Could not determine your current location.';
      finishLocationRequest();
    }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
  });
}

function loadGoogleMaps(apiKey) {
  return new Promise((resolve, reject) => {
    window.restfinderGoogleMapsLoaded = resolve;
    const script = document.createElement('script');
    const parameters = new URLSearchParams({
      key: apiKey, loading: 'async', callback: 'restfinderGoogleMapsLoaded', v: 'weekly'
    });
    script.src = `https://maps.googleapis.com/maps/api/js?${parameters}`;
    script.async = true;
    script.onerror = () => reject(new Error('Google Maps failed to load'));
    document.head.append(script);
  });
}

async function initializeMap(config, city) {
  const mapElement = document.getElementById('map');
  if (!config.google_maps_browser_key) {
    mapElement.innerHTML = '<div class="map-message">Map unavailable: GOOGLE_MAPS_BROWSER_KEY is not configured. The restaurant list remains available below.</div>';
    document.querySelector('.search-placeholder').textContent = 'Address search unavailable';
    return;
  }
  await loadGoogleMaps(config.google_maps_browser_key);
  const [{ Map: GoogleMap }, { AdvancedMarkerElement }, { PlaceAutocompleteElement }, { ColorScheme }] = await Promise.all([
    google.maps.importLibrary('maps'),
    google.maps.importLibrary('marker'),
    google.maps.importLibrary('places'),
    google.maps.importLibrary('core')
  ]);
  GoogleMapClass = GoogleMap;
  mapConfiguration = config;
  mapsLibraries = { AdvancedMarkerElement, PlaceAutocompleteElement, ColorScheme };
  createGoogleMap({ lat: city.lat, lng: city.lng }, city.zoom);

  const autocomplete = new PlaceAutocompleteElement();
  autocomplete.includedRegionCodes = ['us'];
  autocomplete.locationRestriction = {
    west: -74.50, south: 40.40, east: -73.20, north: 41.20
  };
  autocomplete.placeholder = 'Search an NYC metro address…';
  autocomplete.addEventListener('gmp-select', async event => {
    const place = event.placePrediction.toPlace();
    await place.fetchFields({ fields: ['displayName', 'formattedAddress', 'location'] });
    if (place.location) {
      map.panTo(place.location);
      map.setZoom(18);
      document.getElementById('address-search-status').textContent = `Map centered on ${place.formattedAddress || place.displayName}.`;
    }
  });
  document.getElementById('autocomplete-host').replaceChildren(autocomplete);
  renderAll();
}

async function start() {
  configureTheme();
  configureLocation();
  try {
    const json = response => response.ok ? response.json() : Promise.reject(new Error(`Could not load ${response.url}`));
    const [cities, data, build, config] = await Promise.all([
      fetch('cities.json').then(json),
      fetch('data/nyc.json').then(json),
      fetch('build.json', { cache: 'no-store' }).then(json),
      fetch('config.json', { cache: 'no-store' }).then(json)
    ]);
    restaurants = data;
    const latest = restaurants.reduce((value, item) => value > item.last_seen ? value : item.last_seen, '');
    const updated = latest ? new Date(latest).toLocaleDateString('en-GB', {
      day: '2-digit', month: 'short', year: '2-digit', timeZone: 'UTC'
    }).replace(/ /g, '-') : '';
    document.getElementById('version').innerHTML = updated
      ? `Updated <a href="${escapeHtml(build.url)}" target="_blank" rel="noopener">${updated}</a>`
      : '';
    renderTable();
    await initializeMap(config, cities.find(item => item.key === 'nyc'));
  } catch (error) {
    console.error(error);
    document.getElementById('version').textContent = 'Unable to load map';
    if (!restaurants.length) {
      document.getElementById('table-wrap').innerHTML = '<div class="empty">Restaurant data could not be loaded.</div>';
    }
    document.getElementById('map').innerHTML = '<div class="map-message">The map is temporarily unavailable. The restaurant list remains available.</div>';
  }
}

if ('serviceWorker' in navigator) {
  window.addEventListener('load', async () => {
    const localDevelopment = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    if (localDevelopment) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map(registration => registration.unregister()));
      if ('caches' in window) {
        await Promise.all((await caches.keys()).map(key => caches.delete(key)));
      }
      return;
    }
    navigator.serviceWorker.register('service-worker.js').catch(error => {
      console.error('Service worker registration failed', error);
    });
  });
}

start();
