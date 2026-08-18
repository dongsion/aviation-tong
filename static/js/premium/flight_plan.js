/**
 * 航空通 - 飞行计划分析器 (付费功能)
 * 输入起飞/降落机场与巡航高度，分析航线上受影响的 NOTAM
 * 依赖: map.js (escapeHtml, map, allFeatures, TYPE_CONFIG)、Leaflet
 */

// ============================================================
// 全局状态
// ============================================================
let flightPlanRouteLayer = null;       // 飞行路线图层
let flightPlanHighlightLayer = null;   // 受影响 NOTAM 高亮图层
let flightPlanAnalysisResult = null;    // 最近一次分析结果
let airportAutocompleteData = { dep: null, arr: null, depIdx: -1, arrIdx: -1 };
let activeAutocomplete = null;          // 当前激活的自动补全

// ============================================================
// 中国主要机场数据库 (ICAO 代码 + 坐标)
// ============================================================
const CHINA_AIRPORTS = [
    { icao: 'ZBAA', name: '北京首都国际机场', lat: 40.0801, lng: 116.5846 },
    { icao: 'ZBAD', name: '北京大兴国际机场', lat: 39.5092, lng: 116.4108 },
    { icao: 'ZSPD', name: '上海浦东国际机场', lat: 31.1443, lng: 121.8083 },
    { icao: 'ZSSS', name: '上海虹桥国际机场', lat: 31.1979, lng: 121.3360 },
    { icao: 'ZGGG', name: '广州白云国际机场', lat: 23.3924, lng: 113.2989 },
    { icao: 'ZGSZ', name: '深圳宝安国际机场', lat: 22.6394, lng: 113.8108 },
    { icao: 'ZUUU', name: '成都双流国际机场', lat: 30.5785, lng: 103.9472 },
    { icao: 'ZUCK', name: '成都天府国际机场', lat: 30.3120, lng: 104.4419 },
    { icao: 'ZLXY', name: '西安咸阳国际机场', lat: 34.4473, lng: 108.7517 },
    { icao: 'ZPPP', name: '昆明长水国际机场', lat: 25.1019, lng: 102.9292 },
    { icao: 'ZWWW', name: '乌鲁木齐地窝堡机场', lat: 43.9072, lng: 87.4742 },
    { icao: 'ZSHC', name: '杭州萧山国际机场', lat: 30.2678, lng: 120.4344 },
    { icao: 'ZSTN', name: '天津滨海国际机场', lat: 39.1245, lng: 117.2094 },
    { icao: 'ZSNJ', name: '南京禄口国际机场', lat: 31.7420, lng: 118.8622 },
    { icao: 'ZSAM', name: '厦门高崎国际机场', lat: 24.5444, lng: 118.1273 },
    { icao: 'ZGHA', name: '长沙黄花国际机场', lat: 28.1892, lng: 113.2196 },
    { icao: 'ZHHH', name: '武汉天河国际机场', lat: 30.7838, lng: 114.2081 },
    { icao: 'ZSQD', name: '青岛胶东国际机场', lat: 36.3665, lng: 120.3750 },
    { icao: 'ZSCN', name: '南昌昌北国际机场', lat: 28.8644, lng: 115.8896 },
    { icao: 'ZUGY', name: '贵阳龙洞堡机场', lat: 26.5385, lng: 106.8009 },
    { icao: 'ZLIC', name: '银川河东机场', lat: 38.3592, lng: 106.3931 },
    { icao: 'ZBHH', name: '呼和浩特白塔机场', lat: 40.6292, lng: 111.8247 },
    { icao: 'ZYYJ', name: '延吉朝阳川机场', lat: 42.8847, lng: 129.4536 },
    { icao: 'ZYTX', name: '丹东浪头机场', lat: 40.0267, lng: 124.2861 },
    { icao: 'ZYTL', name: '大连周水子机场', lat: 38.9657, lng: 121.5386 },
    { icao: 'ZSFZ', name: '福州长乐国际机场', lat: 25.9351, lng: 119.6539 },
    { icao: 'ZHCC', name: '郑州新郑国际机场', lat: 34.5197, lng: 113.8407 },
    { icao: 'ZJSY', name: '三亚凤凰国际机场', lat: 18.3029, lng: 109.4124 },
    { icao: 'ZGHK', name: '海口美兰国际机场', lat: 19.9349, lng: 110.4589 },
    { icao: 'ZUST', name: '石家庄正定机场', lat: 38.2848, lng: 114.7125 },
    { icao: 'ZGCJ', name: '重庆江北国际机场', lat: 29.7189, lng: 106.6414 },
    { icao: 'ZUCK', name: '成都天府国际机场', lat: 30.3120, lng: 104.4419 },
    { icao: 'ZLXN', name: '西宁曹家堡机场', lat: 36.5333, lng: 102.0372 },
    { icao: 'ZLYA', name: '延安二十里堡机场', lat: 36.6375, lng: 109.5847 },
    { icao: 'ZBOW', name: '包头东河机场', lat: 40.1417, lng: 109.9900 },
    { icao: 'ZBTJ', name: '天津滨海国际机场', lat: 39.1245, lng: 117.2094 },
    { icao: 'ZLDH', name: '敦煌机场', lat: 40.1622, lng: 94.8006 },
    { icao: 'ZLHZ', name: '汉中城固机场', lat: 33.0872, lng: 107.2675 },
    { icao: 'ZWHM', name: '哈密机场', lat: 42.3361, lng: 93.6700 },
    { icao: 'ZWNL', name: '那拉提机场', lat: 43.3306, lng: 84.4711 },
    { icao: 'ZPJY', name: '普洱思茅机场', lat: 22.7928, lng: 100.9625 },
];

