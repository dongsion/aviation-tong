/**
 * 航空通 Pro - 智能航线避让
 * 输入起飞/到达机场，AI 自动规划避开 NOTAM 危险区的航线
 */

let routePlannerLayer = null;
let routePlannerData = null;

function openRoutePlanner() {
    const modal = createModal('route-planner-modal', '🛫 智能航线避让规划');

    const body = modal.querySelector('.modal-body');
    body.innerHTML = `
        <div class="route-planner-form">
            <div class="form-group">
                <label class="form-label">起飞机场 (ICAO/IATA)</label>
                <input type="text" id="rp-departure" class="form-input" placeholder="如 ZBAA 或 PEK" list="airport-datalist">
            </div>
            <div class="form-group">
                <label class="form-label">到达机场 (ICAO/IATA)</label>
                <input type="text" id="rp-arrival" class="form-input" placeholder="如 ZGGG 或 CAN" list="airport-datalist">
            </div>
            <datalist id="airport-datalist">
                ${Object.entries(AIRPORT_DB).map(([icao, a]) => `<option value="${icao}">${a.name}</option><option value="${a.iata}">${a.name}</option>`).join('')}
            </datalist>
            <div class="form-group">
                <label class="form-label">避让距离 (km)</label>
                <input type="number" id="rp-margin" class="form-input" value="50" min="10" max="200" step="10">
            </div>
            <button class="btn-premium-primary" onclick="planRoute()">🛫 规划避让航线</button>
        </div>
        <div id="rp-results" style="margin-top:16px;"></div>
    `;
}

/**
 * 规划避让航线
 */
function planRoute() {
    const depInput = document.getElementById('rp-departure').value.trim().toUpperCase();
    const arrInput = document.getElementById('rp-arrival').value.trim().toUpperCase();
    const margin = parseInt(document.getElementById('rp-margin').value) || 50;

    const dep = AIRPORT_DB[depInput] || AIRPORT_DB[IATA_TO_ICAO[depInput]];
    const arr = AIRPORT_DB[arrInput] || AIRPORT_DB[IATA_TO_ICAO[arrInput]];

    if (!dep || !arr) {
        document.getElementById('rp-results').innerHTML = '<div class="premium-error">机场代码无效，请输入有效的 ICAO 或 IATA 代码</div>';
        return;
    }

    // 计算大圆航线
    const route = calculateGreatCircle([dep.lat, dep.lng], [arr.lat, arr.lng]);

    // 检查 NOTAM 冲突
    const conflicts = [];
    for (const feature of allFeatures) {
        const props = feature.properties || {};
        if (!['danger', 'restricted', 'prohibited', 'tfr'].includes(props.type)) continue;

        const geometry = feature.geometry;
        if (!geometry || geometry.type !== 'Polygon') continue;

        // 检查航线是否经过 NOTAM 区域附近
        const notamCenter = getPolygonCenter(geometry.coordinates[0]);
        const minDist = minDistanceToRoute(route, notamCenter);

        if (minDist < margin) {
            conflicts.push({
                notamCode: props.notam_code,
                notamType: props.type,
                notamName: (TYPE_CONFIG[props.type] || {}).name || '未知',
                distance: minDist.toFixed(1),
                center: notamCenter,
            });
        }
    }

    // 生成避让航线
    let avoidRoute = route;
    if (conflicts.length > 0) {
        avoidRoute = generateAvoidanceRoute(route, conflicts, margin);
    }

    // 渲染结果
    renderRouteResult(dep, arr, route, avoidRoute, conflicts, margin);
}

/**
 * 计算大圆航线
 */
function calculateGreatCircle(p1, p2, segments = 64) {
    const points = [];
    const lat1 = p1[0] * Math.PI / 180;
    const lng1 = p1[1] * Math.PI / 180;
    const lat2 = p2[0] * Math.PI / 180;
    const lng2 = p2[1] * Math.PI / 180;

    for (let i = 0; i <= segments; i++) {
        const f = i / segments;
        const d = 2 * Math.asin(Math.sqrt(
            Math.sin((lat2 - lat1) / 2) ** 2 +
            Math.cos(lat1) * Math.cos(lat2) * Math.sin((lng2 - lng1) / 2) ** 2
        ));

        if (d === 0) {
            points.push([p1[0], p1[1]]);
            continue;
        }

        const A = Math.sin((1 - f) * d) / Math.sin(d);
        const B = Math.sin(f * d) / Math.sin(d);
        const x = A * Math.cos(lat1) * Math.cos(lng1) + B * Math.cos(lat2) * Math.cos(lng2);
        const y = A * Math.cos(lat1) * Math.sin(lng1) + B * Math.cos(lat2) * Math.sin(lng2);
        const z = A * Math.sin(lat1) + B * Math.sin(lat2);

        const lat = Math.atan2(z, Math.sqrt(x * x + y * y)) * 180 / Math.PI;
        const lng = Math.atan2(y, x) * 180 / Math.PI;
        points.push([lat, lng]);
    }
    return points;
}

/**
 * 获取多边形中心
 */
function getPolygonCenter(coords) {
    let lat = 0, lng = 0;
    for (const c of coords) {
        lng += c[0];
        lat += c[1];
    }
    return [lat / coords.length, lng / coords.length];
}

/**
 * 计算点到航线的最短距离 (km)
 */
function minDistanceToRoute(route, point) {
    let minDist = Infinity;
    for (const rp of route) {
        const d = haversine(rp, point);
        if (d < minDist) minDist = d;
    }
    return minDist;
}

/**
 * Haversine 距离公式
 */
