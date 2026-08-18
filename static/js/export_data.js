/**
 * 航空通 - 数据导出模块
 * 支持 CSV / JSON 格式导出 NOTAM 和发射计划
 */

/**
 * 导出 NOTAM 数据
 */
function exportNotamData(format) {
    if (!allFeatures || allFeatures.length === 0) {
        showStatus('error', '暂无数据可导出');
        return;
    }

    if (format === 'json') {
        const data = JSON.stringify({
            export_time: new Date().toISOString(),
            count: allFeatures.length,
            notams: allFeatures.map(f => ({
                notam_code: (f.properties || {}).notam_code || '',
                type: (f.properties || {}).type || '',
                fir: (f.properties || {}).fir || '',
                start: (f.properties || {}).start || '',
                end: (f.properties || {}).end || '',
                coordinates: f.geometry ? f.geometry.coordinates : null,
            })),
        }, null, 2);
        downloadFile(data, `notams_${getDateStr()}.json`, 'application/json');
    } else {
        const headers = ['NOTAM编号', '类型', '情报区', '生效时间', '失效时间', '坐标'];
        const rows = allFeatures.map(f => {
            const p = f.properties || {};
            const coords = f.geometry ? JSON.stringify(f.geometry.coordinates) : '';
            return [
                p.notam_code || '',
                p.type || '',
                p.fir || '',
                p.start || '',
                p.end || '',
                coords,
            ];
        });
        const csv = [headers, ...rows].map(r =>
            r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')
        ).join('\n');
        downloadFile('\ufeff' + csv, `notams_${getDateStr()}.csv`, 'text/csv;charset=utf-8');
    }
    showStatus('success', `已导出 ${allFeatures.length} 条 NOTAM 数据`);
}

/**
 * 导出发射计划数据
 */
function exportLaunchData(format) {
    if (!allLaunches || allLaunches.length === 0) {
        showStatus('error', '暂无发射数据可导出');
        return;
    }

    if (format === 'json') {
        const data = JSON.stringify({
            export_time: new Date().toISOString(),
            count: allLaunches.length,
            launches: allLaunches.map(f => ({
                name: (f.properties || {}).name || '',
                rocket: (f.properties || {}).rocket || '',
                rocket_cn: (f.properties || {}).rocket_cn || '',
                mission_name: (f.properties || {}).mission_name || '',
                country_code: (f.properties || {}).country_code || '',
                net: (f.properties || {}).net || '',
                net_display: (f.properties || {}).net_display || '',
                status: (f.properties || {}).status || '',
                location: (f.properties || {}).location_name || '',
                coordinates: f.geometry ? f.geometry.coordinates : null,
            })),
        }, null, 2);
        downloadFile(data, `launches_${getDateStr()}.json`, 'application/json');
    } else {
        const headers = ['任务名称', '火箭', '火箭(中文)', '任务', '国家', '发射时间', '显示时间', '状态', '发射场', '坐标'];
        const rows = allLaunches.map(f => {
            const p = f.properties || {};
            const coords = f.geometry ? `${f.geometry.coordinates[1]},${f.geometry.coordinates[0]}` : '';
            return [
                p.name || '',
                p.rocket || '',
                p.rocket_cn || '',
                p.mission_name || '',
                p.country_code || '',
                p.net || '',
                p.net_display || '',
                p.status || '',
                p.location_name || '',
                coords,
            ];
        });
        const csv = [headers, ...rows].map(r =>
            r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')
        ).join('\n');
        downloadFile('\ufeff' + csv, `launches_${getDateStr()}.csv`, 'text/csv;charset=utf-8');
    }
    showStatus('success', `已导出 ${allLaunches.length} 条发射数据`);
}

/**
 * 下载文件工具
 */
function downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * 获取日期字符串
 */
function getDateStr() {
    const d = new Date();
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
}
