<div align="center">

# ✈️ 航空通

### NOTAM 航空通告实时可视化系统

[![Website](https://img.shields.io/badge/website-online-brightgreen)](https://你的用户名.github.io/航空通/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB)](https://www.python.org/)
[![Updates](https://img.shields.io/badge/自动更新-每30分钟-orange)](.github/workflows/update-data.yml)

</div>

## 项目简介

**航空通** 是一个 NOTAM（Notice to Air Missions）航空通告 + 火箭发射计划实时可视化系统。它从 FAA 等航空数据源抓取 NOTAM 通告，解析其中的坐标信息；同时从 Launch Library 2 获取全球即将发射的火箭/卫星计划，在交互式地图上以不同颜色标注各类航空限制区域和发射场位置，并支持自动实时更新。

灵感来源: [Joey0609/notams](https://github.com/Joey0609/notams) 项目

## 功能特性

- **实时数据更新** — 通过 GitHub Actions 每 30 分钟自动抓取最新 NOTAM 数据和火箭发射计划
- **火箭发射计划** — 全球即将发射的火箭/卫星在地图上以 🚀 标记显示，含代号、名称、发射时间和实时倒计时
- **区域颜色分类** — 不同类型的航空区域以不同颜色显示，附详细图例说明
- **交互式地图** — 基于 Leaflet 的暗色主题地图，支持缩放、平移、点击查看详情
- **类型筛选** — 点击图例可按类型筛选显示区域或发射计划
- **NOTAM + 发射列表** — 侧边栏展示所有通告和发射计划列表，点击可定位到地图位置
- **详细信息弹窗** — 点击区域或发射标记显示完整信息
- **自动过期过滤** — 自动过滤已失效的 NOTAM
- **GitHub Pages 部署** — 一键部署到 GitHub Pages，免服务器

## 颜色说明

### NOTAM 航空限制区域

| 颜色 | 类型 | 说明 |
|------|------|------|
| 🔴 红色 `#FF1744` | 临时危险区 | 火箭发射、导弹试射等临时危险区域 |
| 🟠 橙色 `#FF6D00` | 限制区 | 军事活动限制区域 |
| 🟡 黄色 `#FFD600` | 警告区 | 潜在飞行危险警告区域 |
| 🟣 紫色 `#AA00FF` | 禁航区 | 完全禁止飞行的区域 |
| 🔵 蓝色 `#2962FF` | 临时飞行限制 | 临时飞行限制 (TFR) |
| 🟢 绿色 `#00C853` | 航路变更 | 航路调整或导航设施变更 |
| ⚫ 灰色 `#546E7A` | 其他通告 | 其他类型航空通告 |

### 🚀 火箭/卫星发射计划标记

| 颜色 | 状态 | 说明 |
|------|------|------|
| 🟢 绿色 | 已确认发射 | 当前 T-0 已确认，准许发射 |
| 🟡 橙黄 | 时间待定 | 发射时间尚未最终确定 (TBD) |
| 🔵 蓝色 | 发射成功 | 已成功发射并入轨 |
| 🔴 红色 | 已取消 | 发射已取消或推迟 |

## 快速开始

### 1. 创建 GitHub 仓库

1. 登录 [GitHub](https://github.com)，点击 **New** 创建新仓库
2. 仓库名称填入 `航空通`
3. 选择 **Public**（公开）
4. 勾选 **Add a README file**
5. 点击 **Create repository**

### 2. 上传项目代码

将本项目所有文件上传到仓库，或使用 Git 克隆推送：

```bash
git clone https://github.com/你的用户名/航空通.git
cd 航空通
# 将项目文件复制到此目录
git add .
git commit -m "初始化航空通项目"
git push origin main
```

### 3. 启用 GitHub Pages

1. 进入仓库 **Settings** → **Pages**
2. Source 选择 **GitHub Actions**
3. 等待工作流自动运行后，网站将发布在 `https://你的用户名.github.io/航空通/`

### 4. 配置自动更新（可选）

项目已包含 GitHub Actions 工作流，会自动每 30 分钟更新数据。

如需使用 FAA NOTAM API v1（推荐，数据更完整）：

1. 在 [FAA Developer Portal](https://api.faa.gov/) 注册并获取 API Key
2. 在仓库 **Settings** → **Secrets and variables** → **Actions** 中添加 Secret：
   - 名称: `FAA_API_KEY`
   - 值: 你的 API Key
3. 工作流会自动使用该密钥获取数据

> 未配置 API Key 时，项目会自动回退到示例数据展示界面功能。

## 项目结构

```
航空通/
├── index.html                  # 主页面
├── main.py                     # 数据抓取与处理主程序(NOTAM + 发射计划)
├── config.ini                  # 配置文件
├── requirements.txt            # Python 依赖
├── data/
│   ├── notams.json             # NOTAM GeoJSON 数据
│   ├── launches.json           # 火箭发射计划 GeoJSON 数据
│   └── legend.json             # 图例数据
├── static/
│   ├── css/style.css           # 全局样式(含发射标记样式)
│   ├── js/map.js               # 地图渲染逻辑(NOTAM + 发射)
│   └── leaflet/                # Leaflet 地图库(本地)
├── fetch/
│   ├── __init__.py
│   └── sources/
│       ├── base.py             # 数据源基类
│       ├── common.py           # 通用解析工具(坐标/时间/分类)
│       ├── manager.py          # 数据源管理器
│       ├── faa/                # FAA NOTAM 数据源
│       │   ├── __init__.py
│       │   └── client.py       # FAA API 客户端(v1 + Search)
│       └── launches/           # 发射计划数据源
│           ├── __init__.py
│           └── client.py       # Launch Library 2 API 客户端
├── .github/workflows/
│   └── update-data.yml         # GitHub Actions 自动更新工作流
├── README.md                   # 项目文档(本文件)
└── LICENSE                     # MIT 许可证
```

## 配置说明

编辑 `config.ini` 可调整以下内容：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `[DATA_SOURCES] enabled` | 数据源选择 | `faa` |
| `[ICAO] codes` | 飞行情报区代码列表 | 中国八大情报区+周边 |
| `[FAA] api_key` | FAA API 密钥(可选) | 空 |
| `[FAA] timeout` | 请求超时(秒) | `15` |
| `[FAA] retries` | 重试次数 | `3` |
| `[COLORS] *` | 各类型颜色配置 | 见配置文件 |
| `[FILTER] *` | 坐标范围过滤 | 东经60°~180° |
| `[UPDATE] interval_minutes` | 更新间隔(分钟) | `30` |

## 数据源

当前支持以下数据源：

- **Launch Library 2 API** — 免费社区维护的全球航天发射数据库，无需 API Key [$TRAE_REF](https://ll.thespacedevs.com/2.2.0/launch/upcoming/)
- **FAA NOTAM API v1** — FAA 最新 REST API，需 API Key（推荐）
- **FAA NOTAM Search** — 传统 FAA 搜索接口，无需认证（备选）

发射计划数据包含：火箭名称、任务名称、任务类型、轨道、发射时间、实时倒计时、发射服务商、发射场坐标和详情。

如需添加更多数据源（如 DAIP、DINS、ICAO），在 `fetch/sources/` 下实现 `DataSource.fetch()` 并在 `manager.py` 中注册即可。

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 抓取并处理数据
python main.py

# 启动本地预览服务器
python -m http.server 8080

# 浏览器访问 http://localhost:8080
```

## 技术栈

- **后端**: Python 3.11+, Requests
- **前端**: HTML5, CSS3, JavaScript (ES6+)
- **地图**: Leaflet 1.9.4 + CartoDB Dark Matter 瓦片
- **部署**: GitHub Pages + GitHub Actions
- **数据格式**: GeoJSON

## ⚠️ 免责声明

本项目仅供学习和参考使用。NOTAM 数据可能存在延迟或不完整，**不应作为唯一的飞行前简报来源**。正式飞行前，请务必通过官方渠道获取最新的 NOTAM 简报。

本项目不得用于非法用途。请自觉维护国家安全，对于非火箭航警做到不分析、不传播。

## 开源许可

本项目采用 [MIT License](LICENSE) 开源协议。

使用的第三方库：
- [Leaflet](https://leafletjs.com/) v1.9.4 — BSD 2-Clause License（许可证见 `static/leaflet/LICENSE`）

## 贡献

欢迎提交 Issue 或 Pull Request 帮助完善功能和修复问题！
