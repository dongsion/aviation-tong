/**
 * 航空通 - 浏览器推送通知模块
 * 新发射任务或即将发射时弹窗提醒
 */

// ============================================================
// 全局状态
// ============================================================
let notificationPermission = 'default';
let notifiedLaunchSlugs = new Set();
let launchNotificationTimer = null;

// ============================================================
// 初始化
// ============================================================
function initNotifications() {
    if (!('Notification' in window)) {
        console.log('浏览器不支持通知功能');
        return;
    }
    notificationPermission = Notification.permission;

    // 每 10 分钟检查一次新发射任务
    launchNotificationTimer = setInterval(checkLaunchNotifications, 10 * 60 * 1000);
}

/**
 * 请求通知权限
 */
function requestNotificationPermission() {
    if (!('Notification' in window)) {
        showStatus('error', '浏览器不支持通知功能');
        return;
    }
    Notification.requestPermission().then(permission => {
        notificationPermission = permission;
        if (permission === 'granted') {
            showStatus('success', '通知已开启');
            new Notification('航空通', {
                body: '您将收到新发射任务和即将发射的通知',
                icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">✈️</text></svg>',
            });
        } else {
            showStatus('error', '通知权限被拒绝');
        }
    });
}

/**
 * 检查发射通知 — 新发射任务 + 即将发射提醒
 */
function checkLaunchNotifications() {
    if (notificationPermission !== 'granted') return;

    const now = new Date();

    for (const launch of allLaunches) {
        const props = launch.properties || {};
        const slug = props.slug || props.name || '';

        // 新发射任务通知
        if (!notifiedLaunchSlugs.has(slug)) {
            notifiedLaunchSlugs.add(slug);
            // 只通知最近 2 小时内新增的
            if (props.net) {
                const launchTime = new Date(props.net);
                const hoursUntil = (launchTime - now) / 3600000;
                if (hoursUntil > 0 && hoursUntil < 72) {
                    new Notification('🚀 新发射任务', {
                        body: `${props.rocket_cn || props.rocket || 'Unknown'}\n${props.net_display || props.net || ''}\n${props.location_cn || props.location_name || ''}`,
                        icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🚀</text></svg>',
                        tag: slug,
                    });
                }
            }
        }

        // 即将发射提醒（1小时、10分钟）
        if (props.net) {
            const launchTime = new Date(props.net);
            const minsUntil = (launchTime - now) / 60000;

            if (minsUntil > 55 && minsUntil < 65 && !notifiedLaunchSlugs.has(slug + '_1h')) {
                notifiedLaunchSlugs.add(slug + '_1h');
                new Notification('⏰ 发射倒计时 1 小时', {
                    body: `${props.rocket_cn || props.rocket}\n${props.mission_name || ''}\n即将发射！`,
                    icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">⏰</text></svg>',
                    tag: slug + '_1h',
                });
            } else if (minsUntil > 5 && minsUntil < 15 && !notifiedLaunchSlugs.has(slug + '_10m')) {
                notifiedLaunchSlugs.add(slug + '_10m');
                new Notification('🔥 即将发射！10 分钟', {
                    body: `${props.rocket_cn || props.rocket}\n${props.location_cn || ''}\n发射窗口即将开启！`,
                    icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🔥</text></svg>',
                    tag: slug + '_10m',
                });
            }
        }
    }
}
