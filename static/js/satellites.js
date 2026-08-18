/**
 * 航空通 - 在轨卫星实时追踪模块
 * 基于 CelesTrak TLE 数据 + satellite.js 实时计算位置
 */

// ============================================================
// 全局状态
// ============================================================
let satelliteData = [];      // 卫星TLE数据列表
let satelliteMarkers = [];   // 地图上的卫星标记
let satelliteLayer = null;   // 卫星图层
let satelliteUpdateTimer = null;
let satelliteTrackTimer = null;
let showSatellites = false;  // 默认不显示
let selectedSatellite = null;
let satelliteTrackPolyline = null;  // 轨道轨迹线

// 卫星类别配置 (颜色+图标)
const SAT_CATEGORY_CONFIG = {
    'stations': { color: '#FF1744', icon: '🛰️', name: '空间站', zIndex: 1000 },
    'visual':   { color: '#00E5FF', icon: '⭐', name: '最亮卫星', zIndex: 900 },
    'weather':  { color: '#76FF03', icon: '🌤️', name: '天气卫星', zIndex: 800 },
    'gps':      { color: '#FFAB00', icon: '📡', name: 'GPS导航', zIndex: 700 },
    'beidou':   { color: '#FF6D00', icon: '🧭', name: '北斗导航', zIndex: 700 },
    'starlink': { color: '#AA00FF', icon: '✨', name: '星链', zIndex: 600 },
};

// 知名卫星中文名称映射
const SAT_NAME_CN = {
    'ISS (ZARYA)': '国际空间站 (ISS)',
    'CSS (TIANHE)': '中国空间站天和核心舱',
    'CSS (WENTIAN)': '中国空间站问天实验舱',
    'CSS (MENGTIAN)': '中国空间站梦天实验舱',
    'CSS (TIANZHOU)': '中国空间站天舟货运飞船',
    'POISK': '国际空间站探索号迷你舱',
    'ISS (NAUKA)': '国际空间站科学号实验舱',
    'HST': '哈勃太空望远镜',
    'HUBBLE SPACE TELESCOPE': '哈勃太空望远镜',
    'TERRA': 'Terra地球观测卫星',
    'AQUA': 'Aqua水卫星',
    'AURA': 'Aura大气卫星',
    'NOAA': 'NOAA气象卫星',
    'GOES': 'GOES气象卫星',
    'METOP': 'Metop气象卫星',
    'FENGYUN': '风云气象卫星',
    'BEIDOU': '北斗导航卫星',
    'BEIDOU-3': '北斗三号',
    'COMPASS': '北斗导航卫星',
    'GPS': 'GPS导航卫星',
    'NAVSTAR': 'GPS导航卫星',
    'STARLINK': '星链卫星',
    'IRIDIUM': '铱星',
    'ONEWEB': 'OneWeb卫星',
    'SOYUZ': '联盟号飞船',
    'PROGRESS': '进步号货运飞船',
    'DRAGON': '龙飞船',
    'CYGNUS': '天鹅座货运飞船',
    'SZ-21': '神舟二十一号',
    'SZ-22': '神舟二十二号',
    'SZ-23': '神舟二十三号',
    'SHENZHOU': '神舟飞船',
};

/**
 * 获取卫星中文名称
 */
function getSatelliteNameCN(name) {
    if (!name) return '';
    const upper = name.toUpperCase();
    // 精确匹配
    for (const [en, cn] of Object.entries(SAT_NAME_CN)) {
        if (upper === en || upper.includes(en)) {
            return cn;
        }
    }
    return name;
}

/**
 * 从 TLE 计算卫星当前经纬度
 */
function calcSatellitePosition(tle1, tle2) {
    try {
        if (typeof satellite === 'undefined') {
            console.error('satellite.js 未加载');
            return null;
        }

        // 解析 TLE
        const satrec = satellite.twoline2satrec(tle1, tle2);

        // 当前时间
        const now = new Date();

        // 传播计算位置 (返回 ECI 坐标)
        const positionAndVelocity = satellite.propagate(satrec, now);

        if (!positionAndVelocity.position || typeof positionAndVelocity.position === 'boolean') {
            return null;  // 传播失败
        }

        const positionEci = positionAndVelocity.position;

        // 计算 GMST (格林尼治恒星时)
        const gmst = satellite.gstime(now);

        // ECI -> 经纬度
        const positionGd = satellite.eciToGeodetic(positionEci, gmst);

        // 弧度转角度
        const longitude = satellite.degreesLong(positionGd.longitude);
        const latitude = satellite.degreesLat(positionGd.latitude);
        const altitude = positionGd.height;  // km

        return {
            lat: latitude,
            lng: longitude,
            alt: altitude,
            velocity: positionAndVelocity.velocity,
        };
    } catch (e) {
        return null;
    }
}