// 影响等级配置
const IMPACT_LEVEL_CONFIG = {
    critical: { name: '严重', color: '#FF1744', order: 0 },
    warning:  { name: '警告', color: '#FFD600', order: 1 },
    info:     { name: '信息', color: '#2962FF', order: 2 },
};

// 距离阈值 (公里)
const DISTANCE_THRESHOLD_CRITICAL = 50;   // 50km 内为严重
const DISTANCE_THRESHOLD_WARNING = 150;    // 150km 内为警告
const DISTANCE_THRESHOLD_INFO = 400;      // 400km 内为信息

// 地球半径 (公里)
const EARTH_RADIUS_KM = 6371;

// ============================================================
// 机场 ICAO 自动补全
// ============================================================

/**
 * 初始化自动补全
 */
function initAirportAutocomplete() {
    const depInput = document.getElementById('fp-departure');
    const arrInput = document.getElementById('fp-arrival');

    if (depInput) {
        depInput.addEventListener('input', function() {
            showAutocomplete(depInput, 'dep');
        });
        depInput.addEventListener('focus', function() {
            if (depInput.value.length >= 1) showAutocomplete(depInput, 'dep');
        });
        depInput.addEventListener('blur', function() {
            setTimeout(function() { hideAutocomplete('dep'); }, 200);
        });
        depInput.addEventListener('keydown', function(e) {
            onAutocompleteKeydown(e, 'dep');
        });
    }

    if (arrInput) {
        arrInput.addEventListener('input', function() {
            showAutocomplete(arrInput, 'arr');
        });
        arrInput.addEventListener('focus', function() {
            if (arrInput.value.length >= 1) showAutocomplete(arrInput, 'arr');
        });
        arrInput.addEventListener('blur', function() {
            setTimeout(function() { hideAutocomplete('arr'); }, 200);
        });
        arrInput.addEventListener('keydown', function(e) {
            onAutocompleteKeydown(e, 'arr');
        });
    }
}

/**
 * 显示自动补全下拉
 */
function showAutocomplete(input, type) {
    const query = input.value.trim().toUpperCase();
    activeAutocomplete = type;

    // 查找或创建下拉容器
    let wrapper = input.closest('.autocomplete-wrapper');
    if (!wrapper) {
        // 包裹 input
        wrapper = document.createElement('div');
        wrapper.className = 'autocomplete-wrapper';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);
    }

    let dropdown = wrapper.querySelector('.autocomplete-dropdown');
    if (!dropdown) {
        dropdown = document.createElement('div');
        dropdown.className = 'autocomplete-dropdown';
        wrapper.appendChild(dropdown);
    }

    if (query.length === 0) {
        dropdown.classList.remove('visible');
        return;
    }

    // 搜索匹配的机场
    const results = CHINA_AIRPORTS.filter(function(ap) {
        return ap.icao.includes(query) || ap.name.toUpperCase().includes(query) ||
               ap.icao.startsWith(query) || ap.name.toUpperCase().startsWith(query);
    }).slice(0, 10);

    if (results.length === 0) {
        dropdown.classList.remove('visible');
        return;
    }

    let html = '';
    results.forEach(function(ap, idx) {
        html +=
            '<div class="autocomplete-item' + (idx === 0 ? ' active' : '') + '" data-idx="' + idx + '" ' +
            'onclick="selectAirport(\'' + escapeHtml(type) + '\',' + idx + ')" ' +
            'data-icao="' + escapeHtml(ap.icao) + '">' +
                '<span class="autocomplete-item-code">' + escapeHtml(ap.icao) + '</span>' +
                '<span class="autocomplete-item-name">' + escapeHtml(ap.name) + '</span>' +
            '</div>';
    });

    dropdown.innerHTML = html;
    dropdown.classList.add('visible');

    if (type === 'dep') {
        airportAutocompleteData.dep = results;
        airportAutocompleteData.depIdx = -1;
    } else {
        airportAutocompleteData.arr = results;
        airportAutocompleteData.arrIdx = -1;
    }
}

/**
 * 隐藏自动补全
 */
function hideAutocomplete(type) {
    const wrapper = document.querySelector('#fp-' + (type === 'dep' ? 'departure' : 'arrival')).closest('.autocomplete-wrapper');
    if (wrapper) {
        const dropdown = wrapper.querySelector('.autocomplete-dropdown');
        if (dropdown) dropdown.classList.remove('visible');
    }
    if (activeAutocomplete === type) activeAutocomplete = null;
}

/**
 * 键盘导航
 */
