# -*- coding: utf-8 -*-
"""
卫星过境预测器 (premium/satellite_pass.py)

功能概述:
    根据卫星 TLE (Two-Line Element) 轨道根数和地面观察者位置，
    预测未来若干天内卫星过境 (可见飞越) 的时间、最大仰角、持续时间和方向。

设计要点:
    - 全部使用 Python 标准库，不依赖 sgp4 / numpy / scipy
    - 使用简化开普勒轨道力学 (Simplified Keplerian Propagation):
        1. 解析 TLE 提取轨道六根数 (a, e, i, Ω, ω, M)
        2. 用平均运动推进平近点角 M(t) = M₀ + n·Δt
        3. 牛顿-迭代法求解开普勒方程  E - e·sinE = M
        4. 由偏近点角 E 计算真近点角 ν 和地心距 r
        5. PQW → ECI 坐标变换 (三次旋转)
        6. 加入 J2 长期摄动修正 (RAAN 和近地点幅角长期漂移)
        7. ECI → ECEF (基于格林尼治平恒星时 GMST)
        8. ECEF → 站心 SEZ (南-东-天) 坐标变换
        9. 计算仰角 (elevation) 和方位角 (azimuth)
    - 过境检测: 仰角从负变正为升起，从正变负为落下
    - 支持从项目 data/satellites.json 读取已缓存的卫星数据批量预测

精度说明:
    本简化模型不包含大气阻力、周期性摄动等高阶项，适用于 LEO 卫星
    数天内的过境预测，时间误差通常在 1-2 分钟以内。
    如需高精度轨道计算，建议使用 sgp4 库。

Python 3.11+ 兼容
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
#  物理常数 (SI / 天文单位)
# ============================================================

# 地球赤道半径 (km)
EARTH_RADIUS_KM = 6378.137

# 地球引力常数 μ = G·M (km³/s²)
EARTH_MU = 398600.4418

# 地球扁率 J2 项
EARTH_J2 = 0.0010826167

# 地球自转角速度 (rad/s)
EARTH_OMEGA = 7.2921151467e-5

# 一天的秒数
SECONDS_PER_DAY = 86400.0

# 弧度 → 度
RAD2DEG = 180.0 / math.pi
DEG2RAD = math.pi / 180.0


# ============================================================
#  TLE 解析
# ============================================================

@dataclass
class OrbitalElements:
    """
    轨道六根数 (从 TLE 解析)

    属性:
        epoch:           历元时间 (UTC datetime)
        inclination:     轨道倾角 (度)
        raan:            升交点赤经 RAAN (度)
        eccentricity:    偏心率 (无量纲)
        arg_perigee:     近地点幅角 (度)
        mean_anomaly:    平近点角 (度)
        mean_motion:     平均运动 (转/天)
        norad_id:        NORAD 编号
        bstar:           大气阻力系数 BSTAR (简化模型中未使用)
        semi_major_axis:  半长轴 (km, 由平均运动计算)
    """
    epoch: datetime
    inclination: float
    raan: float
    eccentricity: float
    arg_perigee: float
    mean_anomaly: float
    mean_motion: float
    norad_id: str = ""
    bstar: float = 0.0
    semi_major_axis: float = 0.0

    def __post_init__(self):
        """计算半长轴"""
        if self.mean_motion > 0 and self.semi_major_axis == 0.0:
            # n (rad/s) = mean_motion * 2π / 86400
            n_rad_s = self.mean_motion * 2.0 * math.pi / SECONDS_PER_DAY
            # a = (μ / n²)^(1/3)
            self.semi_major_axis = (EARTH_MU / (n_rad_s ** 2)) ** (1.0 / 3.0)

    @property
    def orbital_period_minutes(self) -> float:
        """轨道周期 (分钟)"""
        if self.mean_motion > 0:
            return SECONDS_PER_DAY / self.mean_motion / 60.0
        return 0.0


def parse_tle(tle_line1: str, tle_line2: str) -> OrbitalElements:
    """
    解析 TLE (Two-Line Element) 两行轨道根数

    TLE 格式示例::

        1 25544U 98067A   26229.79251732  .00005860  00000+0  11255-3 0  9992
        2 25544  51.6334 355.1923 0007534  57.5442 302.6274 15.49477092581307

    参数:
        tle_line1: TLE 第一行
        tle_line2: TLE 第二行

    返回:
        OrbitalElements 轨道根数对象

    异常:
        ValueError: TLE 格式无效
    """
    line1 = tle_line1.strip()
    line2 = tle_line2.strip()

    # 基本格式校验
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        raise ValueError("TLE 格式无效: 第一行须以 '1 ' 开头, 第二行须以 '2 ' 开头")

    # --- 解析第一行 ---
    parts1 = line1.split()
    if len(parts1) < 4:
        raise ValueError(f"TLE 第一行字段不足: {line1}")

    # NORAD 编号 + 分类字母 (如 "25544U")
    norad_raw = parts1[1]
    norad_id = ""
    for c in norad_raw:
        if c.isdigit():
            norad_id += c
        else:
            break

    # 历元字符串 (如 "26229.79251732")
    epoch_str = parts1[3]

    # BSTAR 阻力系数 (如 "11255-3" → 0.11255e-3)
    bstar = 0.0
    if len(parts1) >= 7:
        bstar = _parse_scientific_notation(parts1[6])

    # 解析历元
    epoch = _parse_tle_epoch(epoch_str)

    # --- 解析第二行 ---
    parts2 = line2.split()
    if len(parts2) < 8:
        raise ValueError(f"TLE 第二行字段不足: {line2}")

    inclination = float(parts2[2])
    raan = float(parts2[3])
    # 偏心率: TLE 中省略了 "0." 前缀, 如 "0007534" → 0.0007534
    eccentricity = float("0." + parts2[4])
    arg_perigee = float(parts2[5])
    mean_anomaly = float(parts2[6])
    mean_motion = float(parts2[7])

    return OrbitalElements(
        epoch=epoch,
        inclination=inclination,
        raan=raan,
        eccentricity=eccentricity,
        arg_perigee=arg_perigee,
        mean_anomaly=mean_anomaly,
        mean_motion=mean_motion,
        norad_id=norad_id,
        bstar=bstar,
    )


def _parse_tle_epoch(epoch_str: str) -> datetime:
    """
    解析 TLE 历元字符串

    格式: "YYDDD.DDDDDDD" (两位年 + 年积日)

    年份规则: 57-99 → 1957-1999, 00-56 → 2000-2056

    参数:
        epoch_str: 历元字符串 (如 "26229.79251732")

    返回:
        UTC datetime
    """
    year_str = epoch_str[:2]
    day_str = epoch_str[2:]

    year = int(year_str)
    if year < 57:
        year += 2000
    else:
        year += 1900

    day_of_year = float(day_str)

    # 年积日转日期: 1月1日 00:00 UTC + (day_of_year - 1) 天
    jan1 = datetime(year, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    epoch = jan1 + timedelta(days=day_of_year - 1)

    return epoch


def _parse_scientific_notation(s: str) -> float:
    """
    解析 TLE 中的科学计数法 (如 "11255-3" → 0.11255e-3)

    TLE 使用紧凑格式: 尾数和指数之间没有 'e'，指数直接跟在尾数后面。
    正指数前有 '+'，负指数前有 '-'。
    """
    s = s.strip()
    if not s:
        return 0.0

    # 尝试标准 float 解析
    try:
        return float(s)
    except ValueError:
        pass

    # 查找 +/- 分隔符 (科学计数法指数)
    for i in range(len(s) - 1, 0, -1):
        if s[i] in "+-":
            mantissa_str = s[:i]
            exp_str = s[i:]
            try:
                mantissa = float(mantissa_str)
                exp = int(exp_str)
                return mantissa * (10.0 ** exp)
            except ValueError:
                continue

    return 0.0


# ============================================================
#  轨道传播 (简化开普勒模型)
# ============================================================

class KeplerPropagator:
    """
    简化开普勒轨道传播器

    使用两体开普勒运动 + J2 长期摄动修正，
    从 TLE 历元开始传播卫星位置。

    用法::

        elements = parse_tle(tle1, tle2)
        prop = KeplerPropagator(elements)
        lat, lon, alt, elev, azim = prop.get_subpoint_and_look_angles(
            observer_lat=39.9, observer_lon=116.4, time=datetime.utcnow()
        )
    """

    def __init__(self, elements: OrbitalElements):
        """
        初始化传播器

        参数:
            elements: 轨道根数
        """
        self.elements = elements

        # 预计算常量 (弧度)
        self._i_rad = math.radians(elements.inclination)
        self._raan_rad = math.radians(elements.raan)
        self._omega_rad = math.radians(elements.arg_perigee)
        self._e = elements.eccentricity

        # 平均运动 (rad/s)
        self._n_rad_s = elements.mean_motion * 2.0 * math.pi / SECONDS_PER_DAY

        # 半长轴和半通径
        self._a = elements.semi_major_axis  # km
        self._p = self._a * (1 - self._e ** 2)  # 半通径 p = a(1-e²)

        # J2 长期摄动速率 (rad/s)
        # dΩ/dt = -3/2 · J2 · (R_E/p)² · n · cos(i)
        self._raan_rate = (
            -1.5 * EARTH_J2 * (EARTH_RADIUS_KM / self._p) ** 2
            * self._n_rad_s * math.cos(self._i_rad)
        )
        # dω/dt = 3/4 · J2 · (R_E/p)² · n · (5cos²(i) - 1)
        self._omega_rate = (
            0.75 * EARTH_J2 * (EARTH_RADIUS_KM / self._p) ** 2
            * self._n_rad_s * (5 * math.cos(self._i_rad) ** 2 - 1)
        )

        # J2000 历元 (2000-01-01 12:00 UTC)
        self._j2000 = datetime(2000, 1, 1, 12, 0, 0, 0, tzinfo=timezone.utc)

    def propagate(self, time: datetime) -> Tuple[float, float, float]:
        """
        传播到指定时间，返回卫星在地心固定坐标系 (ECEF) 中的位置

        参数:
            time: 目标时间 (UTC)

        返回:
            (x_ecef, y_ecef, z_ecef) — 单位 km
        """
        # 时间偏移 (秒)
        dt = (time - self.elements.epoch).total_seconds()

        # --- 1. 推进平近点角 ---
        M0 = math.radians(self.elements.mean_anomaly)
        M = M0 + self._n_rad_s * dt

        # --- 2. J2 长期摄动修正 (RAAN 和近地点幅角) ---
        raan = self._raan_rad + self._raan_rate * dt
        omega = self._omega_rad + self._omega_rate * dt

        # --- 3. 求解开普勒方程: E - e·sinE = M ---
        E = self._solve_kepler(M, self._e)

        # --- 4. 计算真近点角 ν ---
        nu = self._eccentric_to_true_anomaly(E, self._e)

        # --- 5. 计算地心距 r ---
        r = self._a * (1 - self._e * math.cos(E))

        # --- 6. PQW 轨道平面坐标 ---
        x_pqw = r * math.cos(nu)
        y_pqw = r * math.sin(nu)

        # --- 7. PQW → ECI 坐标变换 ---
        x_eci, y_eci, z_eci = self._pqw_to_eci(
            x_pqw, y_pqw, raan, self._i_rad, omega
        )

        # --- 8. ECI → ECEF 坐标变换 (基于 GMST) ---
        theta_g = self._gmst(time)
        x_ecef = math.cos(theta_g) * x_eci + math.sin(theta_g) * y_eci
        y_ecef = -math.sin(theta_g) * x_eci + math.cos(theta_g) * y_eci
        z_ecef = z_eci

        return (x_ecef, y_ecef, z_ecef)

    def get_subpoint(self, time: datetime) -> Tuple[float, float, float]:
        """
        计算卫星的星下点 (地心纬度, 经度, 高度)

        参数:
            time: UTC 时间

        返回:
            (latitude_deg, longitude_deg, altitude_km)
        """
        x, y, z = self.propagate(time)

        # 地心距离
        r = math.sqrt(x * x + y * y + z * z)

        # 纬度 (地心纬度，近似为地理纬度)
        lat = math.degrees(math.asin(z / r)) if r > 0 else 0.0

        # 经度
        lon = math.degrees(math.atan2(y, x))

        # 高度
        alt = r - EARTH_RADIUS_KM

        return (lat, lon, alt)

    def get_look_angles(self,
                        observer_lat: float,
                        observer_lon: float,
                        observer_alt: float,
                        time: datetime) -> Tuple[float, float, float]:
        """
        计算从观察者位置看卫星的仰角、方位角和距离

        参数:
            observer_lat: 观察者纬度 (度)
            observer_lon: 观察者经度 (度)
            observer_alt: 观察者海拔高度 (km, 默认 0)
            time:         UTC 时间

        返回:
            (elevation_deg, azimuth_deg, slant_range_km)
        """
        # 卫星 ECEF 坐标
        sat_x, sat_y, sat_z = self.propagate(time)

        # 观察者 ECEF 坐标
        lat_rad = math.radians(observer_lat)
        lon_rad = math.radians(observer_lon)
        obs_r = EARTH_RADIUS_KM + observer_alt
        obs_x = obs_r * math.cos(lat_rad) * math.cos(lon_rad)
        obs_y = obs_r * math.cos(lat_rad) * math.sin(lon_rad)
        obs_z = obs_r * math.sin(lat_rad)

        # 相对位置 (ECEF)
        rx = sat_x - obs_x
        ry = sat_y - obs_y
        rz = sat_z - obs_z

        # ECEF → SEZ (南-东-天) 变换
        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        sin_lon = math.sin(lon_rad)
        cos_lon = math.cos(lon_rad)

        # SEZ 坐标
        s = sin_lat * cos_lon * rx + sin_lat * sin_lon * ry - cos_lat * rz
        e = -sin_lon * rx + cos_lon * ry
        z = cos_lat * cos_lon * rx + cos_lat * sin_lon * ry + sin_lat * rz

        # 仰角
        range_km = math.sqrt(s * s + e * e + z * z)
        if range_km < 1e-6:
            return (90.0, 0.0, 0.0)

        elevation = math.degrees(math.asin(z / range_km))

        # 方位角 (正北为 0°, 顺时针)
        azimuth = math.degrees(math.atan2(e, -s))
        if azimuth < 0:
            azimuth += 360.0

        return (elevation, azimuth, range_km)

    def get_subpoint_and_look_angles(self,
                                      observer_lat: float,
                                      observer_lon: float,
                                      time: datetime,
                                      observer_alt: float = 0.0
                                      ) -> Tuple[float, float, float, float, float]:
        """
        同时计算星下点和仰角/方位角 (便捷方法)

        返回:
            (sat_lat, sat_lon, sat_alt_km, elevation_deg, azimuth_deg)
        """
        sat_lat, sat_lon, sat_alt = self.get_subpoint(time)
        elev, azim, _ = self.get_look_angles(
            observer_lat, observer_lon, observer_alt, time
        )
        return (sat_lat, sat_lon, sat_alt, elev, azim)

    # ----------------------------------------------------------
    #  内部计算方法
    # ----------------------------------------------------------

    @staticmethod
    def _solve_kepler(M: float, e: float,
                      tolerance: float = 1e-12,
                      max_iter: int = 80) -> float:
        """
        牛顿-迭代法求解开普勒方程: E - e·sin(E) = M

        参数:
            M: 平近点角 (弧度)
            e: 偏心率
            tolerance: 收敛容差
            max_iter: 最大迭代次数

        返回:
            偏近点角 E (弧度)
        """
        # 归一化 M 到 [0, 2π)
        M = M % (2.0 * math.pi)
        if M < 0:
            M += 2.0 * math.pi

        # 初始猜测: E₀ = M (适用于小偏心率)
        E = M
        if e > 0.8:
            # 大偏心率时使用更好的初始值
            E = math.pi

        for _ in range(max_iter):
            f = E - e * math.sin(E) - M
            fp = 1.0 - e * math.cos(E)
            delta = f / fp
            E -= delta
            if abs(delta) < tolerance:
                break

        return E

    @staticmethod
    def _eccentric_to_true_anomaly(E: float, e: float) -> float:
        """
        由偏近点角 E 计算真近点角 ν

        使用公式: tan(ν/2) = √((1+e)/(1-e)) · tan(E/2)

        参数:
            E: 偏近点角 (弧度)
            e: 偏心率

        返回:
            真近点角 ν (弧度)
        """
        return 2.0 * math.atan2(
            math.sqrt(1.0 + e) * math.sin(E / 2.0),
            math.sqrt(1.0 - e) * math.cos(E / 2.0)
        )

    @staticmethod
    def _pqw_to_eci(x_pqw: float, y_pqw: float,
                    raan: float, inc: float, omega: float
                    ) -> Tuple[float, float, float]:
        """
        PQW 轨道平面坐标 → ECI 地心惯性坐标

        三次旋转: R_z(-Ω) · R_x(-i) · R_z(-ω)

        参数:
            x_pqw, y_pqw: PQW 坐标 (km)
            raan: 升交点赤经 (弧度)
            inc:  轨道倾角 (弧度)
            omega: 近地点幅角 (弧度)

        返回:
            (x_eci, y_eci, z_eci) — ECI 坐标 (km)
        """
        cos_O = math.cos(raan)
        sin_O = math.sin(raan)
        cos_w = math.cos(omega)
        sin_w = math.sin(omega)
        cos_i = math.cos(inc)
        sin_i = math.sin(inc)

        # 旋转矩阵展开 (R_z(-Ω) · R_x(-i) · R_z(-ω))
        r11 = cos_O * cos_w - sin_O * sin_w * cos_i
        r12 = -cos_O * sin_w - sin_O * cos_w * cos_i
        r21 = sin_O * cos_w + cos_O * sin_w * cos_i
        r22 = -sin_O * sin_w + cos_O * cos_w * cos_i
        r31 = sin_i * sin_w
        r32 = sin_i * cos_w

        x_eci = r11 * x_pqw + r12 * y_pqw
        y_eci = r21 * x_pqw + r22 * y_pqw
        z_eci = r31 * x_pqw + r32 * y_pqw

        return (x_eci, y_eci, z_eci)

    def _gmst(self, time: datetime) -> float:
        """
        计算格林尼治平恒星时 (Greenwich Mean Sidereal Time)

        使用简化公式:
            GMST = 280.46061837° + 360.98564736629° × d
        其中 d 为 J2000 历元起算的天数。

        参数:
            time: UTC 时间

        返回:
            GMST (弧度, 归一化到 [0, 2π))
        """
        # 天数差 (J2000 起算)
        d = (time - self._j2000).total_seconds() / SECONDS_PER_DAY

        # GMST (度)
        gmst_deg = 280.46061837 + 360.98564736629 * d

        # 转弧度并归一化
        gmst_rad = math.radians(gmst_deg) % (2.0 * math.pi)
        if gmst_rad < 0:
            gmst_rad += 2.0 * math.pi

        return gmst_rad


# ============================================================
#  过境信息数据结构
# ============================================================

@dataclass
class PassInfo:
    """
    单次卫星过境信息

    属性:
        satellite_name: 卫星名称
        norad_id:       NORAD 编号
        start_time:     过境开始时间 (UTC datetime, 仰角升起时刻)
        end_time:       过境结束时间 (UTC datetime, 仰角落下时刻)
        max_elevation:  最大仰角 (度)
        max_elevation_time: 最大仰角时刻 (UTC datetime)
        duration_seconds: 过境持续时间 (秒)
        direction:      过境方向 (中文, 如 "北→南" 或 "南→北")
        start_azimuth:  起始方位角 (度)
        max_azimuth:    最大仰角处方位角 (度)
        end_azimuth:    结束方位角 (度)
        slant_range_km: 最大仰角处斜距 (km)
    """
    satellite_name: str
    norad_id: str = ""
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_elevation: float = 0.0
    max_elevation_time: Optional[datetime] = None
    duration_seconds: float = 0.0
    direction: str = ""
    start_azimuth: float = 0.0
    max_azimuth: float = 0.0
    end_azimuth: float = 0.0
    slant_range_km: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典 (用于 JSON 序列化)"""
        def fmt_dt(dt: Optional[datetime]) -> Optional[str]:
            if dt is None:
                return None
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

        return {
            "satellite_name": self.satellite_name,
            "norad_id": self.norad_id,
            "start_time": fmt_dt(self.start_time),
            "end_time": fmt_dt(self.end_time),
            "max_elevation": round(self.max_elevation, 1),
            "max_elevation_time": fmt_dt(self.max_elevation_time),
            "duration": round(self.duration_seconds, 0),
            "duration_str": self._format_duration(),
            "direction": self.direction,
            "start_azimuth": round(self.start_azimuth, 1),
            "max_azimuth": round(self.max_azimuth, 1),
            "end_azimuth": round(self.end_azimuth, 1),
            "slant_range_km": round(self.slant_range_km, 1),
        }

    def _format_duration(self) -> str:
        """格式化持续时间为可读字符串"""
        minutes = int(self.duration_seconds // 60)
        seconds = int(self.duration_seconds % 60)
        return f"{minutes}分{seconds}秒"


# ============================================================
#  卫星过境预测器
# ============================================================

class SatellitePassPredictor:
    """
    卫星过境预测器

    根据卫星 TLE 和观察者位置，预测未来若干天内的过境事件。

    用法::

        predictor = SatellitePassPredictor()
        passes = predictor.predict_passes(
            observer_lat=39.9042,
            observer_lon=116.4074,
            tle1="1 25544U 98067A   26229.79251732 ...",
            tle2="2 25544  51.6334 355.1923 0007534 ...",
            days=7,
        )
        for p in passes:
            print(f"{p.satellite_name}: {p.start_time} 仰角={p.max_elevation}°")
    """

    def __init__(self,
                 min_elevation: float = 10.0,
                 step_seconds: float = 60.0,
                 refine_seconds: float = 5.0):
        """
        初始化预测器

        参数:
            min_elevation:  最小可见仰角阈值 (度, 默认 10°)
            step_seconds:    初始扫描步长 (秒, 默认 60)
            refine_seconds:  过境边界精化步长 (秒, 默认 5)
        """
        self.min_elevation = min_elevation
        self.step_seconds = step_seconds
        self.refine_seconds = refine_seconds

    def predict_passes(self,
                       observer_lat: float,
                       observer_lon: float,
                       tle1: str,
                       tle2: str,
                       days: int = 7,
                       satellite_name: str = "",
                       observer_alt: float = 0.0,
                       start_time: Optional[datetime] = None
                       ) -> List[PassInfo]:
        """
        预测未来若干天内卫星过境

        参数:
            observer_lat:    观察者纬度 (度)
            observer_lon:    观察者经度 (度)
            tle1:            TLE 第一行
            tle2:            TLE 第二行
            days:            预测天数 (默认 7)
            satellite_name:  卫星名称 (可选, 用于输出标识)
            observer_alt:    观察者海拔高度 (km, 默认 0)
            start_time:      预测起始时间 (默认当前 UTC 时间)

        返回:
            PassInfo 过境信息列表 (按时间排序)
        """
        # 解析 TLE
        elements = parse_tle(tle1, tle2)
        propagator = KeplerPropagator(elements)

        # 设置起始时间
        if start_time is None:
            start_time = datetime.now(timezone.utc)
        else:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)

        end_time = start_time + timedelta(days=days)

        # 如果未提供卫星名称, 使用 NORAD ID
        if not satellite_name:
            satellite_name = f"NORAD {elements.norad_id}"

        # 扫描过境事件
        passes = self._scan_passes(
            propagator=propagator,
            observer_lat=observer_lat,
            observer_lon=observer_lon,
            observer_alt=observer_alt,
            start_time=start_time,
            end_time=end_time,
            satellite_name=satellite_name,
            norad_id=elements.norad_id,
        )

        return passes

    def predict_passes_from_cache(self,
                                   observer_lat: float,
                                   observer_lon: float,
                                   data_file: Optional[str] = None,
                                   days: int = 7,
                                   category: Optional[str] = None,
                                   satellite_name: Optional[str] = None,
                                   limit: int = 50,
                                   observer_alt: float = 0.0,
                                   start_time: Optional[datetime] = None
                                   ) -> List[PassInfo]:
        """
        从项目缓存的 satellites.json 读取卫星数据，批量预测过境

        参数:
            observer_lat:    观察者纬度 (度)
            observer_lon:    观察者经度 (度)
            data_file:        satellites.json 路径 (不传则自动推断)
            days:             预测天数
            category:         按类别过滤 (如 "stations", "visual", "weather")
            satellite_name:   按名称模糊搜索 (不区分大小写)
            limit:            最多处理的卫星数量 (默认 50)
            observer_alt:     观察者海拔 (km)
            start_time:       预测起始时间

        返回:
            所有卫星的过境信息列表 (按时间排序)
        """
        # 加载缓存数据
        if data_file is None:
            premium_dir = os.path.dirname(os.path.abspath(__file__))
            data_file = os.path.join(
                os.path.dirname(premium_dir), "data", "satellites.json"
            )

        if not os.path.exists(data_file):
            return []

        with open(data_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        all_satellites = data.get("satellites", [])

        # 类别过滤
        if category:
            cat_lower = category.lower()
            all_satellites = [
                s for s in all_satellites
                if s.get("category", "").lower() == cat_lower
            ]

        # 名称搜索
        if satellite_name:
            name_lower = satellite_name.lower()
            all_satellites = [
                s for s in all_satellites
                if name_lower in s.get("name", "").lower()
            ]

        # 限制数量
        all_satellites = all_satellites[:limit]

        # 逐颗预测
        all_passes: List[PassInfo] = []

        for sat in all_satellites:
            name = sat.get("name", "未知卫星")
            tle1 = sat.get("tle1", "")
            tle2 = sat.get("tle2", "")
            norad_id = sat.get("norad_id", "")

            if not tle1 or not tle2:
                continue

            try:
                passes = self.predict_passes(
                    observer_lat=observer_lat,
                    observer_lon=observer_lon,
                    tle1=tle1,
                    tle2=tle2,
                    days=days,
                    satellite_name=name,
                    observer_alt=observer_alt,
                    start_time=start_time,
                )
                # 填充 NORAD ID
                for p in passes:
                    p.norad_id = norad_id

                all_passes.extend(passes)
            except (ValueError, RuntimeError):
                continue

        # 按开始时间排序
        all_passes.sort(key=lambda p: p.start_time or datetime.max.replace(tzinfo=timezone.utc))

        return all_passes

    # ----------------------------------------------------------
    #  过境扫描核心算法
    # ----------------------------------------------------------

    def _scan_passes(self,
                     propagator: KeplerPropagator,
                     observer_lat: float,
                     observer_lon: float,
                     observer_alt: float,
                     start_time: datetime,
                     end_time: datetime,
                     satellite_name: str,
                     norad_id: str) -> List[PassInfo]:
        """
        扫描时间区间内的过境事件

        算法:
            1. 按步长遍历时间，计算每个时刻的仰角
            2. 仰角从低于阈值变为高于阈值 → 过境开始
            3. 仰角从高于阈值变为低于阈值 → 过境结束
            4. 在过境期间记录最大仰角和方位角
            5. 精化过境起止时间 (缩小步长二分搜索)

        参数:
            propagator:    轨道传播器
            observer_lat:  观察者纬度
            observer_lon:  观察者经度
            observer_alt:  观察者海拔 (km)
            start_time:    扫描起始时间
            end_time:      扫描结束时间
            satellite_name: 卫星名称
            norad_id:      NORAD 编号

        返回:
            PassInfo 过境信息列表
        """
        passes: List[PassInfo] = []

        # 初始扫描
        current_time = start_time
        prev_elev: Optional[float] = None
        in_pass = False

        # 过境临时状态
        pass_start: Optional[datetime] = None
        max_elev = 0.0
        max_elev_time: Optional[datetime] = None
        max_azim = 0.0
        max_range = 0.0
        start_azim = 0.0
        sat_lat_at_start: Optional[float] = None

        step = timedelta(seconds=self.step_seconds)
        total_seconds = (end_time - start_time).total_seconds()
        num_steps = int(total_seconds / self.step_seconds) + 1

        for i in range(num_steps):
            t = start_time + timedelta(seconds=i * self.step_seconds)
            if t > end_time:
                break

            elev, azim, rng = propagator.get_look_angles(
                observer_lat, observer_lon, observer_alt, t
            )

            above_threshold = elev >= self.min_elevation

            if not in_pass and above_threshold:
                # 过境开始
                in_pass = True
                pass_start = t
                max_elev = elev
                max_elev_time = t
                max_azim = azim
                max_range = rng
                start_azim = azim
                sat_lat_at_start, _, _ = propagator.get_subpoint(t)

            elif in_pass:
                if elev > max_elev:
                    max_elev = elev
                    max_elev_time = t
                    max_azim = azim
                    max_range = rng

                if not above_threshold:
                    # 过境结束
                    in_pass = False
                    pass_end = t
                    end_azim = azim

                    # 精化起止时间
                    refined_start = self._refine_time(
                        propagator, observer_lat, observer_lon, observer_alt,
                        pass_start - step, pass_start, rising=True
                    )
                    refined_end = self._refine_time(
                        propagator, observer_lat, observer_lon, observer_alt,
                        pass_end - step, pass_end, rising=False
                    )

                    if refined_start is None:
                        refined_start = pass_start
                    if refined_end is None:
                        refined_end = pass_end

                    # 计算过境方向
                    sat_lat_at_end, _, _ = propagator.get_subpoint(refined_end)
                    direction = self._determine_direction(
                        sat_lat_at_start, sat_lat_at_end
                    )

                    duration = (refined_end - refined_start).total_seconds()

                    passes.append(PassInfo(
                        satellite_name=satellite_name,
                        norad_id=norad_id,
                        start_time=refined_start,
                        end_time=refined_end,
                        max_elevation=max_elev,
                        max_elevation_time=max_elev_time,
                        duration_seconds=duration,
                        direction=direction,
                        start_azimuth=start_azim,
                        max_azimuth=max_azim,
                        end_azimuth=end_azim,
                        slant_range_km=max_range,
                    ))

            prev_elev = elev

        return passes

    def _refine_time(self,
                     propagator: KeplerPropagator,
                     observer_lat: float,
                     observer_lon: float,
                     observer_alt: float,
                     t_before: datetime,
                     t_after: datetime,
                     rising: bool) -> Optional[datetime]:
        """
        二分搜索精化过境起止时间

        在 t_before (仰角低于阈值) 和 t_after (仰角高于阈值) 之间
        二分搜索，找到仰角恰好等于阈值的时刻。

        参数:
            propagator:   轨道传播器
            observer_lat: 观察者纬度
            observer_lon: 观察者经度
            observer_alt: 观察者海拔
            t_before:     仰角低于阈值的时刻
            t_after:       仰角高于阈值的时刻
            rising:        True=寻找升起时刻, False=寻找落下时刻

        返回:
            精化后的时间 (仰角 ≈ 阈值)
        """
        lo = t_before
        hi = t_after

        for _ in range(20):  # 20 次二分, 精度可达 ~0.05 秒
            mid = lo + (hi - lo) / 2
            elev, _, _ = propagator.get_look_angles(
                observer_lat, observer_lon, observer_alt, mid
            )

            if elev >= self.min_elevation:
                # 仰角高于阈值
                if rising:
                    hi = mid  # 升起时, 向前搜索
                else:
                    lo = mid  # 落下时, 向后搜索
            else:
                # 仰角低于阈值
                if rising:
                    lo = mid
                else:
                    hi = mid

        return lo + (hi - lo) / 2

    @staticmethod
    def _determine_direction(lat_at_start: Optional[float],
                              lat_at_end: Optional[float]) -> str:
        """
        根据过境起止时的卫星纬度变化判断过境方向

        参数:
            lat_at_start: 过境开始时卫星星下点纬度
            lat_at_end:   过境结束时卫星星下点纬度

        返回:
            方向描述 (中文): "北→南" 或 "南→北"
        """
        if lat_at_start is None or lat_at_end is None:
            return "未知"

        if lat_at_end > lat_at_start:
            return "南→北"  # 升轨 (向北飞行)
        else:
            return "北→南"  # 降轨 (向南飞行)


# ============================================================
#  便捷函数
# ============================================================

def predict_satellite_passes(observer_lat: float,
                              observer_lon: float,
                              tle1: str,
                              tle2: str,
                              days: int = 7,
                              satellite_name: str = "",
                              min_elevation: float = 10.0) -> List[PassInfo]:
    """
    便捷函数: 一行调用预测卫星过境

    参数:
        observer_lat:   观察者纬度 (度)
        observer_lon:   观察者经度 (度)
        tle1:           TLE 第一行
        tle2:           TLE 第二行
        days:            预测天数
        satellite_name:  卫星名称
        min_elevation:   最小可见仰角 (度)

    返回:
        PassInfo 过境信息列表
    """
    predictor = SatellitePassPredictor(min_elevation=min_elevation)
    return predictor.predict_passes(
        observer_lat=observer_lat,
        observer_lon=observer_lon,
        tle1=tle1,
        tle2=tle2,
        days=days,
        satellite_name=satellite_name,
    )


# ============================================================
#  模块自测 / 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  航空通 卫星过境预测演示")
    print("=" * 60)

    # ISS TLE (国际空间站)
    iss_tle1 = "1 25544U 98067A   26229.79251732  .00005860  00000+0  11255-3 0  9992"
    iss_tle2 = "2 25544  51.6334 355.1923 0007534  57.5442 302.6274 15.49477092581307"

    # CSS TLE (中国空间站天和核心舱)
    css_tle1 = "1 48274U 21035A   26229.66261368  .00001567  00000+0  23690-4 0  9997"
    css_tle2 = "2 48274  41.4707 308.8276 0001154 262.1579  97.9128 15.59041175302769"

    # 观察者位置: 北京 (39.9042°N, 116.4074°E)
    obs_lat = 39.9042
    obs_lon = 116.4074

    print(f"\n观察者位置: {obs_lat}°N, {obs_lon}°E (北京)")
    print(f"预测天数: 3 天")
    print(f"最小仰角: 10°\n")

    # --- 测试 1: ISS 过境预测 ---
    print("-" * 60)
    print("  ISS (国际空间站) 过境预测")
    print("-" * 60)

    # 解析 TLE 并显示轨道参数
    elements = parse_tle(iss_tle1, iss_tle2)
    print(f"  NORAD ID:      {elements.norad_id}")
    print(f"  历元:          {elements.epoch.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  轨道倾角:      {elements.inclination:.4f}°")
    print(f"  升交点赤经:    {elements.raan:.4f}°")
    print(f"  偏心率:        {elements.eccentricity:.7f}")
    print(f"  近地点幅角:    {elements.arg_perigee:.4f}°")
    print(f"  平近点角:      {elements.mean_anomaly:.4f}°")
    print(f"  平均运动:      {elements.mean_motion:.6f} 转/天")
    print(f"  半长轴:        {elements.semi_major_axis:.2f} km")
    print(f"  轨道周期:      {elements.orbital_period_minutes:.2f} 分钟")

    predictor = SatellitePassPredictor(min_elevation=10.0, step_seconds=60.0)

    # 使用从 TLE 历元开始的预测 (确保结果可复现)
    start = datetime.now(timezone.utc)
    passes = predictor.predict_passes(
        observer_lat=obs_lat,
        observer_lon=obs_lon,
        tle1=iss_tle1,
        tle2=iss_tle2,
        days=3,
        satellite_name="ISS (ZARYA)",
        start_time=start,
    )

    print(f"\n  预测到 {len(passes)} 次过境:\n")
    for i, p in enumerate(passes, 1):
        d = p.to_dict()
        print(f"  [{i}] {d['satellite_name']}")
        print(f"      开始: {d['start_time']}  方位角 {d['start_azimuth']}°")
        print(f"      最高: {d['max_elevation_time']}  仰角 {d['max_elevation']}°  方位角 {d['max_azimuth']}°")
        print(f"      结束: {d['end_time']}  方位角 {d['end_azimuth']}°")
        print(f"      时长: {d['duration_str']}  方向: {d['direction']}  斜距: {d['slant_range_km']} km")
        print()

    # --- 测试 2: CSS (中国空间站) 过境预测 ---
    print("-" * 60)
    print("  CSS (天和核心舱) 过境预测")
    print("-" * 60)

    passes_css = predictor.predict_passes(
        observer_lat=obs_lat,
        observer_lon=obs_lon,
        tle1=css_tle1,
        tle2=css_tle2,
        days=3,
        satellite_name="CSS (TIANHE)",
        start_time=start,
    )

    print(f"\n  预测到 {len(passes_css)} 次过境:\n")
    for i, p in enumerate(passes_css, 1):
        d = p.to_dict()
        print(f"  [{i}] {d['satellite_name']}")
        print(f"      开始: {d['start_time']}  方位角 {d['start_azimuth']}°")
        print(f"      最高: {d['max_elevation_time']}  仰角 {d['max_elevation']}°  方位角 {d['max_azimuth']}°")
        print(f"      结束: {d['end_time']}  方位角 {d['end_azimuth']}°")
        print(f"      时长: {d['duration_str']}  方向: {d['direction']}  斜距: {d['slant_range_km']} km")
        print()

    # --- 测试 3: 从缓存数据批量预测 ---
    print("-" * 60)
    print("  从缓存数据批量预测 (stations 类别, 最多 5 颗)")
    print("-" * 60)

    cached_passes = predictor.predict_passes_from_cache(
        observer_lat=obs_lat,
        observer_lon=obs_lon,
        days=2,
        category="stations",
        limit=5,
        start_time=start,
    )

    print(f"\n  共预测到 {len(cached_passes)} 次过境:\n")
    for i, p in enumerate(cached_passes[:10], 1):  # 只显示前 10 条
        d = p.to_dict()
        print(f"  [{i}] {d['satellite_name']:20s}  "
              f"{d['start_time']}  仰角 {d['max_elevation']:5.1f}°  "
              f"时长 {d['duration_str']:8s}  {d['direction']}")

    print("\n" + "=" * 60)
    print("  演示结束")
    print("=" * 60)
