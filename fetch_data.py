#!/usr/bin/env python3
"""
Ocean Data Fetcher — 从 NOAA ERDDAP + Copernicus Marine 获取海洋环境数据
生成 ocean_data.json 供游戏端下载

数据源:
  🌡️ 海表温度 (SST)  → NOAA CoastWatch ERDDAP [无需认证]
  🌿 叶绿素-a         → Copernicus Marine BGC 分析预报 [需认证]
  💨 溶解氧            → Copernicus Marine BGC 分析预报 [需认证]
  🧂 盐度              → Copernicus Marine PHY 分析预报 [需认证]
  🗑️ 微塑料            → 区域统计模拟 (无免费实时数据源)

使用方式:
  python fetch_data.py
  # 或指定区域
  python fetch_data.py --lat-min 18 --lat-max 26 --lon-min 108 --lon-max 121
"""

import json
import sys
import argparse
import requests
from datetime import datetime, timedelta

# ============================================================
#  配置
# ============================================================

# 目标海域默认值：中国南海北部
DEFAULT_LAT_MIN = 18.0
DEFAULT_LAT_MAX = 26.0
DEFAULT_LON_MIN = 108.0
DEFAULT_LON_MAX = 121.0

# NOAA ERDDAP - SST
SST_URL = "https://coastwatch.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SnrtCDaily.json"

# Copernicus Marine 数据集 ID (2024年4月后新Data Store格式)
# 注意: 叶绿素和溶解氧在不同的子数据集里!
# BGC-PFT: 浮游植物 — 包含叶绿素(chl)
COPERNICUS_BGC_CHL_DATASET = "cmems_mod_glo_bgc-pft_anfc_0.25deg_P1D-m"
# BGC-BIO: 初级生产+溶解氧 — 包含溶解氧(o2)
COPERNICUS_BGC_O2_DATASET = "cmems_mod_glo_bgc-bio_anfc_0.25deg_P1D-m"
# PHY: 物理 — 盐度(so) 日平均
COPERNICUS_PHY_SALINITY_DATASET = "cmems_mod_glo_phy-so_anfc_0.083deg_P1D-m"

# ============================================================
#  NOAA SST 获取 (无需认证)
# ============================================================

def fetch_noaa_sst(lat_min, lat_max, lon_min, lon_max, days_offset=3):
    """从 NOAA CoastWatch ERDDAP 获取海表温度"""
    date_str = (datetime.utcnow() - timedelta(days=days_offset)).strftime("%Y-%m-%d")

    url = (
        f"{SST_URL}?"
        f"sea_surface_temperature[({date_str}T12:00:00Z):1:({date_str}T12:00:00Z)]"
        f"[({lat_min}):1.0:({lat_max})]"
        f"[({lon_min}):1.0:({lon_max})]"
    )

    print(f"[NOAA SST] 请求: {date_str}, 区域: {lat_min}-{lat_max}°N, {lon_min}-{lon_max}°E")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        rows = data.get("table", {}).get("rows", [])
        values = [row[3] for row in rows if row[3] is not None and -5 < row[3] < 45]

        if values:
            avg = sum(values) / len(values)
            print(f"[NOAA SST] ✅ 成功: {avg:.2f}°C (样本数: {len(values)})")
            return {
                "value": round(avg, 2),
                "sample_count": len(values),
                "source": "NOAA CoastWatch ERDDAP",
                "is_real": True
            }
        else:
            print("[NOAA SST] ⚠️ 无有效数据 (云覆盖?)")

    except Exception as e:
        print(f"[NOAA SST] ❌ 失败: {e}")

    return None


# ============================================================
#  Copernicus Marine 获取 (需认证)
# ============================================================