function onAutocompleteKeydown(e, type) {
    const data = type === 'dep' ? airportAutocompleteData.dep : airportAutocompleteData.arr;
    if (!data || data.length === 0) return;

    let idx = type === 'dep' ? airportAutocompleteData.depIdx : airportAutocompleteData.arrIdx;
    const wrapper = e.target.closest('.autocomplete-wrapper');
    const dropdown = wrapper ? wrapper.querySelector('.autocomplete-dropdown') : null;
    if (!dropdown) return;

    const items = dropdown.querySelectorAll('.autocomplete-item');

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        idx = Math.min(idx + 1, items.length - 1);
        updateAutocompleteActive(items, type, idx);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        idx = Math.max(idx - 1, -1);
        updateAutocompleteActive(items, type, idx);
    } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (idx >= 0 && idx < data.length) {
            e.preventDefault();
            selectAirport(type, idx);
        }
    } else if (e.key === 'Escape') {
        dropdown.classList.remove('visible');
    }
}

function updateAutocompleteActive(items, type, idx) {
    items.forEach(function(item, i) {
        item.classList.toggle('active', i === idx);
    });
    if (type === 'dep') {
        airportAutocompleteData.depIdx = idx;
    } else {
        airportAutocompleteData.arrIdx = idx;
    }
}

/**
 * 选中机场
 */
function selectAirport(type, idx) {
    const data = type === 'dep' ? airportAutocompleteData.dep : airportAutocompleteData.arr;
    if (!data || idx < 0 || idx >= data.length) return;

    const airport = data[idx];
    const input = document.getElementById(type === 'dep' ? 'fp-departure' : 'fp-arrival');
    if (input) {
        input.value = airport.icao;
    }

    hideAutocomplete(type);
    if (typeof showToast === 'function') {
        showToast('已选择: ' + airport.icao + ' ' + airport.name, 'info');
    }
}

// ============================================================
// 地理计算工具
// ============================================================

/**
 * 角度转弧度
 */
function toRadians(deg) {
    return deg * Math.PI / 180;
}

/**
 * 弧度转角度
 */
function toDegrees(rad) {
    return rad * 180 / Math.PI;
}

/**
 * 计算两点间大圆距离 (Haversine 公式)
 * @returns 距离(公里)
 */
function haversineDistance(lat1, lng1, lat2, lng2) {
    const dLat = toRadians(lat2 - lat1);
    const dLng = toRadians(lng2 - lng1);
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
        Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return EARTH_RADIUS_KM * c;
}

/**
 * 计算点到线段(大圆路径)的垂直距离
 * 使用近似: 将经纬度投影到平面后计算
 * @returns 距离(公里)
 */
function pointToRouteDistance(pLat, pLng, aLat, aLng, bLat, bLng) {
    // 将经纬度转换为近似平面坐标 (公里)
    const latMid = toRadians((aLat + bLat) / 2);
    const px = pLng * Math.cos(latMid) * 111.32;
    const py = pLat * 111.0;
    const ax = aLng * Math.cos(latMid) * 111.32;
    const ay = aLat * 111.0;
    const bx = bLng * Math.cos(latMid) * 111.32;
    const by = bLat * 111.0;

    const dx = bx - ax;
    const dy = by - ay;
    const lenSq = dx * dx + dy * dy;

    if (lenSq === 0) {
        // A 和 B 重合
        return Math.sqrt((px - ax) * (px - ax) + (py - ay) * (py - ay));
    }

    // 参数 t: 点在 AB 线段上的投影位置
    let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));

    const projX = ax + t * dx;
    const projY = ay + t * dy;

    return Math.sqrt((px - projX) * (px - projX) + (py - projY) * (py - projY));
}

/**
 * 计算 NOTAM 多边形质心
 */
function calcPolygonCentroid(feature) {
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== 'Polygon') return null;

    const coords = geometry.coordinates[0];
    let area = 0;
    let cx = 0, cy = 0;

    for (let i = 0; i < coords.length - 1; i++) {
        const x0 = coords[i][0];
        const y0 = coords[i][1];
        const x1 = coords[i + 1][0];
        const y1 = coords[i + 1][1];
        const cross = x0 * y1 - x1 * y0;
        area += cross;
        cx += (x0 + x1) * cross;
        cy += (y0 + y1) * cross;
    }

    area = area / 2;
    if (area === 0) {
        // 退化为平均值
        let sumLng = 0, sumLat = 0;
        coords.forEach(function(c) { sumLng += c[0]; sumLat += c[1]; });
        return { lat: sumLat / coords.length, lng: sumLng / coords.length };
    }

    cx = cx / (6 * area);
    cy = cy / (6 * area);
    return { lat: cy, lng: cx };
}

/**
 * 解析 NOTAM 高度范围
 * 返回 { min: 米, max: 米 } 或 null
 */
function parseNotamAltitude(altitudeStr) {
    if (!altitudeStr) return null;

    const str = String(altitudeStr);
    const numbers = str.match(/(\d+)\s*[~～到]\s*(\d+)/);
    if (numbers) {
        return { min: parseInt(numbers[1], 10), max: parseInt(numbers[2], 10) };
    }

    // 单一高度
    const single = str.match(/(\d+)/);
    if (single) {
        const val = parseInt(single[1], 10);
        return { min: 0, max: val };
    }

    return null;
}

/**
 * 英尺转米
 */
function feetToMeters(feet) {
    return feet * 0.3048;
}

/**
 * 米转英尺
 */
