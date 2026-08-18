/**
 * 航空通 - 实时航班追踪模块
 * 基于 OpenSky Network API 获取全球实时航班位置
 */

// ============================================================
// 全局状态
// ============================================================
let flightLayer = null;
let flightMarkers = [];
let flightData = [];
let flightUpdateTimer = null;
let showFlights = false;
let flightSearchQuery = '';

// ============================================================
// 初始化
// ============================================================
function initFlights() {
    // 预加载，不渲染
}

/**
 * 切换航班显示
 */
function toggleFlights(forceOn) {
    if (forceOn === true) {
        showFlights = true;
    } else {
        showFlights = !showFlights;
    }

    const btn = document.getElementById('btn-toggle-flight');
    if (showFlights) {
        if (btn) btn.classList.add('active');
        loadFlightData();
        if (!flightUpdateTimer) {
            flightUpdateTimer = setInterval(loadFlightData, 30000); // 30秒刷新
        }
    } else {
        if (btn) btn.classList.remove('active');
        if (flightLayer) {
            map.removeLayer(flightLayer);
        }
        if (flightUpdateTimer) {
            clearInterval(flightUpdateTimer);
            flightUpdateTimer = null;
        }
    }
}

/**
 * 加载航班数据 — OpenSky Network API
 */
async function loadFlightData() {
    try {
        // 获取当前视口范围
        const bounds = map.getBounds();
        const lamin = Math.max(-90, bounds.getSouth() - 5);
        const lamax = Math.min(90, bounds.getNorth() + 5);
        const lomin = Math.max(-180, bounds.getWest() - 5);
        const lomax = Math.min(180, bounds.getEast() + 5);

        const url = `https://opensky-network.org/api/states/all?lamin=${lamin}&lamax=${lamax}&lomin=${lomin}&lomax=${lomax}`;

        const resp = await fetch(url);
        if (!resp.ok) throw new Error('航班API请求失败');
        const data = await resp.json();

        if (data.states) {
            flightData = data.states.map(s => ({
                icao24: s[0],
                callsign: (s[1] || '').trim(),
                origin: s[2],
                longitude: s[5],
                latitude: s[6],
                altitude: s[7],        // 米
                velocity: s[9],         // m/s
                heading: s[10],         // 度
                onGround: s[8],
                verticalRate: s[11],
            })).filter(f => f.longitude !== null && f.latitude !== null);

            renderFlights();
            updateFlightList();

            const stat = document.getElementById('stat-flights');
            if (stat) stat.textContent = flightData.length;
        }
    } catch (err) {
        console.error('航班数据加载失败:', err);
        showStatus('error', '航班数据加载失败（OpenSky API 限流）');
    }
}

/**
 * 渲染航班到地图
 */
