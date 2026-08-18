/**
 * 航空通 - 地图渲染与交互逻辑
 * 基于 Leaflet 实现 NOTAM 区域 + 火箭发射计划可视化
 */

// ============================================================
// 全局状态
// ============================================================
let map = null;
let notamLayer = null;
let launchLayer = null;
let allFeatures = [];
let allLaunches = [];
let activeTypes = new Set();
let showLaunches = true;
let lastUpdate = null;
let autoRefreshTimer = null;

// NOTAM 类型配置
const TYPE_CONFIG = {
    danger:     { color: '#FF1744', name: '临时危险区',    desc: '火箭发射、导弹试射等临时危险区域' },
    restricted: { color: '#FF6D00', name: '限制区',        desc: '军事活动限制区域' },
    warning:    { color: '#FFD600', name: '警告区',        desc: '潜在飞行危险警告区域' },
    prohibited: { color: '#AA00FF', name: '禁航区',        desc: '完全禁止飞行的区域' },
    tfr:        { color: '#2962FF', name: '临时飞行限制', desc: '临时飞行限制(TFR)' },
    airway:     { color: '#00C853', name: '航路变更',      desc: '航路调整或导航设施变更' },
    other:      { color: '#546E7A', name: '其他通告',      desc: '其他类型航空通告' },
};

// ISO 3166-1 三字母 -> 两字母 国家代码映射 (用于国旗图片)
const CC3_TO_CC2 = {
    'USA': 'us', 'CHN': 'cn', 'RUS': 'ru', 'JPN': 'jp', 'IND': 'in',
    'GUF': 'fr', 'NZL': 'nz', 'KAZ': 'kz', 'KOR': 'kr', 'GBR': 'gb',
    'NOR': 'no', 'SWE': 'se', 'BRA': 'br', 'OMN': 'om', 'AUS': 'au',
    'IRN': 'ir', 'ISR': 'il', 'FRA': 'fr', 'DEU': 'de', 'ITA': 'it',
    'CAN': 'ca', 'ESP': 'es', 'UKR': 'ua', 'IDN': 'id', 'MEX': 'mx',
    'ZAF': 'za', 'TUR': 'tr', 'KWT': 'kw', 'SAU': 'sa', 'ARE': 'ae',
    'PRK': 'kp', 'VNM': 'vn', 'THA': 'th', 'MYS': 'my', 'PHL': 'ph',
    'PAK': 'pk', 'BGD': 'bd', 'LKA': 'lk', 'EGY': 'eg', 'DZK': 'dz',
    'ARG': 'ar', 'CHL': 'cl', 'PER': 'pe', 'COL': 'co',
};

/**
 * 获取国旗图片 HTML
 * @param {string} cc - 三字母国家代码 (如 CHN, USA)
 * @param {number} size - 图片宽度(像素)
 * @returns {string} img 标签 HTML
 */
function getFlag(cc, size = 20) {
    if (!cc || cc === '???') {
        return `<img src="static/flags/unknown.png" alt="未知" style="width:${size}px;height:${size * 0.67}px;border-radius:2px;vertical-align:middle" onerror="this.style.display='none'">`;
    }
    const cc2 = CC3_TO_CC2[cc];
    if (!cc2) {
        return `<span style="font-size:${size * 0.7}px;opacity:0.6">🏳️</span>`;
    }
    return `<img src="static/flags/${cc2}.png" alt="${cc}" style="width:${size}px;height:${size * 0.67}px;border-radius:2px;vertical-align:middle;object-fit:cover" onerror="this.style.display='none'">`;
}

// ============================================================
// 初始化
// ============================================================
function init() {
    initMap();
    loadData();
    autoRefreshTimer = setInterval(loadData, 5 * 60 * 1000);
}

// 折叠/展开侧边栏区块
function toggleSection(sectionId) {
    const section = document.getElementById(sectionId);
    if (section) {
        section.classList.toggle('collapsed');
        // 触发地图重绘，防止空白
        if (map) setTimeout(() => map.invalidateSize(), 300);
    }
}

function initMap() {
    map = L.map('map', {
        center: [30, 115],
        zoom: 4,
        minZoom: 2,
        maxZoom: 12,
        zoomControl: true,
        attributionControl: true,
        worldCopyJump: true,
    });

    L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', {
        attribution: '&copy; 高德地图 | 航空通',
        subdomains: ['1', '2', '3', '4'],
        maxZoom: 18,
    }).addTo(map);

    notamLayer = L.layerGroup().addTo(map);
    launchLayer = L.layerGroup().addTo(map);
}