function metersToFeet(meters) {
    return meters / 0.3048;
}

// ============================================================
// 飞行计划分析 (核心逻辑)
// ============================================================

/**
 * 分析飞行计划 - 主入口
 */
async function analyzeFlightPlan() {
    const depIcao = (document.getElementById('fp-departure') || {}).value;
    const arrIcao = (document.getElementById('fp-arrival') || {}).value;
    const depTime = (document.getElementById('fp-time') || {}).value;
    const cruiseAltFt = parseInt((document.getElementById('fp-altitude') || {}).value, 10);

    if (!depIcao || !arrIcao) {
        showToast('请输入起飞和降落机场代码', 'error');
        return;
    }

    const depAirport = CHINA_AIRPORTS.find(function(a) { return a.icao === depIcao.toUpperCase(); });
    const arrAirport = CHINA_AIRPORTS.find(function(a) { return a.icao === arrIcao.toUpperCase(); });

    if (!depAirport) {
        showToast('未找到起飞机场: ' + depIcao, 'error');
        return;
    }
    if (!arrAirport) {
        showToast('未找到降落机场: ' + arrIcao, 'error');
        return;
    }

    const cruiseAltM = feetToMeters(cruiseAltFt || 0);
    const totalDistance = haversineDistance(depAirport.lat, depAirport.lng, arrAirport.lat, arrAirport.lng);

    // 显示加载状态
    showAnalysisLoading();

    // 先尝试调用后端 API
    let result = null;
    try {
        result = await analyzeFlightPlanViaAPI(depAirport, arrAirport, depTime, cruiseAltFt);
    } catch (e) {
        console.log('后端分析不可用，使用本地分析', e);
    }

    // 本地分析回退
    if (!result) {
        result = analyzeFlightPlanLocal(depAirport, arrAirport, depTime, cruiseAltM, totalDistance);
    }

    flightPlanAnalysisResult = result;

    // 绘制飞行路线
    drawFlightRoute(depAirport, arrAirport);

    // 高亮受影响 NOTAM 区域
    highlightAffectedNotams(result.affectedNotams);

    // 渲染结果
    renderAnalysisResult(result, depAirport, arrAirport, totalDistance, cruiseAltFt);

    showToast('分析完成: 发现 ' + result.affectedNotams.length + ' 条受影响 NOTAM', 'success');
}

/**
 * 通过后端 API 分析
 */
async function analyzeFlightPlanViaAPI(dep, arr, depTime, cruiseAltFt) {
    const resp = await fetch('/api/v1/flight-plan/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            departure: dep.icao,
            arrival: arr.icao,
            dep_lat: dep.lat,
            dep_lng: dep.lng,
            arr_lat: arr.lat,
            arr_lng: arr.lng,
            departure_time: depTime,
            cruise_altitude_ft: cruiseAltFt,
        }),
    });

    if (!resp.ok) throw new Error('API 返回 ' + resp.status);
    return await resp.json();
}

/**
 * 本地分析模式 - 使用已加载的 allFeatures 数据
 */