function haversine(p1, p2) {
    const R = 6371;
    const lat1 = p1[0] * Math.PI / 180;
    const lat2 = p2[0] * Math.PI / 180;
    const dlat = (p2[0] - p1[0]) * Math.PI / 180;
    const dlng = (p2[1] - p1[1]) * Math.PI / 180;
    const a = Math.sin(dlat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dlng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * 生成避让航线（简化算法：在冲突点附近绕行）
 */
function generateAvoidanceRoute(route, conflicts, margin) {
    const newRoute = [...route];
    for (const conflict of conflicts) {
        // 找到航线中距冲突最近的点
        let nearestIdx = 0;
        let nearestDist = Infinity;
        for (let i = 0; i < newRoute.length; i++) {
            const d = haversine(newRoute[i], conflict.center);
            if (d < nearestDist) {
                nearestDist = d;
                nearestIdx = i;
            }
        }

        // 在最近的点上施加偏移
        const offsetLat = (conflict.center[0] - newRoute[nearestIdx][0]) > 0 ? -1 : 1;
        const offsetLng = (conflict.center[1] - newRoute[nearestIdx][1]) > 0 ? -1 : 1;
        const offsetKm = margin / 111; // 简化转换

        // 偏移航线附近的几个点
        const range = 5;
        for (let i = Math.max(0, nearestIdx - range); i <= Math.min(newRoute.length - 1, nearestIdx + range); i++) {
            const factor = 1 - Math.abs(i - nearestIdx) / (range + 1);
            newRoute[i] = [
                newRoute[i][0] + offsetLat * offsetKm * factor,
                newRoute[i][1] + offsetLng * offsetKm * factor,
            ];
        }
    }
    return newRoute;
}

/**
 * 渲染航线结果
 */
function renderRouteResult(dep, arr, route, avoidRoute, conflicts, margin) {
    const distance = route.reduce((sum, p, i) => i > 0 ? sum + haversine(route[i - 1], p) : 0, 0);
    const avoidDistance = avoidRoute.reduce((sum, p, i) => i > 0 ? sum + haversine(avoidRoute[i - 1], p) : 0, 0);
    const extraKm = (avoidDistance - distance).toFixed(0);
    const extraPct = ((avoidDistance / distance - 1) * 100).toFixed(1);

    const results = document.getElementById('rp-results');
    results.innerHTML = `
        <div class="route-result-card">
            <div class="route-summary">
                <div class="route-airports">
                    <span>${getFlag(dep.country)} ${escapeHtml(dep.name)}</span>
                    <span class="route-arrow-icon">✈️</span>
                    <span>${getFlag(arr.country)} ${escapeHtml(arr.name)}</span>
                </div>
                <div class="route-stats">
                    <div class="route-stat"><span>直飞距离</span><strong>${distance.toFixed(0)} km</strong></div>
                    <div class="route-stat"><span>避让距离</span><strong>${avoidDistance.toFixed(0)} km</strong></div>
                    <div class="route-stat ${conflicts.length > 0 ? 'route-stat-warn' : 'route-stat-ok'}">
                        <span>额外距离</span><strong>+${extraKm} km (+${extraPct}%)</strong>
                    </div>
                    <div class="route-stat ${conflicts.length > 0 ? 'route-stat-warn' : 'route-stat-ok'}">
                        <span>NOTAM 冲突</span><strong>${conflicts.length} 个</strong>
                    </div>
                </div>
            </div>
            ${conflicts.length > 0 ? `
            <div class="route-conflicts">
                <h4>⚠️ 避让的 NOTAM 区域</h4>
                ${conflicts.map(c => `
                    <div class="conflict-item">
                        <span class="conflict-type" style="color:${(TYPE_CONFIG[c.notamType] || {}).color}">${c.notamName}</span>
                        <span>${escapeHtml(c.notamCode)}</span>
                        <span class="conflict-dist">最近距离 ${c.distance}km</span>
                    </div>
                `).join('')}
            </div>` : '<div class="route-no-conflict">✅ 航线无 NOTAM 冲突</div>'}
            <button class="btn-premium-secondary" onclick="renderRouteOnMap()">在地图上显示航线</button>
        </div>
    `;

    routePlannerData = { route, avoidRoute, dep, arr, conflicts };
}

/**
 * 在地图上渲染航线
 */
function renderRouteOnMap() {
    if (!routePlannerData) return;

    if (routePlannerLayer) {
        map.removeLayer(routePlannerLayer);
    }
    routePlannerLayer = L.layerGroup();

    const { route, avoidRoute, dep, arr, conflicts } = routePlannerData;

    // 直飞航线（虚线灰色）
    L.polyline(route, {
        color: '#546E7A',
        weight: 2,
        opacity: 0.5,
        dashArray: '5,5',
    }).addTo(routePlannerLayer);

    // 避让航线（实线蓝色）
    if (conflicts.length > 0) {
        L.polyline(avoidRoute, {
            color: '#2962FF',
            weight: 3,
            opacity: 0.9,
        }).addTo(routePlannerLayer);
    } else {
        L.polyline(route, {
            color: '#00E676',
            weight: 3,
            opacity: 0.9,
        }).addTo(routePlannerLayer);
    }

    // 起降点标记
    L.marker([dep.lat, dep.lng], {
        icon: L.divIcon({
            html: '<div style="font-size:20px">🛫</div>',
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        }),
    }).addTo(routePlannerLayer).bindPopup(`起飞: ${dep.name}`);

    L.marker([arr.lat, arr.lng], {
        icon: L.divIcon({
            html: '<div style="font-size:20px">🛬</div>',
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        }),
    }).addTo(routePlannerLayer).bindPopup(`到达: ${arr.name}`);

    routePlannerLayer.addTo(map);

    // 缩放到航线范围
    const bounds = L.latLngBounds(route);
    map.fitBounds(bounds, { padding: [60, 60] });

    document.getElementById('route-planner-modal').remove();
}