// ============================================================
// 数据加载
// ============================================================
async function loadData() {
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn) refreshBtn.disabled = true;

    try {
        // 并行加载 NOTAM 和发射数据
        const [notamResp, launchResp] = await Promise.all([
            fetch('data/notams.json?t=' + Date.now()),
            fetch('data/launches.json?t=' + Date.now()),
        ]);

        // NOTAM 数据
        if (notamResp.ok) {
            const geojson = await notamResp.json();
            allFeatures = geojson.features || [];
            const meta = geojson.metadata || {};
            lastUpdate = meta.updated_at;
        }

        // 发射数据
        if (launchResp.ok) {
            const launchJson = await launchResp.json();
            allLaunches = launchJson.features || [];
        }

        renderLegend();
        renderNotamList();
        renderLaunchList();
        renderMapFeatures();
        renderLaunchMarkers();
        updateStatusBar();

    } catch (err) {
        console.error('数据加载失败:', err);
        showStatus('error', '数据加载失败');
    } finally {
        if (refreshBtn) refreshBtn.disabled = false;
    }
}

// ============================================================
// NOTAM 地图渲染
// ============================================================
function renderMapFeatures() {
    notamLayer.clearLayers();

    allFeatures.forEach((feature) => {
        const props = feature.properties || {};
        const notamType = props.type || 'other';
        const config = TYPE_CONFIG[notamType] || TYPE_CONFIG.other;

        if (activeTypes.size > 0 && !activeTypes.has(notamType)) return;

        const geometry = feature.geometry;
        if (!geometry) return;

        if (geometry.type === 'Polygon') {
            const rings = geometry.coordinates.map(ring =>
                ring.map(coord => [coord[1], coord[0]])
            );

            // 底层发光多边形 (halo)
            const glow = L.polygon(rings, {
                color: config.color,
                weight: 8,
                opacity: 0.12,
                fillColor: config.color,
                fillOpacity: 0.05,
                smoothFactor: 1,
                dashArray: '',
                lineJoin: 'round',
                lineCap: 'round',
            });
            glow.addTo(notamLayer);

            // 主多边形 — 渐变填充 + 精致边框
            const isDanger = notamType === 'danger' || notamType === 'prohibited';
            const polygon = L.polygon(rings, {
                color: config.color,
                weight: 2.5,
                opacity: 0.95,
                fillColor: config.color,
                fillOpacity: 0.22,
                smoothFactor: 1,
                dashArray: isDanger ? '8 4' : '',
                lineJoin: 'round',
                lineCap: 'round',
            });

            polygon.bindPopup(() => buildPopupContent(props, config), {
                maxWidth: 420,
                className: 'notam-popup',
            });

            polygon.on('click', () => {
                highlightNotamInList(props.notam_code);
            });

            // 鼠标悬停时增强发光
            polygon.on('mouseover', function() {
                glow.setStyle({ opacity: 0.25, fillOpacity: 0.12 });
                this.setStyle({ weight: 3.5, fillOpacity: 0.35 });
            });
            polygon.on('mouseout', function() {
                glow.setStyle({ opacity: 0.12, fillOpacity: 0.05 });
                this.setStyle({ weight: 2.5, fillOpacity: 0.22 });
            });

            polygon.addTo(notamLayer);
        }
    });
}

function buildPopupContent(props, config) {
    const isSample = props.is_sample ? '<span style="color:#FFA000;font-size:10px;"> (示例数据)</span>' : '';
    const rawShort = (props.raw_message || '').substring(0, 200);

    return `
        <div class="popup-content">
            <div class="popup-header">
                <span class="popup-badge" style="background:${config.color}">${config.name}</span>
                <span class="popup-code">${props.notam_code || 'N/A'}${isSample}</span>
            </div>
            <div class="popup-info">
                <div class="info-row"><span class="info-label">情报区</span><span class="info-value">${props.fir || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">高度</span><span class="info-value">${props.altitude || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">开始</span><span class="info-value">${props.start || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">结束</span><span class="info-value">${props.end || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">来源</span><span class="info-value">${props.source || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">状态</span><span class="info-value" style="color:${props.is_active ? '#00e676' : '#ff5252'}">${props.is_active ? '● 生效中' : '● 已失效'}</span></div>
            </div>
            <div class="popup-raw">${rawShort}${(props.raw_message || '').length > 200 ? '...' : ''}</div>
        </div>
    `;
}