function analyzeFlightPlanLocal(dep, arr, depTime, cruiseAltM, totalDistance) {
    const affectedNotams = [];

    if (!allFeatures || allFeatures.length === 0) {
        return {
            affectedNotams: [],
            summary: { critical: 0, warning: 0, info: 0, total: 0 },
            totalDistance: totalDistance,
            departure: dep,
            arrival: arr,
            mode: 'local',
        };
    }

    // 解析起飞时间
    const depDate = depTime ? new Date(depTime) : new Date();

    allFeatures.forEach(function(feature) {
        const props = feature.properties || {};
        const geometry = feature.geometry;

        if (!geometry || geometry.type !== 'Polygon') return;

        // 计算质心
        const centroid = calcPolygonCentroid(feature);
        if (!centroid) return;

        // 计算质心到航线的垂直距离
        const distance = pointToRouteDistance(
            centroid.lat, centroid.lng,
            dep.lat, dep.lng,
            arr.lat, arr.lng
        );

        // 超出关注范围则跳过
        if (distance > DISTANCE_THRESHOLD_INFO) return;

        // 解析高度
        const altRange = parseNotamAltitude(props.altitude);
        let altitudeConflict = false;
        if (altRange && cruiseAltM > 0) {
            altitudeConflict = (cruiseAltM >= altRange.min && cruiseAltM <= altRange.max);
        }

        // 确定影响等级
        const notamType = props.type || 'other';
        const typeConfig = (typeof TYPE_CONFIG !== 'undefined') ? (TYPE_CONFIG[notamType] || TYPE_CONFIG.other) : { color: '#546E7A', name: '其他' };

        let impactLevel = 'info';
        // 危险/禁航区始终为严重
        if (notamType === 'danger' || notamType === 'prohibited') {
            impactLevel = 'critical';
        } else if (distance <= DISTANCE_THRESHOLD_CRITICAL) {
            // 50km 内根据类型决定
            if (notamType === 'restricted' || notamType === 'warning' || notamType === 'tfr') {
                impactLevel = 'critical';
            } else {
                impactLevel = 'warning';
            }
        } else if (distance <= DISTANCE_THRESHOLD_WARNING) {
            impactLevel = (notamType === 'restricted' || notamType === 'warning') ? 'warning' : 'info';
        }

        // 高度冲突提升等级
        if (altitudeConflict && impactLevel === 'warning') {
            impactLevel = 'critical';
        } else if (altitudeConflict && impactLevel === 'info') {
            impactLevel = 'warning';
        }

        // 判断是否在生效时间范围内
        let timeActive = true;
        if (props.start && props.end) {
            try {
                const notamStart = parseNotamDate(props.start);
                const notamEnd = parseNotamDate(props.end);
                if (notamStart && notamEnd) {
                    // 估算到达 NOTAM 附近的时间 (按总距离比例)
                    const progress = totalDistance > 0 ? distance / totalDistance : 0;
                    const flightDuration = Math.max(totalDistance / 500, 1); // 假设巡航速度 500km/h
                    const etaAtNotam = new Date(depDate.getTime() + progress * flightDuration * 3600000);
                    timeActive = (etaAtNotam >= notamStart && etaAtNotam <= notamEnd);
                }
            } catch (e) {
                timeActive = props.is_active !== false;
            }
        } else {
            timeActive = props.is_active !== false;
        }

        affectedNotams.push({
            code: props.notam_code || 'N/A',
            type: notamType,
            typeName: typeConfig.name,
            color: typeConfig.color,
            fir: props.fir || '',
            altitude: props.altitude || 'N/A',
            start: props.start || '',
            end: props.end || '',
            distance: Math.round(distance),
            altitudeConflict: altitudeConflict,
            impactLevel: impactLevel,
            timeActive: timeActive,
            description: buildImpactDescription(notamType, distance, altitudeConflict, timeActive),
            reroute: buildRerouteSuggestion(notamType, distance, altitudeConflict),
            centroid: centroid,
        });
    });

    // 按影响等级排序
    affectedNotams.sort(function(a, b) {
        const orderA = IMPACT_LEVEL_CONFIG[a.impactLevel] ? IMPACT_LEVEL_CONFIG[a.impactLevel].order : 3;
        const orderB = IMPACT_LEVEL_CONFIG[b.impactLevel] ? IMPACT_LEVEL_CONFIG[b.impactLevel].order : 3;
        if (orderA !== orderB) return orderA - orderB;
        return a.distance - b.distance;
    });

    // 汇总统计
    const summary = {
        critical: affectedNotams.filter(function(n) { return n.impactLevel === 'critical'; }).length,
        warning: affectedNotams.filter(function(n) { return n.impactLevel === 'warning'; }).length,
        info: affectedNotams.filter(function(n) { return n.impactLevel === 'info'; }).length,
        total: affectedNotams.length,
    };

    return {
        affectedNotams: affectedNotams,
        summary: summary,
        totalDistance: Math.round(totalDistance),
        departure: dep,
        arrival: arr,
        mode: 'local',
    };
}

/**
 * 解析 NOTAM 日期字符串
 * 格式如: "2026-08-18 06:00 UTC"
 */
function parseNotamDate(dateStr) {
    if (!dateStr) return null;
    try {
        const clean = dateStr.replace('UTC', '').trim();
        return new Date(clean + ' UTC');
    } catch (e) {
        return null;
    }
}

/**
 * 生成影响描述
 */
function buildImpactDescription(notamType, distance, altitudeConflict, timeActive) {
    const parts = [];

    if (notamType === 'danger') {
        parts.push('航线上存在临时危险区');
    } else if (notamType === 'prohibited') {
        parts.push('航线上存在禁航区，禁止穿越');
    } else if (notamType === 'restricted') {
        parts.push('航线附近有限制区');
    } else if (notamType === 'tfr') {
        parts.push('航线附近有临时飞行限制');
    } else if (notamType === 'warning') {
        parts.push('航线附近有警告区');
    }

    parts.push('偏航距离约 ' + Math.round(distance) + ' 公里');

    if (altitudeConflict) {
        parts.push('巡航高度与该区域高度范围冲突');
    }

    if (!timeActive) {
        parts.push('该区域可能在飞行时段外生效');
    }

    return parts.join('，') + '。';
}

/**
 * 生成改航建议
 */
function buildRerouteSuggestion(notamType, distance, altitudeConflict) {
    if (notamType === 'danger' || notamType === 'prohibited') {
        return '建议绕飞该区域，避开危险空域。可考虑向偏航 ' + Math.ceil((distance + 30) / 10) * 10 + ' 公里方向调整航路。';
    }
    if (notamType === 'restricted' && distance < DISTANCE_THRESHOLD_CRITICAL) {
        return '建议在到达该区域前向侧方偏航 30-50 公里绕飞，或申请穿越许可。';
    }
    if (notamType === 'tfr') {
        return '临时飞行限制区不可穿越，建议提前规划替代航路。';
    }
    if (altitudeConflict) {
        return '建议调整巡航高度避开该区域高度范围，或绕飞。';
    }
    if (distance < DISTANCE_THRESHOLD_WARNING) {
        return '关注该区域动态，必要时可小幅偏航规避。';
    }
    return null;
}

// ============================================================
// 地图渲染 - 飞行路线与高亮
// ============================================================

/**
 * 绘制飞行路线 (虚线)
 */