function renderFlights() {
    if (flightLayer) {
        map.removeLayer(flightLayer);
    }
    flightLayer = L.layerGroup();
    flightMarkers = [];

    let count = 0;
    for (const flight of flightData) {
        if (flight.onGround) continue; // 跳过地面飞机

        const isFiltered = flightSearchQuery &&
            !flight.callsign.toLowerCase().includes(flightSearchQuery.toLowerCase()) &&
            !flight.icao24.toLowerCase().includes(flightSearchQuery.toLowerCase());
        if (isFiltered) continue;

        const color = flight.altitude > 10000 ? '#00E5FF' : '#FFAB00';
        const icon = L.divIcon({
            className: 'flight-marker',
            html: `<div class="flight-marker-icon" style="transform: rotate(${flight.heading || 0}deg);">
                       <svg width="16" height="16" viewBox="0 0 24 24" fill="${color}">
                           <path d="M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z"/>
                       </svg>
                   </div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });

        const marker = L.marker([flight.latitude, flight.longitude], { icon })
            .bindPopup(() => formatFlightPopup(flight));

        flightMarkers.push({ flight, marker });
        flightLayer.addLayer(marker);
        count++;
    }

    if (showFlights) {
        flightLayer.addTo(map);
    }
    console.log(`已渲染 ${count} 架航班`);
}

/**
 * 格式化航班弹窗
 */
function formatFlightPopup(flight) {
    const altKm = flight.altitude ? (flight.altitude / 1000).toFixed(1) : 'N/A';
    const speedKmh = flight.velocity ? (flight.velocity * 3.6).toFixed(0) : 'N/A';
    const callsign = flight.callsign || flight.icao24.toUpperCase();

    return `
        <div class="flight-popup">
            <div class="flight-popup-header">✈️ ${escapeHtml(callsign)}</div>
            <div class="flight-popup-body">
                <div class="flight-info-row"><span>ICAO24</span><span>${escapeHtml(flight.icao24)}</span></div>
                <div class="flight-info-row"><span>归属</span><span>${escapeHtml(flight.origin || 'N/A')}</span></div>
                <div class="flight-info-row"><span>高度</span><span>${altKm} km (${flight.altitude ? flight.altitude.toFixed(0) + ' m' : 'N/A'})</span></div>
                <div class="flight-info-row"><span>速度</span><span>${speedKmh} km/h</span></div>
                <div class="flight-info-row"><span>航向</span><span>${flight.heading ? flight.heading.toFixed(0) + '°' : 'N/A'}</span></div>
                <div class="flight-info-row"><span>经纬</span><span>${flight.longitude.toFixed(3)}, ${flight.latitude.toFixed(3)}</span></div>
                <div class="flight-info-row"><span>状态</span><span style="color:${flight.onGround ? '#FFAB00' : '#00e676'}">${flight.onGround ? '地面' : '飞行中'}</span></div>
            </div>
        </div>
    `;
}

/**
 * 更新航班列表
 */
function updateFlightList() {
    const listEl = document.getElementById('flight-list');
    if (!listEl) return;

    if (flightData.length === 0) {
        listEl.innerHTML = '<div class="notam-empty">暂无航班数据</div>';
        return;
    }

    const filtered = flightSearchQuery
        ? flightData.filter(f =>
            f.callsign.toLowerCase().includes(flightSearchQuery.toLowerCase()) ||
            f.icao24.toLowerCase().includes(flightSearchQuery.toLowerCase()))
        : flightData;

    const sorted = [...filtered].sort((a, b) =>
        (b.altitude || 0) - (a.altitude || 0));

    const fragment = document.createDocumentFragment();
    for (const flight of sorted.slice(0, 100)) {
        const callsign = flight.callsign || flight.icao24.toUpperCase();
        const color = flight.altitude > 10000 ? '#00E5FF' : '#FFAB00';

        const card = document.createElement('div');
        card.className = 'flight-card';
        card.style.borderLeftColor = color;
        card.innerHTML = `
            <div class="flight-name">✈️ ${escapeHtml(callsign)}</div>
            <div class="flight-info">📏 ${(flight.altitude / 1000).toFixed(1)}km | 🚀 ${(flight.velocity * 3.6).toFixed(0)}km/h | 🧭 ${flight.heading.toFixed(0)}°</div>
            <span class="notam-fir">${escapeHtml(flight.origin || 'Unknown')}</span>
        `;

        card.addEventListener('click', () => {
            map.setView([flight.latitude, flight.longitude], 8, { animate: true });
        });

        fragment.appendChild(card);
    }

    listEl.innerHTML = '';
    listEl.appendChild(fragment);
}

/**
 * 搜索航班（自包含防抖）
 */
let _flightSearchTimer = null;
function searchFlights() {
    if (_flightSearchTimer) clearTimeout(_flightSearchTimer);
    _flightSearchTimer = setTimeout(() => {
        const input = document.getElementById('flight-search-input');
        if (input) flightSearchQuery = input.value.trim();
        renderFlights();
        updateFlightList();
    }, 250);
}
