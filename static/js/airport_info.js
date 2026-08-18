/**
 * 航空通 - 机场信息查询模块
 * 输入 ICAO/IATA 代码查看机场基本信息
 */

// ============================================================
// 机场数据库（常用机场）
// ============================================================
const AIRPORT_DB = {
    // 中国
    'ZBAA': { name: '北京首都国际机场', city: '北京', country: 'CHN', iata: 'PEK', lat: 40.0801, lng: 116.5840, runways: ['01/19', '18L/36R'] },
    'ZBAD': { name: '北京大兴国际机场', city: '北京', country: 'CHN', iata: 'PKX', lat: 39.5098, lng: 116.4141, runways: ['01/19', '17L/35R'] },
    'ZSSS': { name: '上海虹桥国际机场', city: '上海', country: 'CHN', iata: 'SHA', lat: 31.1979, lng: 121.3360, runways: ['18L/36R', '18R/36L'] },
    'ZSPD': { name: '上海浦东国际机场', city: '上海', country: 'CHN', iata: 'PVG', lat: 31.1443, lng: 121.8083, runways: ['16L/34R', '16R/34L', '17L/35R', '17R/35L'] },
    'ZGGG': { name: '广州白云国际机场', city: '广州', country: 'CHN', iata: 'CAN', lat: 23.3924, lng: 113.2988, runways: ['02L/20R', '02R/20L'] },
    'ZGSZ': { name: '深圳宝安国际机场', city: '深圳', country: 'CHN', iata: 'SZX', lat: 22.6394, lng: 113.8108, runways: ['16/34'] },
    'ZUCK': { name: '成都天府国际机场', city: '成都', country: 'CHN', iata: 'TFU', lat: 30.3120, lng: 104.4415, runways: ['01/19', '02/20'] },
    'ZUUU': { name: '成都双流国际机场', city: '成都', country: 'CHN', iata: 'CTU', lat: 30.5785, lng: 103.9471, runways: ['02L/20R', '02R/20L'] },
    'ZSWY': { name: '温州龙湾国际机场', city: '温州', country: 'CHN', iata: 'WNZ', lat: 27.9126, lng: 120.8523, runways: ['03/21'] },
    'ZSAM': { name: '厦门高崎国际机场', city: '厦门', country: 'CHN', iata: 'XMN', lat: 24.5440, lng: 118.1272, runways: ['05/23'] },
    // 美国
    'KATL': { name: 'Hartsfield-Jackson Atlanta', city: 'Atlanta', country: 'USA', iata: 'ATL', lat: 33.6407, lng: -84.4277, runways: ['08L/26R', '08R/26L', '09/27', '10/28'] },
    'KLAX': { name: 'Los Angeles International', city: 'Los Angeles', country: 'USA', iata: 'LAX', lat: 33.9416, lng: -118.4085, runways: ['06L/24R', '06R/24L', '07/25'] },
    'KJFK': { name: 'John F Kennedy International', city: 'New York', country: 'USA', iata: 'JFK', lat: 40.6413, lng: -73.7781, runways: ['04L/22R', '04R/22L', '13L/31R', '13R/31L'] },
    'KSFO': { name: 'San Francisco International', city: 'San Francisco', country: 'USA', iata: 'SFO', lat: 37.6213, lng: -122.3790, runways: ['01L/19R', '01R/19L', '10L/28R', '10R/28L'] },
    'KORD': { name: 'O\'Hare International', city: 'Chicago', country: 'USA', iata: 'ORD', lat: 41.9742, lng: -87.9073, runways: ['04L/22R', '04R/22L', '09L/27R', '09R/27L', '10L/28R', '10C/28C'] },
    // 欧洲
    'EGLL': { name: 'London Heathrow', city: 'London', country: 'GBR', iata: 'LHR', lat: 51.4700, lng: -0.4543, runways: ['09L/27R', '09R/27L'] },
    'EHAM': { name: 'Amsterdam Schiphol', city: 'Amsterdam', country: 'NLD', iata: 'AMS', lat: 52.3105, lng: 4.7683, runways: ['06/24', '09/27', '18L/36R', '18C/36C'] },
    'LFPG': { name: 'Paris Charles de Gaulle', city: 'Paris', country: 'FRA', iata: 'CDG', lat: 49.0097, lng: 2.5479, runways: ['08L/26R', '08R/26L', '09/27', '10/28'] },
    'EDDF': { name: 'Frankfurt am Main', city: 'Frankfurt', country: 'DEU', iata: 'FRA', lat: 50.0379, lng: 8.5622, runways: ['07L/25R', '07R/25L', '07C/25C', '18'] },
    'LEMD': { name: 'Madrid Barajas', city: 'Madrid', country: 'ESP', iata: 'MAD', lat: 40.4983, lng: -3.5676, runways: ['14L/32R', '14R/32L', '18L/36R', '18R/36L'] },
    // 亚太
    'RJTT': { name: 'Tokyo Haneda', city: 'Tokyo', country: 'JPN', iata: 'HND', lat: 35.5494, lng: 139.7798, runways: ['04/22', '16L/34R', '16R/34L', '05/23'] },
    'RJAA': { name: 'Tokyo Narita', city: 'Tokyo', country: 'JPN', iata: 'NRT', lat: 35.7647, lng: 140.3863, runways: ['16L/34R', '16R/34L'] },
    'WSSS': { name: 'Singapore Changi', city: 'Singapore', country: 'SGP', iata: 'SIN', lat: 1.3644, lng: 103.9915, runways: ['02L/20R', '02C/20C', '02R/20L'] },
    'VTBS': { name: 'Bangkok Suvarnabhumi', city: 'Bangkok', country: 'THA', iata: 'BKK', lat: 13.6900, lng: 100.7501, runways: ['01L/19R', '01R/19L'] },
    'YSSY': { name: 'Sydney Kingsford Smith', city: 'Sydney', country: 'AUS', iata: 'SYD', lat: -33.9399, lng: 151.1753, runways: ['07/25', '16L/34R', '16R/34L'] },
    // 中东
    'OMDB': { name: 'Dubai International', city: 'Dubai', country: 'ARE', iata: 'DXB', lat: 25.2532, lng: 55.3657, runways: ['12L/30R', '12R/30L'] },
    'OTHH': { name: 'Doha Hamad International', city: 'Doha', country: 'QAT', iata: 'DOH', lat: 25.2731, lng: 51.6080, runways: ['16/34'] },
};