/**
 * 预测卫星未来轨道轨迹
 */
function calcSatelliteTrack(tle1, tle2, minutes = 90, stepSeconds = 30) {
    const points = [];
    try {
        if (typeof satellite === 'undefined') return points;

        const satrec = satellite.twoline2satrec(tle1, tle2);
        const now = new Date();

        for (let t = 0; t <= minutes * 60; t += stepSeconds) {
            const time = new Date(now.getTime() + t * 1000);
            const pv = satellite.propagate(satrec, time);

            if (!pv.position || typeof pv.position === 'boolean') continue;

            const gmst = satellite.gstime(time);
            const pgd = satellite.eciToGeodetic(pv.position, gmst);

            const lng = satellite.degreesLong(pgd.longitude);
            const lat = satellite.degreesLat(pgd.latitude);

            // 处理经度跨越（Leaflet 会自动处理，但我们需要确保点连续）
            points.push([lat, lng]);
        }
    } catch (e) {
        console.error('轨道计算失败', e);
    }
    return points;
}

/**
 * 加载卫星TLE数据
 */
async function loadSatelliteData() {
    try {
        const resp = await fetch('data/satellites.json?v=' + Date.now());
        if (!resp.ok) {
            console.warn('卫星数据加载失败');
            return;
        }
        const data = await resp.json();
        satelliteData = data.satellites || [];
        console.log(`卫星数据加载完成: ${satelliteData.length} 颗`);
        updateSatelliteList();
    } catch (e) {
        console.error('卫星数据加载失败:', e);
    }
}

/**
 * 更新卫星列表显示
 */
function updateSatelliteList() {
    const listEl = document.getElementById('satellite-list');
    if (!listEl) return;

    if (satelliteData.length === 0) {
        listEl.innerHTML = '<div class="notam-empty">暂无卫星数据</div>';
        return;
    }

    // 按类别分组
    const byCategory = {};
    for (const sat of satelliteData) {
        const cat = sat.category || 'other';
        if (!byCategory[cat]) byCategory[cat] = [];
        byCategory[cat].push(sat);
    }

    let html = '';
    for (const [cat, sats] of Object.entries(byCategory)) {
        const config = SAT_CATEGORY_CONFIG[cat] || { color: '#546E7A', icon: '🛰️', name: '其他' };
        html += `<div class="sat-category-header" style="color:${config.color};font-weight:600;font-size:13px;padding:6px 0;">
            ${config.icon} ${config.name} (${sats.length})
        </div>`;

        for (const sat of sats.slice(0, 30)) {  // 每类最多显示30个
            const nameCN = getSatelliteNameCN(sat.name);
            html += `<div class="sat-item" onclick="searchAndLocateSatellite('${sat.norad_id}')" 
                         style="padding:4px 8px;cursor:pointer;font-size:12px;border-left:3px solid ${config.color};margin-left:4px;">
                        ${nameCN}
                        <span style="color:var(--text-muted);font-size:10px;">#${sat.norad_id}</span>
                    </div>`;
        }
        if (sats.length > 30) {
            html += `<div style="padding:2px 8px;font-size:11px;color:var(--text-muted);">...还有 ${sats.length - 30} 颗</div>`;
        }
    }

    listEl.innerHTML = html;
}

/**
 * 搜索卫星并定位 (添加防抖优化)
 */
const searchSatelliteDebounced = debounce(function() {
    _doSearchSatellite();
}, 250);

function searchSatellite() {
    searchSatelliteDebounced();
}