function drawFlightRoute(dep, arr) {
    if (!map) return;

    if (!flightPlanRouteLayer) {
        flightPlanRouteLayer = L.layerGroup().addTo(map);
    }
    flightPlanRouteLayer.clearLayers();

    // 起点标记
    const depMarker = L.marker([dep.lat, dep.lng], {
        icon: L.divIcon({
            className: 'flight-plan-marker',
            html: '<div style="background:#00E676;width:14px;height:14px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 8px rgba(0,230,118,0.6);"></div>',
            iconSize: [14, 14],
            iconAnchor: [7, 7],
        }),
    }).bindTooltip(escapeHtml(dep.icao) + ' (起飞)', { permanent: false });

    // 终点标记
    const arrMarker = L.marker([arr.lat, arr.lng], {
        icon: L.divIcon({
            className: 'flight-plan-marker',
            html: '<div style="background:#FF1744;width:14px;height:14px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 8px rgba(255,23,68,0.6);"></div>',
            iconSize: [14, 14],
            iconAnchor: [7, 7],
        }),
    }).bindTooltip(escapeHtml(arr.icao) + ' (降落)', { permanent: false });

    // 航线虚线
    const routeLine = L.polyline(
        [[dep.lat, dep.lng], [arr.lat, arr.lng]],
        {
            color: '#00E5FF',
            weight: 3,
            opacity: 0.8,
            dashArray: '10, 6',
        }
    ).bindTooltip('飞行路线: ' + escapeHtml(dep.icao) + ' → ' + escapeHtml(arr.icao), { sticky: true });

    flightPlanRouteLayer.addLayer(depMarker);
    flightPlanRouteLayer.addLayer(arrMarker);
    flightPlanRouteLayer.addLayer(routeLine);

    // 飞到航线视图
    map.fitBounds([[dep.lat, dep.lng], [arr.lat, arr.lng]], { padding: [60, 60] });
}

/**
 * 高亮受影响 NOTAM 区域
 */
function highlightAffectedNotams(affectedNotams) {
    if (!map) return;

    if (!flightPlanHighlightLayer) {
        flightPlanHighlightLayer = L.layerGroup().addTo(map);
    }
    flightPlanHighlightLayer.clearLayers();

    // 从 allFeatures 中找到对应的 NOTAM 并高亮
    affectedNotams.forEach(function(item) {
        const feature = allFeatures.find(function(f) {
            return (f.properties || {}).notam_code === item.code;
        });
        if (!feature || !feature.geometry || feature.geometry.type !== 'Polygon') return;

        const rings = feature.geometry.coordinates.map(function(ring) {
            return ring.map(function(coord) { return [coord[1], coord[0]]; });
        });

        const config = IMPACT_LEVEL_CONFIG[item.impactLevel] || IMPACT_LEVEL_CONFIG.info;

        // 高亮多边形
        const highlight = L.polygon(rings, {
            color: config.color,
            weight: 3,
            opacity: 1,
            fillColor: config.color,
            fillOpacity: 0.3,
            dashArray: '',
        });

        highlight.bindPopup(
            '<div style="min-width:200px;">' +
                '<div style="font-weight:700;font-size:14px;color:' + config.color + ';">' + escapeHtml(item.typeName) + ' - ' + escapeHtml(config.name) + '</div>' +
                '<div style="font-size:12px;margin-top:4px;">代号: <strong>' + escapeHtml(item.code) + '</strong></div>' +
                '<div style="font-size:12px;">偏航距离: ' + item.distance + ' km</div>' +
                (item.altitudeConflict ? '<div style="font-size:12px;color:#ff5252;">高度冲突!</div>' : '') +
            '</div>',
            { maxWidth: 280 }
        );

        flightPlanHighlightLayer.addLayer(highlight);
    });
}

/**
 * 清除飞行计划图层
 */
function clearFlightPlanLayers() {
    if (flightPlanRouteLayer) {
        map.removeLayer(flightPlanRouteLayer);
        flightPlanRouteLayer = null;
    }
    if (flightPlanHighlightLayer) {
        map.removeLayer(flightPlanHighlightLayer);
        flightPlanHighlightLayer = null;
    }
    flightPlanAnalysisResult = null;
}

// ============================================================
// 结果渲染
// ============================================================

/**
 * 显示分析加载状态
 */
function showAnalysisLoading() {
    const resultEl = document.getElementById('fp-result');
    if (!resultEl) return;
    resultEl.innerHTML =
        '<div class="analysis-loading">' +
            '<div style="margin-bottom:8px;">⏳ 正在分析航线受影响情况...</div>' +
        '</div>';
}

/**
 * 渲染分析结果
 */