def fetch_copernicus_subset(dataset_id, variables, lat_min, lat_max, lon_min, lon_max,
                            depth_min=0.5, depth_max=1, days_offset=3, username=None, password=None):
    """
    从 Copernicus Marine Data Store 获取子集数据
    使用 copernicusmarine Python 包
    """
    try:
        import copernicusmarine
        print(f"[Copernicus] copernicusmarine 版本: {copernicusmarine.__version__}")
    except ImportError:
        print("[Copernicus] ⚠️ copernicusmarine 未安装，尝试安装...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "copernicusmarine"])
        import copernicusmarine

    date_str = (datetime.utcnow() - timedelta(days=days_offset)).strftime("%Y-%m-%d")
    next_date = (datetime.utcnow() - timedelta(days=days_offset - 1)).strftime("%Y-%m-%d")

    print(f"[Copernicus] 请求: {dataset_id}")
    print(f"  变量: {variables}, 日期: {date_str} ~ {next_date}")

    try:
        kwargs = dict(
            dataset_id=dataset_id,
            variables=variables,
            minimum_longitude=lon_min,
            maximum_longitude=lon_max,
            minimum_latitude=lat_min,
            maximum_latitude=lat_max,
            minimum_depth=depth_min,
            maximum_depth=depth_max,
            start_datetime=date_str,
            end_datetime=next_date,
            file_format="csv",
        )

        # 认证 (优先用参数，其次用环境变量 COPERNICUSMARINE_SERVICE_USERNAME)
        if username and password:
            kwargs["username"] = username
            kwargs["password"] = password

        result = copernicusmarine.subset(**kwargs)

        # 从返回结果中提取均值
        return _extract_copernicus_values(result, variables)

    except Exception as e:
        print(f"[Copernicus] ❌ 获取失败 ({dataset_id}): {type(e).__name__}: {e}")
        return None


def _extract_copernicus_values(result, variables):
    """从 copernicusmarine 返回结果中提取均值"""
    values = {}

    try:
        # copernicusmarine.subset() 返回 ResponseSubset 对象
        # 可能的返回形式: xarray Dataset, 文件路径, DataFrame 等

        import xarray as xr
        import pandas as pd

        # 情况1: xarray Dataset (在线模式)
        if isinstance(result, xr.Dataset):
            print(f"[Copernicus] 收到 xarray Dataset, 变量: {list(result.data_vars)}")
            for var in variables:
                if var in result:
                    data = result[var].values.flatten()
                    valid = data[~(data != data)]  # 去除 NaN
                    if len(valid) > 0:
                        values[var] = {
                            "mean": float(valid.mean()),
                            "count": int(len(valid)),
                            "is_real": True
                        }
            return values if values else None

        # 情况2: pandas DataFrame
        if isinstance(result, pd.DataFrame):
            print(f"[Copernicus] 收到 DataFrame, 列: {list(result.columns)}")
            for var in variables:
                if var in result.columns:
                    valid = result[var].dropna()
                    if len(valid) > 0:
                        values[var] = {
                            "mean": float(valid.mean()),
                            "count": int(len(valid)),
                            "is_real": True
                        }
            return values if values else None

        # 情况3: 文件路径 (CSV 下载模式)
        if isinstance(result, str) or hasattr(result, '__fspath__'):
            filepath = str(result)
            print(f"[Copernicus] 收到文件: {filepath}")
            # 判断文件类型
            if filepath.endswith('.csv'):
                df = pd.read_csv(filepath)
                print(f"[Copernicus] CSV 列: {list(df.columns)}")
                for var in variables:
                    if var in df.columns:
                        valid = df[var].dropna()
                        if len(valid) > 0:
                            values[var] = {
                                "mean": float(valid.mean()),
                                "count": int(len(valid)),
                                "is_real": True
                            }
                return values if values else None

        # 情况4: ResponseSubset 对象 (copernicusmarine 新版本)
        # 检查是否有 .dataset 或 .file_path 属性
        if hasattr(result, 'dataset'):
            print(f"[Copernicus] 收到 ResponseSubset.dataset")
            return _extract_copernicus_values(result.dataset, variables)

        if hasattr(result, 'file_path'):
            print(f"[Copernicus] 收到 ResponseSubset.file_path: {result.file_path}")
            return _extract_copernicus_values(result.file_path, variables)

        # 情况5: 尝试遍历 / 其他类型
        print(f"[Copernicus] 未知返回类型: {type(result)}, 尝试通用解析...")

        # 如果 result 是可迭代对象
        if hasattr(result, '__iter__') and not isinstance(result, (str, dict)):
            for item in result:
                sub_result = _extract_copernicus_values(item, variables)
                if sub_result:
                    return sub_result

        print(f"[Copernicus] 无法解析返回结果类型: {type(result)}")
        return None

    except Exception as e:
        print(f"[Copernicus] 解析结果失败: {type(e).__name__}: {e}")
        return None


# ============================================================
#  科学估算 / 模拟 (当 API 不可用时的降级方案)
# ============================================================

def estimate_dissolved_oxygen(temp_c):
    """Weiss (1970) 简化方程: DO ≈ 288.5 - 6.13*T + 0.087*T² (μmol/kg)"""
    o2_sat = 288.5 - 6.13 * temp_c + 0.087 * temp_c ** 2
    return round(o2_sat * 0.97, 1)  # 97% 饱和度

def simulate_chlorophyll():
    """南海叶绿素统计基准: 0.5~4.5 mg/m³"""
    import random
    return round(1.5 + random.uniform(0, 3), 2)

def simulate_salinity():
    """南海表层盐度气候态: 33.5~34.6 PSU"""
    import random
    return round(34.0 + random.uniform(-0.5, 0.6), 1)

def simulate_microplastic():
    """微塑料浓度: 500~20000 个/m³ (无免费实时数据源)"""
    import random
    return round(3500 + random.uniform(-1500, 5000))


# ============================================================
#  主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Ocean Data Fetcher for CTP Game")
    parser.add_argument("--lat-min", type=float, default=DEFAULT_LAT_MIN)
    parser.add_argument("--lat-max", type=float, default=DEFAULT_LAT_MAX)
    parser.add_argument("--lon-min", type=float, default=DEFAULT_LON_MIN)
    parser.add_argument("--lon-max", type=float, default=DEFAULT_LON_MAX)
    parser.add_argument("--days-offset", type=int, default=3, help="数据日期偏移天数")
    parser.add_argument("--username", type=str, default=None, help="Copernicus 用户名")
    parser.add_argument("--password", type=str, default=None, help="Copernicus 密码")
    args = parser.parse_args()

    print("=" * 60)
    print("🌊 CTP Ocean Data Fetcher")
    print(f"   区域: {args.lat_min}~{args.lat_max}°N, {args.lon_min}~{args.lon_max}°E")
    print(f"   时间: {(datetime.utcnow() - timedelta(days=args.days_offset)).strftime('%Y-%m-%d')}")
    print(f"   Copernicus 认证: {'✅ 已配置' if args.username else '❌ 未配置'}")
    print("=" * 60)

    # ---- 第1步: NOAA SST (无需认证) ----
    sst_result = fetch_noaa_sst(
        args.lat_min, args.lat_max, args.lon_min, args.lon_max, args.days_offset
    )

    # ---- 第2步: Copernicus BGC-PFT (叶绿素) ----
    chl_result = None
    if args.username and args.password:
        print("\n[Copernicus BGC-PFT] 获取叶绿素...")
        chl_result = fetch_copernicus_subset(
            COPERNICUS_BGC_CHL_DATASET,
            variables=["chl"],
            lat_min=args.lat_min, lat_max=args.lat_max,
            lon_min=args.lon_min, lon_max=args.lon_max,
            depth_min=0.5, depth_max=1,
            days_offset=args.days_offset,
            username=args.username, password=args.password
        )
    else:
        print("\n[Copernicus BGC-PFT] ⚠️ 未提供认证信息，跳过叶绿素")

    # ---- 第2.5步: Copernicus BGC-BIO (溶解氧) ----
    o2_result = None
    if args.username and args.password:
        print("\n[Copernicus BGC-BIO] 获取溶解氧...")
        o2_result = fetch_copernicus_subset(
            COPERNICUS_BGC_O2_DATASET,
            variables=["o2"],
            lat_min=args.lat_min, lat_max=args.lat_max,
            lon_min=args.lon_min, lon_max=args.lon_max,
            depth_min=0.5, depth_max=1,
            days_offset=args.days_offset,
            username=args.username, password=args.password
        )
    else:
        print("\n[Copernicus BGC-BIO] ⚠️ 未提供认证信息，跳过溶解氧")

    # ---- 第3步: Copernicus PHY (盐度) ----
    phy_result = None
    if args.username and args.password:
        print("\n[Copernicus PHY] 获取盐度...")
        phy_result = fetch_copernicus_subset(
            COPERNICUS_PHY_SALINITY_DATASET,
            variables=["so"],
            lat_min=args.lat_min, lat_max=args.lat_max,
            lon_min=args.lon_min, lon_max=args.lon_max,
            depth_min=0.5, depth_max=1,
            days_offset=args.days_offset,
            username=args.username, password=args.password
        )
    else:
        print("[Copernicus PHY] ⚠️ 未提供认证信息，跳过")

    # ---- 第4步: 组装最终数据 ----
    print("\n" + "=" * 60)
    print("📦 组装最终数据...")

    # SST
    if sst_result:
        sst_value = sst_result["value"]
        sst_is_real = True
        sst_source = "NOAA ERDDAP"
    else:
        import random
        sst_value = round(26.0 + random.uniform(-2.5, 3.5), 2)
        sst_is_real = False
        sst_source = "科学基准值"

    # 叶绿素
    if chl_result and "chl" in chl_result:
        chl_value = round(chl_result["chl"]["mean"], 2)
        chl_is_real = True
        chl_source = "Copernicus Marine"
    else:
        chl_value = simulate_chlorophyll()
        chl_is_real = False
        chl_source = "统计模拟"

    # 溶解氧 (Copernicus 返回 mmol/m³, 需转换为 μmol/kg: 1 mmol/m³ ≈ 1 μmol/kg * 密度/1000 ≈ 1.023 μmol/kg)
    if o2_result and "o2" in o2_result:
        do_value = round(o2_result["o2"]["mean"] * 1.023, 1)  # mmol/m³ → μmol/kg 近似转换
        do_is_real = True
        do_source = "Copernicus Marine"
    else:
        do_value = estimate_dissolved_oxygen(sst_value)
        do_is_real = False
        do_source = "Weiss方程估算"

    # 盐度
    if phy_result and "so" in phy_result:
        sal_value = round(phy_result["so"]["mean"], 1)
        sal_is_real = True
        sal_source = "Copernicus Marine"
    else:
        sal_value = simulate_salinity()
        sal_is_real = False
        sal_source = "气候态常量"

    # 微塑料 (始终为模拟)
    mp_value = simulate_microplastic()

    # 判断整体数据质量
    any_real = sst_is_real or chl_is_real or do_is_real or sal_is_real
    real_count = sum([sst_is_real, chl_is_real, do_is_real, sal_is_real])

    # 构建输出 JSON
    output = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": {
            "name": "South China Sea",
            "lat_min": args.lat_min,
            "lat_max": args.lat_max,
            "lon_min": args.lon_min,
            "lon_max": args.lon_max
        },
        "data": {
            "sea_surface_temperature": {
                "value": sst_value,
                "unit": "°C",
                "source": sst_source,
                "is_real": sst_is_real
            },
            "chlorophyll_a": {
                "value": chl_value,
                "unit": "mg/m³",
                "source": chl_source,
                "is_real": chl_is_real
            },
            "dissolved_oxygen": {
                "value": do_value,
                "unit": "μmol/kg",
                "source": do_source,
                "is_real": do_is_real
            },
            "salinity": {
                "value": sal_value,
                "unit": "PSU",
                "source": sal_source,
                "is_real": sal_is_real
            },
            "microplastic": {
                "value": mp_value,
                "unit": "particles/m³",
                "source": "区域统计模拟",
                "is_real": False
            }
        },
        "quality": {
            "real_data_count": real_count,
            "total_params": 5,
            "any_real_data": any_real,
            "level": "excellent" if real_count >= 4 else "good" if real_count >= 2 else "basic"
        }
    }

    # 写入文件
    output_path = "docs/ocean_data.json"
    import os
    os.makedirs("docs", exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 数据已写入: {output_path}")
    print(f"   真实数据: {real_count}/5 个参数")
    print(f"   🌡️ SST:    {sst_value}°C [{sst_source}]")
    print(f"   🌿 叶绿素: {chl_value} mg/m³ [{chl_source}]")
    print(f"   💨 溶解氧: {do_value} μmol/kg [{do_source}]")
    print(f"   🧂 盐度:   {sal_value} PSU [{sal_source}]")
    print(f"   🗑️ 微塑料: {mp_value} 个/m³ [模拟]")


if __name__ == "__main__":
    main()
