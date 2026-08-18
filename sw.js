/**
 * 航空通 - Service Worker (PWA 离线支持)
 */
const CACHE_NAME = 'aviation-tong-v19';
const CACHE_URLS = [
  './',
  './index.html',
  './manifest.json',
  './static/css/style.css?v=19',
  './static/css/premium.css?v=19',
  './static/leaflet/leaflet.css?v=19',
  './static/leaflet/leaflet.js?v=19',
  './static/js/lib/satellite.min.js',
  './static/js/map.js?v=19',
  './static/js/satellites.js?v=19',
  './static/js/flights.js?v=19',
  './static/js/export_data.js?v=19',
  './static/js/favorites.js?v=19',
  './static/js/notifications.js?v=19',
  './static/js/airport_info.js?v=19',
  './static/js/premium/subscription.js?v=19',
  './static/js/premium/flight_plan.js?v=19',
  './static/js/premium/satellite_pass.js?v=19',
  './static/js/premium/route_planner.js?v=19',
  './static/js/premium/notam_impact.js?v=19',
  './static/js/premium/api_dashboard.js?v=19',
];

// 安装 — 预缓存核心资源
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(CACHE_URLS).catch(err => {
        console.warn('部分资源预缓存失败:', err);
      });
    })
  );
  self.skipWaiting();
});

// 激活 — 清理旧缓存
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.filter(name => name !== CACHE_NAME)
          .map(name => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// 拦截请求 — 缓存优先，网络回退
self.addEventListener('fetch', (event) => {
  // 跳过非 GET 请求
  if (event.request.method !== 'GET') return;

  // 跳过 API 请求和地图瓦片
  const url = new URL(event.request.url);
  if (url.hostname.includes('opensky-network.org') ||
      url.hostname.includes('celestrak.org') ||
      url.hostname.includes('basemaps.cartocdn.com') ||
      url.pathname.includes('/api/')) {
    return; // 这些请求不走缓存
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      // 缓存优先，同时后台更新
      const fetchPromise = fetch(event.request).then(response => {
        if (response && response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      }).catch(() => {
        // 离线时返回缓存
        return cached;
      });
      return cached || fetchPromise;
    })
  );
});

// 接收消息 — 支持手动更新
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