function renderAnalysisResult(result, dep, arr, totalDistance, cruiseAltFt) {
    const resultEl = document.getElementById('fp-result');
    if (!resultEl) return;

    const s = result.summary;
    const modeLabel = result.mode === 'local' ? '本地分析' : 'API 分析';

    let html =
        '<div class="analysis-result">' +
            // 汇总统计
            '<div class="analysis-summary">' +
                '<div class="analysis-summary-card">' +
                    '<div class="analysis-summary-value">' + (result.totalDistance || Math.round(totalDistance)) + '</div>' +
                    '<div class="analysis-summary-label">航线距离(km)</div>' +
                '</div>' +
                '<div class="analysis-summary-card critical">' +
                    '<div class="analysis-summary-value">' + s.critical + '</div>' +
                    '<div class="analysis-summary-label">严重</div>' +
                '</div>' +
                '<div class="analysis-summary-card warning">' +
                    '<div class="analysis-summary-value">' + s.warning + '</div>' +
                    '<div class="analysis-summary-label">警告</div>' +
                '</div>' +
                '<div class="analysis-summary-card info">' +
                    '<div class="analysis-summary-value">' + s.info + '</div>' +
                    '<div class="analysis-summary-label">信息</div>' +
                '</div>' +
            '</div>' +
            '<div style="font-size:11px;color:var(--text-muted);margin-bottom:10px;">' +
                escapeHtml(dep.icao) + ' → ' + escapeHtml(arr.icao) + ' | 巡航高度: ' + (cruiseAltFt || 0) + ' ft | ' + modeLabel +
            '</div>';

    if (result.affectedNotams.length === 0) {
        html +=
            '<div class="analysis-empty">' +
                '<div style="font-size:32px;margin-bottom:8px;opacity:0.5;">✅</div>' +
                '<div>航线上未发现受影响的 NOTAM</div>' +
                '<div style="font-size:11px;margin-top:4px;">飞行计划安全</div>' +
            '</div>';
    } else {
        html += '<div class="impact-list">';
        result.affectedNotams.forEach(function(item) {
            const config = IMPACT_LEVEL_CONFIG[item.impactLevel] || IMPACT_LEVEL_CONFIG.info;
            html +=
                '<div class="impact-item impact-' + escapeHtml(item.impactLevel) + '">' +
                    '<div class="impact-item-header">' +
                        '<div>' +
                            '<span class="impact-code">' + escapeHtml(item.code) + '</span>' +
                            ' <span style="font-size:11px;color:var(--text-muted);">' + escapeHtml(item.typeName) + '</span>' +
                        '</div>' +
                        '<span class="impact-level-badge ' + escapeHtml(item.impactLevel) + '">' + escapeHtml(config.name) + '</span>' +
                    '</div>' +
                    '<div class="impact-detail-grid">' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">情报区:</span>' +
                            '<span class="impact-detail-value">' + escapeHtml(item.fir || 'N/A') + '</span>' +
                        '</div>' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">偏航距离:</span>' +
                            '<span class="impact-detail-value">' + item.distance + ' km</span>' +
                        '</div>' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">高度范围:</span>' +
                            '<span class="impact-detail-value">' + escapeHtml(item.altitude || 'N/A') + '</span>' +
                        '</div>' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">高度冲突:</span>' +
                            '<span class="impact-detail-value" style="color:' + (item.altitudeConflict ? '#ff5252' : '#00e676') + ';">' + (item.altitudeConflict ? '是' : '否') + '</span>' +
                        '</div>' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">生效时间:</span>' +
                            '<span class="impact-detail-value">' + escapeHtml(item.start || 'N/A') + ' ~ ' + escapeHtml(item.end || 'N/A') + '</span>' +
                        '</div>' +
                        '<div class="impact-detail-row">' +
                            '<span class="impact-detail-label">飞行时段:</span>' +
                            '<span class="impact-detail-value" style="color:' + (item.timeActive ? '#ff5252' : '#00e676') + ';">' + (item.timeActive ? '冲突' : '无冲突') + '</span>' +
                        '</div>' +
                    '</div>' +
                    '<div class="impact-description">' + escapeHtml(item.description) + '</div>' +
                    (item.reroute ? '<div class="reroute-suggestion"><div class="reroute-suggestion-title">改航建议</div>' + escapeHtml(item.reroute) + '</div>' : '') +
                '</div>';
        });
        html += '</div>';
    }

    // 导出按钮
    html +=
        '<div class="premium-divider"></div>' +
        '<div class="premium-btn-group">' +
            '<button class="premium-btn" onclick="clearFlightPlanLayers()">清除航线</button>' +
            '<button class="premium-btn primary" onclick="exportFlightPlanPDF()">导出 PDF</button>' +
        '</div>';

    html += '</div>';

    resultEl.innerHTML = html;
}

// ============================================================
// 导出 PDF
// ============================================================

/**
 * 导出飞行计划分析报告为 PDF (调用后端生成)
 */
async function exportFlightPlanPDF() {
    if (!flightPlanAnalysisResult) {
        showToast('请先执行分析', 'error');
        return;
    }

    const result = flightPlanAnalysisResult;
    const btn = event ? event.target : null;
    if (btn) {
        btn.disabled = true;
        btn.textContent = '生成中...';
    }

    // 先尝试调用后端 PDF 生成接口
    try {
        const resp = await fetch('/api/v1/flight-plan/pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                departure: result.departure.icao,
                arrival: result.arrival.icao,
                total_distance: result.totalDistance,
                summary: result.summary,
                affected_notams: result.affectedNotams,
            }),
        });

        if (resp.ok) {
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'flight-plan-' + result.departure.icao + '-' + result.arrival.icao + '.pdf';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            showToast('PDF 已生成', 'success');
            if (btn) { btn.disabled = false; btn.textContent = '导出 PDF'; }
            return;
        }
    } catch (e) {
        console.log('后端 PDF 生成不可用，使用本地导出');
    }

    // 本地回退: 导出为可打印 HTML (可由浏览器另存为 PDF)
    exportFlightPlanHTML(result);
    if (btn) { btn.disabled = false; btn.textContent = '导出 PDF'; }
}

