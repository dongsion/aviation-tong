/**
 * 航空通 Pro - NOTAM 影响分析
 * 输入航班号/航线，自动分析受影响的 NOTAM 列表
 */

function openNotamImpact() {
    const modal = createModal('notam-impact-modal', '🔍 NOTAM 影响分析');

    const body = modal.querySelector('.modal-body');
    body.innerHTML = `
        <div class="route-planner-form">
            <div class="form-group">
                <label class="form-label">起飞机场 (ICAO/IATA)</label>
                <input type="text" id="ni-departure" class="form-input" placeholder="如 ZBAA 或 PEK" list="airport-datalist">
            </div>
            <div class="form-group">
                <label class="form-label">到达机场 (ICAO/IATA)</label>
                <input type="text" id="ni-arrival" class="form-input" placeholder="如 ZGGG 或 CAN" list="airport-datalist">
            </div>
            <datalist id="airport-datalist">
                ${Object.entries(AIRPORT_DB).map(([icao, a]) => `<option value="${icao}">${a.name}</option><option value="${a.iata}">${a.name}</option>`).join('')}
            </datalist>
            <div class="form-group">
                <label class="form-label">飞行高度层 (ft)</label>
                <input type="number" id="ni-altitude" class="form-input" placeholder="如 35000" value="35000">
            </div>
            <button class="btn-premium-primary" onclick="analyzeNotamImpact()">🔍 分析 NOTAM 影响</button>
        </div>
        <div id="ni-results" style="margin-top:16px;"></div>
    `;
}

/**
 * 分析 NOTAM 影响
 */
function analyzeNotamImpact() {
    const depInput = document.getElementById('ni-departure').value.trim().toUpperCase();
    const arrInput = document.getElementById('ni-arrival').value.trim().toUpperCase();
    const altitude = parseInt(document.getElementById('ni-altitude').value) || 35000;

    const dep = AIRPORT_DB[depInput] || AIRPORT_DB[IATA_TO_ICAO[depInput]];
    const arr = AIRPORT_DB[arrInput] || AIRPORT_DB[IATA_TO_ICAO[arrInput]];

    if (!dep || !arr) {
        document.getElementById('ni-results').innerHTML = '<div class="premium-error">机场代码无效</div>';
        return;
    }

    // 计算航线
    const route = calculateGreatCircle([dep.lat, dep.lng], [arr.lat, arr.lng]);
    const routeDistance = route.reduce((sum, p, i) => i > 0 ? sum + haversine(route[i - 1], p) : 0, 0);

    // 分析每个 NOTAM
    const impacts = [];
    for (const feature of allFeatures) {
        const props = feature.properties || {};
        const geometry = feature.geometry;
        if (!geometry || geometry.type !== 'Polygon') continue;

        const notamCenter = getPolygonCenter(geometry.coordinates[0]);
        const minDist = minDistanceToRoute(route, notamCenter);

        // 100km 范围内的 NOTAM 视为潜在影响
        if (minDist < 100) {
            const config = TYPE_CONFIG[props.type] || TYPE_CONFIG.other;
            const severity = calculateSeverity(props.type, minDist);
            impacts.push({
                notamCode: props.notam_code,
                notamType: props.type,
                notamName: config.name,
                color: config.color,
                distance: minDist.toFixed(1),
                severity,
                start: props.start,
                end: props.end,
                fir: props.fir,
                center: notamCenter,
            });
        }
    }

    // 按严重程度排序
    impacts.sort((a, b) => b.severity - a.severity);

    renderImpactResult(dep, arr, route, routeDistance, impacts, altitude);
}

/**
 * 计算严重程度 (0-100)
 */
function calculateSeverity(type, distance) {
    const typeWeight = {
        'prohibited': 100,
        'danger': 80,
        'restricted': 70,
        'tfr': 60,
        'warning': 40,
        'airway': 30,
        'other': 10,
    };
    const weight = typeWeight[type] || 10;
    // 距离越近，严重度越高
    const distanceFactor = Math.max(0, 1 - distance / 100);
    return Math.round(weight * distanceFactor);
}

/**
 * 渲染影响分析结果
 */