// ============================================================
// 发射标记渲染
// ============================================================
function renderLaunchMarkers() {
    launchLayer.clearLayers();

    if (!showLaunches) return;

    allLaunches.forEach((feature) => {
        const props = feature.properties || {};
        const geometry = feature.geometry;
        if (!geometry || geometry.type !== 'Point') return;

        const lon = geometry.coordinates[0];
        const lat = geometry.coordinates[1];

        // 根据状态选择颜色
        const isGo = props.status && props.status.toLowerCase().includes('go');
        const isTBD = props.status && (props.status.toLowerCase().includes('tbd') || props.status.toLowerCase().includes('deter'));
        const isSuccess = props.status && props.status.toLowerCase().includes('success');
        const isScrub = props.status && props.status.toLowerCase().includes('scrub');

        let color = '#FFD600'; // 默认黄色
        if (isGo) color = '#00E676';      // 绿色 - 确认发射
        else if (isTBD) color = '#FFAB00'; // 橙黄 - 时间待定
        else if (isSuccess) color = '#2979FF'; // 蓝色 - 已成功
        else if (isScrub) color = '#FF1744';   // 红色 - 已取消

        // 创建精致图钉标记
        const flag = getFlag(props.country_code, 22);
        const icon = L.divIcon({
            className: 'launch-marker',
            html: `<div class="launch-pin" style="--pin-color:${color}">
                <div class="launch-pin-ring"></div>
                <div class="launch-pin-body">
                    <div class="launch-pin-flag">${flag}</div>
                </div>
                <div class="launch-pin-tip"></div>
                <div class="launch-pin-shadow"></div>
            </div>`,
            iconSize: [40, 52],
            iconAnchor: [20, 52],
            popupAnchor: [0, -48],
        });

        const marker = L.marker([lat, lon], { icon: icon });

        marker.bindPopup(() => buildLaunchPopup(props, color), {
            maxWidth: 400,
            className: 'launch-popup',
        });

        marker.on('click', () => {
            highlightLaunchInList(props.slug || props.name);
        });

        marker.addTo(launchLayer);
    });
}

function buildLaunchPopup(props, color) {
    const flag = getFlag(props.country_code);
    const liveBadge = props.webcast_live ? '<span class="popup-badge" style="background:#ff1744;margin-left:4px;">🔴 直播中</span>' : '';
    const desc = props.mission_desc ? `<div class="popup-raw">${props.mission_desc}</div>` : '';

    return `
        <div class="popup-content">
            <div class="popup-header">
                <span class="popup-badge" style="background:${color}">${props.status_cn || props.status || '未知'}</span>
                ${liveBadge}
            </div>
            <div class="popup-code" style="margin-bottom:6px;">🚀 ${props.name || 'N/A'}</div>
            <div class="popup-info">
                <div class="info-row"><span class="info-label">代号</span><span class="info-value" style="font-weight:700;color:#fff">${props.rocket_cn || props.rocket || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">任务名</span><span class="info-value">${props.mission_name || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">任务类型</span><span class="info-value">${props.mission_type || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">轨道</span><span class="info-value">${props.orbit || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">发射时间</span><span class="info-value" style="color:#00e676;font-weight:700">${props.net_display || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">倒计时</span><span class="info-value" style="color:${props.is_upcoming ? '#FFD600' : '#546E7A'};font-weight:700">${props.countdown || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">服务商</span><span class="info-value">${props.provider || 'N/A'} (${props.provider_type || ''})</span></div>
                <div class="info-row"><span class="info-label">发射场</span><span class="info-value">${flag} ${props.location_cn || props.location_name || 'N/A'}</span></div>
                <div class="info-row"><span class="info-label">发射台</span><span class="info-value">${props.pad_name || 'N/A'}</span></div>
            </div>
            ${desc}
        </div>
    `;
}