function _doSearchSatellite() {
    const input = document.getElementById('satellite-search-input');
    if (!input) return;
    const query = input.value.trim().toLowerCase();

    if (!query) {
        updateSatelliteList();
        return;
    }

    // 搜索匹配的卫星
    const results = satelliteData.filter(sat => {
        const nameCN = getSatelliteNameCN(sat.name).toLowerCase();
        return sat.name.toLowerCase().includes(query) ||
               nameCN.includes(query) ||
               String(sat.norad_id).includes(query);
    });

    const listEl = document.getElementById('satellite-list');
    if (!listEl) return;

    if (results.length === 0) {
        listEl.innerHTML = '<div class="notam-empty">未找到匹配的卫星</div>';
        return;
    }

    let html = `<div style="padding:6px 0;font-size:13px;color:var(--text-muted);">
        找到 ${results.length} 颗卫星
    </div>`;

    for (const sat of results.slice(0, 50)) {
        const config = SAT_CATEGORY_CONFIG[sat.category] || { color: '#546E7A', icon: '🛰️' };
        const nameCN = getSatelliteNameCN(sat.name);
        const safeNoradId = escapeHtml(String(sat.norad_id));
        const safeName = escapeHtml(sat.name);
        const safeNameCN = escapeHtml(nameCN);
        html += `<div class="sat-item" onclick="searchAndLocateSatellite('${safeNoradId}')"
                     style="padding:6px 8px;cursor:pointer;font-size:12px;border-left:3px solid ${config.color};margin:2px 0;background:rgba(255,255,255,0.03);">
                    <div style="font-weight:600;">${safeNameCN}</div>
                    <div style="color:var(--text-muted);font-size:10px;">
                        ${safeName} · ID:${safeNoradId}
                    </div>
                </div>`;
    }

    listEl.innerHTML = html;
}

/**
 * 定位到指定卫星
 */
function searchAndLocateSatellite(noradId) {
    const sat = satelliteData.find(s => s.norad_id === noradId);
    if (!sat) return;

    selectedSatellite = sat;

    // 确保卫星图层开启
    if (!showSatellites) {
        toggleSatellites(true);
    }

    // 计算当前位置
    const pos = calcSatellitePosition(sat.tle1, sat.tle2);
    if (!pos) {
        showToast('无法计算卫星位置');
        return;
    }

    // 飞到卫星位置
    map.flyTo([pos.lat, pos.lng], 5, { duration: 1.5 });

    // 显示轨道轨迹
    showSatelliteTrack(sat);

    // 显示卫星信息弹窗
    setTimeout(() => {
        showSatellitePopup(sat, pos);
    }, 1600);
}

/**
 * 显示卫星轨道轨迹
 */
function showSatelliteTrack(sat) {
    // 清除旧轨迹
    if (satelliteTrackPolyline) {
        map.removeLayer(satelliteTrackPolyline);
    }

    const points = calcSatelliteTrack(sat.tle1, sat.tle2, 90, 30);
    if (points.length === 0) return;

    const config = SAT_CATEGORY_CONFIG[sat.category] || { color: '#00E5FF' };

    // 绘制轨道线
    satelliteTrackPolyline = L.polyline(points, {
        color: config.color,
        weight: 2,
        opacity: 0.5,
        dashArray: '5, 5',
    }).addTo(map);
}

/**
 * 显示卫星信息弹窗
 */
function showSatellitePopup(sat, pos) {
    const nameCN = getSatelliteNameCN(sat.name);
    const config = SAT_CATEGORY_CONFIG[sat.category] || { color: '#546E7A', icon: '🛰️', name: '其他' };
    const velocity = pos.velocity ? Math.sqrt(
        pos.velocity.x * pos.velocity.x +
        pos.velocity.y * pos.velocity.y +
        pos.velocity.z * pos.velocity.z
    ).toFixed(0) : 'N/A';

    const html = `
        <div class="satellite-popup">
            <div class="sat-popup-header" style="background:${config.color};">
                ${config.icon} ${nameCN}
            </div>
            <div class="sat-popup-body">
                <div class="sat-info-row">
                    <span class="sat-label">原名</span>
                    <span class="sat-value">${sat.name}</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">NORAD编号</span>
                    <span class="sat-value">${sat.norad_id}</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">类别</span>
                    <span class="sat-value">${config.name}</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">高度</span>
                    <span class="sat-value">${pos.alt.toFixed(1)} km</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">速度</span>
                    <span class="sat-value">${velocity} km/s</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">经度</span>
                    <span class="sat-value">${pos.lng.toFixed(4)}°</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">纬度</span>
                    <span class="sat-value">${pos.lat.toFixed(4)}°</span>
                </div>
                <div class="sat-info-row">
                    <span class="sat-label">状态</span>
                    <span class="sat-value" style="color:#00e676;">● 在轨运行</span>
                </div>
            </div>
        </div>
    `;

    // 使用自定义弹窗
    const popup = L.popup({
        className: 'satellite-popup-container',
        maxWidth: 320,
        minWidth: 280,
    })
    .setLatLng([pos.lat, pos.lng])
    .setContent(html)
    .openOn(map);

    // 持续更新位置
    if (satelliteTrackTimer) clearInterval(satelliteTrackTimer);
    satelliteTrackTimer = setInterval(() => {
        const newPos = calcSatellitePosition(sat.tle1, sat.tle2);
        if (newPos) {
            popup.setLatLng([newPos.lat, newPos.lng]);
            // 更新弹窗内的数据
            const velocityEl = popup.getElement()?.querySelector('.sat-value');
            // 简单更新：重新设置内容
        }
    }, 5000);
}