function renderImpactResult(dep, arr, route, distance, impacts, altitude) {
    const critical = impacts.filter(i => i.severity >= 60);
    const warning = impacts.filter(i => i.severity >= 30 && i.severity < 60);
    const info = impacts.filter(i => i.severity < 30);

    const results = document.getElementById('ni-results');
    results.innerHTML = `
        <div class="route-result-card">
            <div class="route-summary">
                <div class="route-airports">
                    <span>${getFlag(dep.country)} ${escapeHtml(dep.name)}</span>
                    <span class="route-arrow-icon">✈️</span>
                    <span>${getFlag(arr.country)} ${escapeHtml(arr.name)}</span>
                </div>
                <div class="route-stats">
                    <div class="route-stat"><span>航线距离</span><strong>${distance.toFixed(0)} km</strong></div>
                    <div class="route-stat"><span>飞行高度</span><strong>FL${(altitude / 100).toFixed(0)}</strong></div>
                    <div class="route-stat ${critical.length > 0 ? 'route-stat-danger' : 'route-stat-ok'}"><span>严重</span><strong>${critical.length}</strong></div>
                    <div class="route-stat ${warning.length > 0 ? 'route-stat-warn' : 'route-stat-ok'}"><span>警告</span><strong>${warning.length}</strong></div>
                    <div class="route-stat"><span>提示</span><strong>${info.length}</strong></div>
                </div>
            </div>

            ${critical.length > 0 ? `
            <div class="impact-section impact-critical">
                <h4>🔴 严重影响 (${critical.length})</h4>
                ${critical.map(i => `
                    <div class="impact-item" style="border-left-color:${i.color}">
                        <div class="impact-code">${escapeHtml(i.notamCode)} <span class="impact-severity">${i.severity}/100</span></div>
                        <div class="impact-detail">${i.notamName} · 距航线 ${i.distance}km · ${escapeHtml(i.fir || '')}</div>
                        <div class="impact-time">${escapeHtml(i.start || '')} ~ ${escapeHtml(i.end || '')}</div>
                    </div>
                `).join('')}
            </div>` : ''}

            ${warning.length > 0 ? `
            <div class="impact-section impact-warning">
                <h4>🟡 警告 (${warning.length})</h4>
                ${warning.map(i => `
                    <div class="impact-item" style="border-left-color:${i.color}">
                        <div class="impact-code">${escapeHtml(i.notamCode)} <span class="impact-severity">${i.severity}/100</span></div>
                        <div class="impact-detail">${i.notamName} · 距航线 ${i.distance}km</div>
                    </div>
                `).join('')}
            </div>` : ''}

            ${impacts.length === 0 ? '<div class="route-no-conflict">✅ 航线无 NOTAM 影响</div>' : ''}

            <button class="btn-premium-secondary" onclick="renderImpactOnMap()">在地图上显示影响区域</button>
        </div>
    `;

    window._impactData = { route, impacts, dep, arr };
}

/**
 * 在地图上显示影响分析
 */
function renderImpactOnMap() {
    const data = window._impactData;
    if (!data) return;

    if (window._impactLayer) {
        map.removeLayer(window._impactLayer);
    }
    window._impactLayer = L.layerGroup();

    // 航线
    L.polyline(data.route, {
        color: '#2962FF',
        weight: 3,
        opacity: 0.7,
    }).addTo(window._impactLayer);

    // 影响 NOTAM 圆圈
    for (const impact of data.impacts) {
        const color = impact.severity >= 60 ? '#FF1744' : impact.severity >= 30 ? '#FFAB00' : '#546E7A';
        L.circle(impact.center, {
            radius: 100000,
            color: color,
            fillColor: color,
            fillOpacity: 0.15,
            weight: 2,
        }).addTo(window._impactLayer).bindPopup(`
            <strong>${escapeHtml(impact.notamCode)}</strong><br>
            ${escapeHtml(impact.notamName)}<br>
            严重度: ${impact.severity}/100<br>
            距航线: ${impact.distance}km
        `);
    }

    window._impactLayer.addTo(map);
    const bounds = L.latLngBounds(data.route);
    map.fitBounds(bounds, { padding: [60, 60] });

    document.getElementById('notam-impact-modal').remove();
}