// IATA -> ICAO 映射
const IATA_TO_ICAO = {};
for (const icao in AIRPORT_DB) {
    IATA_TO_ICAO[AIRPORT_DB[icao].iata] = icao;
}

/**
 * 搜索机场
 */
function searchAirport() {
    const input = document.getElementById('airport-search-input');
    if (!input) return;
    const query = input.value.trim().toUpperCase();

    if (!query) return;

    // 先按 ICAO 查，再按 IATA 查，再按城市/名称模糊匹配
    let airport = AIRPORT_DB[query] || AIRPORT_DB[IATA_TO_ICAO[query]];

    if (!airport) {
        // 模糊搜索
        const matches = Object.values(AIRPORT_DB).filter(a =>
            a.name.toUpperCase().includes(query) ||
            a.city.toUpperCase().includes(query));
        if (matches.length > 0) {
            airport = matches[0];
            if (matches.length > 1) {
                showAirportSearchResults(matches);
                return;
            }
        }
    }

    if (airport) {
        showAirportInfo(airport);
    } else {
        showStatus('error', `未找到机场: ${query}`);
    }
}

/**
 * 显示机场搜索结果列表
 */
function showAirportSearchResults(matches) {
    const modal = createModal('airport-results-modal', '搜索结果');
    const list = document.createElement('div');
    list.style.cssText = 'display:flex;flex-direction:column;gap:8px;';

    for ( const airport of matches) {
        const item = document.createElement('div');
        item.className = 'notam-card';
        item.style.cssText = 'cursor:pointer;border-left-color:var(--accent);';
        item.innerHTML = `
            <div style="font-weight:700">${escapeHtml(airport.name)}</div>
            <div style="font-size:11px;color:var(--text-muted)">
                ${escapeHtml(airport.iata)} / ${escapeHtml(Object.keys(AIRPORT_DB).find(k => AIRPORT_DB[k] === airport))} · ${escapeHtml(airport.city)}
            </div>
        `;
        item.addEventListener('click', () => {
            showAirportInfo(airport);
            modal.remove();
        });
        list.appendChild(item);
    }
    modal.querySelector('.modal-body').appendChild(list);
}

/**
 * 显示机场信息弹窗
 */
function showAirportInfo(airport) {
    const icao = Object.keys(AIRPORT_DB).find(k => AIRPORT_DB[k] === airport);
    const flag = getFlag(airport.country, 24);

    // 定位地图
    map.setView([airport.lat, airport.lng], 12, { animate: true });

    // 显示弹窗
    const popup = L.popup({
        className: 'airport-popup-container',
        maxWidth: 360,
    })
    .setLatLng([airport.lat, airport.lng])
    .setContent(`
        <div class="airport-popup">
            <div class="airport-popup-header">
                ${flag} ${escapeHtml(airport.name)}
            </div>
            <div class="airport-popup-body">
                <div class="airport-info-row"><span class="airport-label">ICAO</span><span class="airport-value">${escapeHtml(icao)}</span></div>
                <div class="airport-info-row"><span class="airport-label">IATA</span><span class="airport-value">${escapeHtml(airport.iata)}</span></div>
                <div class="airport-info-row"><span class="airport-label">城市</span><span class="airport-value">${escapeHtml(airport.city)}</span></div>
                <div class="airport-info-row"><span class="airport-label">国家</span><span class="airport-value">${escapeHtml(COUNTRY_NAME_CN[airport.country] || airport.country)}</span></div>
                <div class="airport-info-row"><span class="airport-label">坐标</span><span class="airport-value">${airport.lat.toFixed(4)}, ${airport.lng.toFixed(4)}</span></div>
                <div class="airport-info-row"><span class="airport-label">跑道</span><span class="airport-value">${escapeHtml(airport.runways.join(', '))}</span></div>
                <div class="airport-info-row"><span class="airport-label">状态</span><span class="airport-value" style="color:#00e676;">● 运营中</span></div>
            </div>
        </div>
    `)
    .openOn(map);
}

/**
 * 创建模态框工具
 */
function createModal(id, title) {
    const existing = document.getElementById(id);
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = id;
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
        <div class="modal-content">
            <div class="modal-header">
                <span>${escapeHtml(title)}</span>
                <button class="modal-close" onclick="document.getElementById('${id}').remove()">✕</button>
            </div>
            <div class="modal-body"></div>
        </div>
    `;
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.remove();
    });
    document.body.appendChild(overlay);
    return overlay;
}