/**
 * 本地导出为可打印 HTML
 */
function exportFlightPlanHTML(result) {
    const s = result.summary;
    const dateStr = new Date().toLocaleString('zh-CN');

    let notamsHtml = '';
    result.affectedNotams.forEach(function(item) {
        const config = IMPACT_LEVEL_CONFIG[item.impactLevel] || IMPACT_LEVEL_CONFIG.info;
        notamsHtml +=
            '<tr style="border-bottom:1px solid #ddd;">' +
                '<td style="padding:6px;font-weight:700;">' + escapeHtml(item.code) + '</td>' +
                '<td style="padding:6px;color:' + config.color + ';">' + escapeHtml(config.name) + '</td>' +
                '<td style="padding:6px;">' + escapeHtml(item.typeName) + '</td>' +
                '<td style="padding:6px;">' + item.distance + ' km</td>' +
                '<td style="padding:6px;">' + escapeHtml(item.altitude) + '</td>' +
                '<td style="padding:6px;color:' + (item.altitudeConflict ? 'red' : 'green') + ';">' + (item.altitudeConflict ? '是' : '否') + '</td>' +
                '<td style="padding:6px;font-size:11px;">' + escapeHtml(item.description) + '</td>' +
            '</tr>';
    });

    const html =
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">' +
        '<title>飞行计划分析报告 - ' + escapeHtml(result.departure.icao) + ' → ' + escapeHtml(result.arrival.icao) + '</title>' +
        '<style>' +
            'body{font-family:"Microsoft YaHei",sans-serif;background:#fff;color:#333;padding:30px;}' +
            'h1{color:#1a237e;border-bottom:2px solid #1a237e;padding-bottom:8px;}' +
            '.summary{display:flex;gap:20px;margin:16px 0;}' +
            '.summary-card{flex:1;text-align:center;padding:12px;background:#f5f5f5;border-radius:8px;}' +
            '.summary-value{font-size:24px;font-weight:700;}' +
            'table{width:100%;border-collapse:collapse;margin-top:12px;}' +
            'th{background:#1a237e;color:#fff;padding:8px;text-align:left;}' +
            '.footer{margin-top:20px;font-size:11px;color:#999;border-top:1px solid #eee;padding-top:8px;}' +
        '</style></head><body>' +
        '<h1>飞行计划分析报告</h1>' +
        '<div style="font-size:14px;margin-bottom:10px;">' +
            '起飞: <strong>' + escapeHtml(result.departure.icao) + ' ' + escapeHtml(result.departure.name) + '</strong><br>' +
            '降落: <strong>' + escapeHtml(result.arrival.icao) + ' ' + escapeHtml(result.arrival.name) + '</strong><br>' +
            '航线距离: ' + result.totalDistance + ' 公里 | 生成时间: ' + dateStr +
        '</div>' +
        '<div class="summary">' +
            '<div class="summary-card"><div class="summary-value" style="color:#d32f2f;">' + s.critical + '</div><div>严重</div></div>' +
            '<div class="summary-card"><div class="summary-value" style="color:#f57f17;">' + s.warning + '</div><div>警告</div></div>' +
            '<div class="summary-card"><div class="summary-value" style="color:#1565c0;">' + s.info + '</div><div>信息</div></div>' +
            '<div class="summary-card"><div class="summary-value">' + s.total + '</div><div>总计</div></div>' +
        '</div>';

    let fullHtml = html;
    if (result.affectedNotams.length > 0) {
        fullHtml +=
            '<h2>受影响 NOTAM 列表</h2>' +
            '<table><thead><tr>' +
                '<th>代号</th><th>等级</th><th>类型</th><th>偏航距离</th><th>高度范围</th><th>高度冲突</th><th>影响描述</th>' +
            '</tr></thead><tbody>' + notamsHtml + '</tbody></table>';
    } else {
        fullHtml += '<div style="padding:20px;text-align:center;background:#e8f5e9;border-radius:8px;color:#2e7d32;">航线上未发现受影响的 NOTAM，飞行计划安全。</div>';
    }

    fullHtml +=
        '<div class="footer">航空通 - NOTAM 航空通告系统 | 本报告由本地分析引擎生成 | 仅供参考</div>' +
        '<script>window.onload=function(){window.print();}</script>' +
        '</body></html>';

    const blob = new Blob([fullHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'flight-plan-' + result.departure.icao + '-' + result.arrival.icao + '.html';
    a.target = '_blank';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('已生成分析报告，可在浏览器中打印为 PDF', 'success');
}

// ============================================================
// 初始化飞行计划模块
// ============================================================
function initFlightPlan() {
    initAirportAutocomplete();

    // 设置默认起飞时间为当前时间
    const timeInput = document.getElementById('fp-time');
    if (timeInput && !timeInput.value) {
        const now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        timeInput.value = now.toISOString().slice(0, 16);
    }
}

// DOM 加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(initFlightPlan, 600);
});