/**
 * 渲染所有卫星到地图
 */
function renderSatellites() {
    if (satelliteLayer) {
        map.removeLayer(satelliteLayer);
    }
    satelliteLayer = L.layerGroup();
    satelliteMarkers = [];

    let count = 0;
    for (const sat of satelliteData) {
        const pos = calcSatellitePosition(sat.tle1, sat.tle2);
        if (!pos) continue;

        const config = SAT_CATEGORY_CONFIG[sat.category] || { color: '#546E7A', icon: '🛰️' };
        const nameCN = getSatelliteNameCN(sat.name);

        // 创建卫星图标
        const icon = L.divIcon({
            className: 'satellite-marker',
            html: `<div class="sat-marker" style="background:${config.color};">
                       <span>${config.icon}</span>
                   </div>`,
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        });

        const marker = L.marker([pos.lat, pos.lng], { icon })
            .bindPopup(() => {
                const p = calcSatellitePosition(sat.tle1, sat.tle2);
                if (p) {
                    return showSatellitePopup(sat, p);
                }
                return '位置计算中...';
            })
            .on('click', () => {
                selectedSatellite = sat;
                showSatelliteTrack(sat);
            });

        satelliteMarkers.push({ sat, marker, lastPos: pos });
        satelliteLayer.addLayer(marker);
        count++;
    }

    if (showSatellites) {
        satelliteLayer.addTo(map);
    }

    console.log(`已渲染 ${count} 颗卫星`);
}

/**
 * 更新所有卫星位置（实时刷新）
 */
function updateSatellitePositions() {
    for (const item of satelliteMarkers) {
        const pos = calcSatellitePosition(item.sat.tle1, item.sat.tle2);
        if (pos) {
            item.marker.setLatLng([pos.lat, pos.lng]);
            item.lastPos = pos;
        }
    }
}

/**
 * 切换卫星显示
 */
function toggleSatellites(forceOn) {
    if (forceOn === true) {
        showSatellites = true;
    } else {
        showSatellites = !showSatellites;
    }

    if (showSatellites) {
        if (!satelliteData.length) {
            loadSatelliteData().then(() => renderSatellites());
        } else if (!satelliteMarkers.length) {
            renderSatellites();
        } else {
            satelliteLayer.addTo(map);
        }

        // 启动实时更新（每30秒）
        if (!satelliteUpdateTimer) {
            satelliteUpdateTimer = setInterval(updateSatellitePositions, 30000);
        }

        // 更新按钮状态
        const btn = document.getElementById('btn-toggle-sat');
        if (btn) btn.classList.add('active');
    } else {
        if (satelliteLayer) {
            map.removeLayer(satelliteLayer);
        }
        if (satelliteUpdateTimer) {
            clearInterval(satelliteUpdateTimer);
            satelliteUpdateTimer = null;
        }
        if (satelliteTrackPolyline) {
            map.removeLayer(satelliteTrackPolyline);
            satelliteTrackPolyline = null;
        }
        if (satelliteTrackTimer) {
            clearInterval(satelliteTrackTimer);
            satelliteTrackTimer = null;
        }

        const btn = document.getElementById('btn-toggle-sat');
        if (btn) btn.classList.remove('active');
    }
}

/**
 * 初始化卫星追踪模块
 */
function initSatellites() {
    // 预加载卫星数据（不渲染）
    loadSatelliteData();
}