// ============================================================
// 图例渲染
// ============================================================
function renderLegend() {
    const container = document.getElementById('legend');
    if (!container) return;

    const typeCounts = {};
    allFeatures.forEach(f => {
        const t = (f.properties || {}).type || 'other';
        typeCounts[t] = (typeCounts[t] || 0) + 1;
    });

    // 发射统计
    const launchCount = allLaunches.length;
    const goCount = allLaunches.filter(f => {
        const s = (f.properties || {}).status || '';
        return s.toLowerCase().includes('go');
    }).length;

    let html = '';

    // NOTAM 类型
    Object.entries(TYPE_CONFIG).forEach(([key, config]) => {
        const count = typeCounts[key] || 0;
        if (count === 0 && key !== 'other') return;

        const opacity = (activeTypes.size > 0 && !activeTypes.has(key)) ? '0.4' : '1';
        html += `
            <div class="legend-item" data-type="${key}" style="opacity:${opacity}" onclick="toggleType('${key}')">
                <div class="legend-color" style="background:${config.color}"></div>
                <div class="legend-text">
                    <div class="legend-name">${config.name}</div>
                    <div class="legend-desc">${config.desc}</div>
                </div>
                <div class="legend-count">${count}</div>
            </div>
        `;
    });

    // 分隔线
    html += '<div style="height:1px;background:var(--border);margin:8px 0;"></div>';

    // 发射计划
    const launchOpacity = showLaunches ? '1' : '0.4';
    html += `
        <div class="legend-item" id="legend-launches" style="opacity:${launchOpacity}" onclick="toggleLaunches()">
            <div class="legend-color" style="background:linear-gradient(135deg,#00E676,#FFD600)">🚀</div>
            <div class="legend-text">
                <div class="legend-name">火箭/卫星发射</div>
                <div class="legend-desc">即将发射的运载火箭任务</div>
            </div>
            <div class="legend-count">${launchCount}</div>
        </div>
        <div style="font-size:10px;color:var(--text-muted);padding:2px 0 0 34px;">
            🟢确认发射 ${goCount} ｜ 🟡时间待定 ${launchCount - goCount}
        </div>
    `;

    container.innerHTML = html;
}

function toggleType(typeKey) {
    if (activeTypes.has(typeKey)) {
        activeTypes.delete(typeKey);
    } else {
        activeTypes.add(typeKey);
    }

    const allTypes = Object.keys(TYPE_CONFIG);
    if (activeTypes.size === allTypes.length) {
        activeTypes.clear();
    }

    renderLegend();
    renderNotamList();
    renderMapFeatures();
}

function toggleLaunches() {
    showLaunches = !showLaunches;
    renderLegend();
    renderLaunchList();
    renderLaunchMarkers();
}

// ============================================================
// NOTAM 列表
// ============================================================
function renderNotamList() {
    const container = document.getElementById('notam-list');
    if (!container) return;

    let features = allFeatures;

    if (activeTypes.size > 0) {
        features = features.filter(f =>
            activeTypes.has((f.properties || {}).type)
        );
    }

    if (features.length === 0) {
        container.innerHTML = '<div class="notam-empty">暂无 NOTAM 数据</div>';
        return;
    }

    let html = '';
    features.forEach(feature => {
        const props = feature.properties || {};
        const notamType = props.type || 'other';
        const config = TYPE_CONFIG[notamType] || TYPE_CONFIG.other;

        html += `
            <div class="notam-card" style="border-left-color:${config.color}" data-code="${props.notam_code || ''}">
                <div class="notam-code">${props.notam_code || 'N/A'}</div>
                <div class="notam-type">${config.name}</div>
                <div class="notam-time">${props.start || ''} ~ ${props.end || ''}</div>
                <span class="notam-fir">${props.fir || ''}</span>
            </div>
        `;
    });

    container.innerHTML = html;

    // 绑定点击事件
    container.querySelectorAll('.notam-card').forEach((card, idx) => {
        card.addEventListener('click', () => {
            const feature = features[idx];
            const geometry = feature.geometry;
            if (geometry && geometry.type === 'Polygon') {
                const coords = geometry.coordinates[0];
                const latlngs = coords.map(c => [c[1], c[0]]);
                const bounds = L.latLngBounds(latlngs);
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        });
    });
}

function highlightNotamInList(code) {
    document.querySelectorAll('.notam-card').forEach(card => {
        card.classList.toggle('active', card.dataset.code === code);
    });
    const card = document.querySelector(`.notam-card[data-code="${code}"]`);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ============================================================
// 发射列表
// ============================================================
function renderLaunchList() {
    const container = document.getElementById('launch-list');
    if (!container) return;

    if (!showLaunches) {
        container.innerHTML = '<div class="notam-empty">已隐藏发射计划</div>';
        return;
    }

    if (allLaunches.length === 0) {
        container.innerHTML = '<div class="notam-empty">暂无发射计划</div>';
        return;
    }

    // 按发射时间排序(最近的在前)
    const sorted = [...allLaunches].sort((a, b) => {
        const ta = (a.properties || {}).net || '';
        const tb = (b.properties || {}).net || '';
        return ta.localeCompare(tb);
    });

    let html = '';
    sorted.forEach(feature => {
        const props = feature.properties || {};
        const flag = getFlag(props.country_code);
        const isGo = (props.status || '').toLowerCase().includes('go');
        const color = isGo ? '#00E676' : '#FFAB00';

        html += `
            <div class="launch-card" data-slug="${props.slug || props.name}" style="border-left-color:${color}">
                <div class="launch-name">${flag} ${props.rocket_cn || props.rocket || 'N/A'}</div>
                <div class="launch-mission">📡 ${props.mission_name || 'N/A'}</div>
                <div class="launch-time" style="color:${isGo ? '#00e676' : '#FFAB00'};font-weight:700">
                    ⏰ ${props.net_display || 'N/A'}
                </div>
                <div class="launch-countdown">${props.countdown || ''}</div>
                <span class="notam-fir">${props.location_cn || props.location_name || ''}</span>
            </div>
        `;
    });

    container.innerHTML = html;

    // 绑定点击事件
    container.querySelectorAll('.launch-card').forEach((card, idx) => {
        card.addEventListener('click', () => {
            const feature = sorted[idx];
            const geometry = feature.geometry;
            if (geometry && geometry.type === 'Point') {
                const [lon, lat] = geometry.coordinates;
                map.setView([lat, lon], 6, { animate: true });
            }
        });
    });
}

function highlightLaunchInList(slug) {
    document.querySelectorAll('.launch-card').forEach(card => {
        card.classList.toggle('active', card.dataset.slug === slug);
    });
    const card = document.querySelector(`.launch-card[data-slug="${slug}"]`);
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ============================================================
// 状态栏
// ============================================================
function updateStatusBar() {
    const totalEl = document.getElementById('stat-total');
    const activeEl = document.getElementById('stat-active');
    const updateEl = document.getElementById('stat-update');
    const sourceEl = document.getElementById('stat-source');
    const launchEl = document.getElementById('stat-launches');

    if (totalEl) totalEl.textContent = allFeatures.length;

    const activeCount = allFeatures.filter(f => (f.properties || {}).is_active).length;
    if (activeEl) activeEl.textContent = activeCount;

    if (launchEl) launchEl.textContent = allLaunches.length;

    if (updateEl && lastUpdate) {
        const dt = new Date(lastUpdate);
        updateEl.textContent = dt.toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
        });
    }

    if (sourceEl) {
        sourceEl.textContent = allLaunches.length > 0 ? 'LaunchLib+FAA' : 'N/A';
    }
}

function showStatus(type, message) {
    const dot = document.querySelector('.status-dot');
    if (dot) {
        dot.classList.toggle('offline', type === 'error');
    }
}

async function manualRefresh() {
    const btn = document.getElementById('btn-refresh');
    if (btn) {
        btn.disabled = true;
        btn.textContent = '刷新中...';
    }

    try {
        // 调用后端 API 触发实时数据抓取
        const resp = await fetch('/api/refresh', { method: 'GET' });
        const data = await resp.json();

        if (resp.status === 409) {
            // 已有刷新在进行中
            console.log('刷新进行中，等待...');
        } else if (data.ok) {
            console.log('数据刷新已启动');

            // 轮询等待刷新完成
            await pollRefreshStatus();
        }
    } catch (e) {
        // 后端 API 不可用 (如 GitHub Pages 静态部署)
        console.log('后端API不可用，仅重新加载本地数据');
    }

    // 重新加载前端数据
    await loadData();

    if (btn) {
        btn.disabled = false;
        btn.textContent = '刷新数据';
    }
}

async function pollRefreshStatus() {
    const maxWait = 60; // 最多等待 60 秒
    for (let i = 0; i < maxWait; i++) {
        await new Promise(r => setTimeout(r, 1000));

        try {
            const resp = await fetch('/api/status?t=' + Date.now());
            const data = await resp.json();

            if (!data.running) {
                // 刷新完成
                if (data.last_result && data.last_result.includes('成功')) {
                    console.log('数据刷新成功:', data.last_result);
                } else if (data.last_error) {
                    console.warn('数据刷新异常:', data.last_error);
                }
                return;
            }
        } catch (e) {
            // API 不可用，直接返回
            return;
        }
    }
    console.log('刷新等待超时');
}

document.addEventListener('DOMContentLoaded', init);
