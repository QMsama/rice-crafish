import numpy as np
import os
import glob
import datetime
from osgeo import gdal

# ==========================================
# 1. 配置区：路径、参数与单位说明
# ==========================================

# --- 输入数据路径 ---
BASE_MASK = r"D:\桌面文件\mode\rice_crayfish\Rice_2021.tif"
SOIL_PH = r"D:\桌面文件\mode\soil\Environmental Date_pH.tif"
SOIL_SOM = r"D:\桌面文件\mode\soil\Environmental Data_SOM.tif"
N_FER = r"D:\桌面文件\mode\nitrogen_fertilizer_use\Nfer-2018"
RAIN_DIR = r"D:\桌面文件\mode\rain\rain daily tiff\2024"
ET_DIR = r"D:\桌面文件\mode\蒸散发\T_2024_daily_tiff"
OUTPUT_DIR = r"D:\#data\Python\面上估算\测试V2"

# --- 输出结果 ---
# 1. TN_Load_RM_2022.tif      : 单季稻(RM)累积TN流失负荷 (kg/ha)
# 2. TN_Load_RCC_2022.tif     : 稻虾共作(RCC)累积TN流失负荷 (kg/ha)
# 3. 控制台统计               : 非零像元均值、标准差、最大值

# --- 物理与面积参数 (单位已标注) ---
PIXEL_AREA_HA = 20.0          # 每个像元代表的面积 (ha)
S_LOSS = 2.0                  # 日下渗量 (mm/d)
DEFAULT_ET = 5.0              # ET缺失时的默认值 (mm/d)

# --- RCC沟渠工程参数 (面尺度等效参数) ---
RCC_DITCH_RATIO = 0.30        # 沟面积占像元比例 (面尺度聚合值, 文献点尺度约0.276)
RCC_DITCH_DEPTH_MAX = 900.0   # 沟渠最大等效水深 (mm)
RCC_DITCH_NORMAL = 800.0      # 沟渠初始等效水深 (mm)
RCC_DITCH_LENGTH_PER_HA = 920  # 每公顷沟长 (m/ha), 文献点尺度: 285m/0.31ha
RCC_DITCH_COEF_B = 0.9        # 沟道截面系数 (点模块继承)
RCC_DITCH_COEF_A = 1.1667     # 沟道截面系数 (点模块继承)
STORM_THRESHOLD = 60.0

# --- 施肥配置 (日期: MMDD, 比例: 占总施肥量) ---
# 注意: 日期填 None 表示该生育期不施肥
FERTILIZER_CONFIG = {
    "rice": {
        "base":      {"date": 601,  "ratio": 0.7},
        "tillering": {"date": 618,  "ratio": 0.3},
        "heading":   {"date": None,  "ratio": 0}
    },
    "cray": {
        "base":      {"date": 601, "ratio": 0.7},
        "tillering": {"date": 618,  "ratio": 0.3},
        "heading":   {"date": None, "ratio": 0.0}
    }
}

# --- TN一级动力学衰减系数 (1/d) ---
TN_DECAY_K = {
    "rice": {"base": 0.250, "tillering": 0.400, "heading": 0.400},
    "cray": {"base": 0.300, "tillering": 0.400, "heading": 0.467}
}

# --- 模拟时段 ---
START_DATE = datetime.date(2024, 6, 1)
END_DATE = datetime.date(2024, 9, 23)

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==========================================
# 2. 工具函数
# ==========================================

def read_and_align_to_base(target_path, base_ds, forced_src_srs=None):
    """
    将目标栅格对齐到基准栅格的投影、范围、分辨率。
    返回: numpy数组 (float32), NoData转为np.nan
    """
    gt = base_ds.GetGeoTransform()
    cols, rows = base_ds.RasterXSize, base_ds.RasterYSize
    minX, maxY = gt[0], gt[3]
    maxX = minX + gt[1] * cols
    minY = maxY + gt[5] * rows

    kwargs = {
        'format': 'VRT',
        'outputBounds': [minX, minY, maxX, maxY],
        'width': cols, 'height': rows,
        'dstSRS': base_ds.GetProjection(),
        'resampleAlg': gdal.GRA_Bilinear
    }
    if forced_src_srs:
        kwargs['srcSRS'] = forced_src_srs

    tmp_ds = gdal.Warp('', target_path, **kwargs)
    if tmp_ds is None:
        raise RuntimeError(f"❌ 对齐失败: {target_path}")

    arr = tmp_ds.GetRasterBand(1).ReadAsArray().astype(np.float32)
    nodata = tmp_ds.GetRasterBand(1).GetNoDataValue()
    if nodata is not None:
        arr = np.where(arr == nodata, np.nan, arr)
    return arr


def kriging_fill_2d(arr, gt, max_samples=8000):
    """
    对二维数组中的NaN/NoData进行克里金插值填充。
    优先使用 PyKrige (pip install pykrige)；若未安装，回退到 RBF (径向基函数)。
    RBF的thin plate spline核在平滑性上与克里金接近，适合连续型土壤属性。
    """
    rows, cols = arr.shape
    invalid = np.isnan(arr)
    if not np.any(invalid):
        return arr

    # 构建地理坐标网格
    x_coords = gt[0] + np.arange(cols) * gt[1]
    y_coords = gt[3] + np.arange(rows) * gt[5]
    xv, yv = np.meshgrid(x_coords, y_coords)

    x_valid = xv[~invalid]
    y_valid = yv[~invalid]
    z_valid = arr[~invalid]

    # 若样本过多，随机采样以控制计算量
    if len(z_valid) > max_samples:
        idx = np.random.choice(len(z_valid), max_samples, replace=False)
        x_valid, y_valid, z_valid = x_valid[idx], y_valid[idx], z_valid[idx]

    # 尝试克里金
    try:
        from pykrige.ok import OrdinaryKriging
        print("   🔬 使用 PyKrige 普通克里金插值...")
        OK = OrdinaryKriging(
            x_valid, y_valid, z_valid,
            variogram_model='spherical',
            verbose=False,
            enable_plotting=False
        )
        # 对整个网格预测 (rows x cols)
        z_pred, _ = OK.execute('grid', x_coords, y_coords, backend='vectorized')
        result = np.where(invalid, z_pred, arr)
        return result
    except Exception as e:
        print(f"   ⚠️ PyKrige 不可用({e})，回退到 RBF 径向基插值 (效果接近克里金)...")
        from scipy.interpolate import RBFInterpolator
        rbf = RBFInterpolator(
            np.column_stack([x_valid, y_valid]),
            z_valid,
            kernel='thin_plate_spline'
        )
        pts = np.column_stack([xv[invalid], yv[invalid]])
        result = arr.copy()
        result[invalid] = rbf(pts)
        return result


def depth_to_volume_ditch_mm(h_mm, L, b=0.9, a=1.1667):
    """沟道水深(mm) → 体积(m³)。向量化兼容。"""
    h_m = h_mm / 1000.0
    return L * (b * h_m + a * h_m**2)


def volume_to_depth_ditch_vec(V, L, b=0.9, a=1.1667):
    """沟道体积(m³) → 水深(mm)。向量化兼容。"""
    # a*h^2 + b*h - V/L = 0, 取正根
    c = -(V / L)
    disc = np.maximum(0.0, b**2 - 4 * a * c)
    h_m = (-b + np.sqrt(disc)) / (2 * a)
    return h_m * 1000.0


def calculate_tn_initial_vec(fer_amount, ph, som, stage):
    """
    论文公式计算TN初始浓度 C0 (mg/L)。
    fer_amount: 该次施肥量 (kg/ha), ph: 无量纲, som: (%)
    """
    if stage == 'base':
        val = -21.469 + 0.841 * fer_amount + 3.074 * ph
    elif stage == 'tillering':
        val = -101.200 + 0.540 * fer_amount + 22.184 * ph - 11.093 * som
    elif stage == 'heading':
        val = -164.918 + 0.435 * fer_amount + 26.256 * ph
    else:
        val = np.zeros_like(fer_amount)
    return np.maximum(0.001, val)


def find_daily_file(folder, year, doy):
    """搜索日值栅格文件，支持多种命名格式"""
    if not os.path.exists(folder):
        return None
    
    # 支持格式列表（按优先级）
    patterns = [
        # 降雨格式: PRE_2024_Day_153.tif
        f"PRE_{year}_Day_{doy:03d}*.tif",
        f"PRE_*_Day_{doy:03d}*.tif",
        
        # ET格式: T_2022261.tif 或 T_2022_261.tif
        f"*{year}*{doy:03d}*.tif",
        f"*{year}*Day_{doy:03d}*.tif",
        f"*{year}{doy:03d}*.tif",
        
        # 通用兜底
        f"*Day_{doy:03d}*.tif",
        f"*{doy:03d}*.tif"
    ]
    
    for p in patterns:
        matches = glob.glob(os.path.join(folder, p))
        if matches:
            # 返回第一个匹配，并打印找到的文件名（调试用）
            # print(f"   ✅ 找到: {os.path.basename(matches[0])} (模式: {p})")
            return matches[0]
    
    # 如果没找到，打印警告
    print(f"   ⚠️ 未找到 DOY={doy} 的文件，已尝试模式: {patterns[:3]}...")
    return None


# ==========================================
# 3. 加载基准栅格与静态环境数据
# ==========================================
print("🚀 加载基准栅格与静态数据...")
mask_ds = gdal.Open(BASE_MASK)
mask_data = mask_ds.GetRasterBand(1).ReadAsArray()
gt = mask_ds.GetGeoTransform()
rows, cols = mask_data.shape
print(f"   基准栅格: {cols} 列 × {rows} 行")

# 掩膜统计
rm_mask = (mask_data == 1)
rcc_mask = (mask_data == 3)
print(f"   RM像元数: {np.sum(rm_mask)}, RCC像元数: {np.sum(rcc_mask)}")

# 读取并对齐静态数据
print("\n🔄 对齐静态环境栅格...")
ph_raw = read_and_align_to_base(SOIL_PH, mask_ds)
som_raw = read_and_align_to_base(SOIL_SOM, mask_ds)
nfer_raw = read_and_align_to_base(N_FER, mask_ds)

# 克里金插值填充NoData (土壤属性连续变量，克里金/RBF最合理)
print("🌐 对土壤pH进行空间插值...")
ph_data = kriging_fill_2d(ph_raw, gt)
ph_data = np.clip(ph_data, 4.0, 10.0)

print("🌐 对土壤SOM进行空间插值...")
som_data = kriging_fill_2d(som_raw, gt)
som_data = np.clip(som_data, 0.1, 5.0)

print("🌐 对氮肥进行空间插值...")
nfer_data = kriging_fill_2d(nfer_raw, gt)
nfer_data = np.where((nfer_data < 0) | np.isnan(nfer_data), 0.0, nfer_data)
nfer_data = nfer_data * 10.0  # 单位换算（若原始数据为其他单位需调整）

print("   ✅ 静态数据准备完成")

# ==========================================
# 4. 初始化面尺度状态数组
# ==========================================

# -- 面积与沟道参数 (向量化常量) --
A_total = PIXEL_AREA_HA * 10000.0          # 像元总面积 (m²)
A_paddy = A_total * (1.0 - RCC_DITCH_RATIO)  # RCC稻田面积 (m²)
A_ditch = A_total * RCC_DITCH_RATIO          # RCC沟顶面积 (m²)
L_ditch = PIXEL_AREA_HA * RCC_DITCH_LENGTH_PER_HA  # 沟长 (m)

# -- 水量状态 --
h_rm = np.zeros((rows, cols), dtype=np.float32)          # RM田面水位 (mm)
h_rcc_paddy = np.zeros((rows, cols), dtype=np.float32)   # RCC稻田水位 (mm)
v_rcc_ditch = np.zeros((rows, cols), dtype=np.float32)   # RCC沟渠体积 (m³)

# 初始化RCC沟渠体积 (对应正常水位800mm)
v_rcc_init = depth_to_volume_ditch_mm(RCC_DITCH_NORMAL, L_ditch)
v_rcc_ditch[rcc_mask] = v_rcc_init

# -- TN浓度状态 (mg/L) --
c_tn_rm = np.full((rows, cols), 1, dtype=np.float32)   # RM初始TN
c_tn_rcc = np.full((rows, cols), 1., dtype=np.float32)   # RCC初始TN

# -- 负荷累加器 (kg/ha) --
accum_load_rm = np.zeros((rows, cols), dtype=np.float32)
accum_load_rcc = np.zeros((rows, cols), dtype=np.float32)
                                
# -- 当前衰减阶段标记 --
rice_stage = 'base'
cray_stage = 'base'

# ==========================================
# 5. 逐日循环模拟（带详细DEBUG日志）
# ==========================================
delta_days = (END_DATE - START_DATE).days + 1
print(f"\n📅 开始面尺度耦合模拟: {START_DATE} 至 {END_DATE}, 共 {delta_days} 天")
print("=" * 70)

# DEBUG开关: 设为True会打印每天详细过程
DEBUG_DAILY = True
# 只打印前N天的详细过程，避免刷屏
DEBUG_FIRST_N_DAYS = 30

for day_idx in range(delta_days):
    current_date = START_DATE + datetime.timedelta(days=day_idx)
    doy = current_date.timetuple().tm_yday
    md = current_date.month * 100 + current_date.day
    date_str = current_date.strftime("%Y-%m-%d")
    
    # --- 5.1 读取气象数据 ---
    rain_path = find_daily_file(RAIN_DIR, current_date.year, doy)
    et_path = find_daily_file(ET_DIR, current_date.year, doy)
    
    # 降雨读取
    if rain_path and os.path.exists(rain_path):
        P_raw = read_and_align_to_base(rain_path, mask_ds)
        if np.nanmax(np.abs(P_raw)) > 1000:
            P_raw = P_raw / 1000.0
        P = np.where(np.isnan(P_raw), 0.0, P_raw)
        P = np.where(P < 0, 0.0, P)
        p_status = f"✅ 读取成功 (max={np.nanmax(P):.1f}mm)"
    else:
        P = np.zeros((rows, cols), dtype=np.float32)
        p_status = "❌ 缺失,设为0"
    
    # ET读取
    if et_path and os.path.exists(et_path):
        ET_raw = read_and_align_to_base(et_path, mask_ds, forced_src_srs='EPSG:4326')
        if np.nanmax(np.abs(ET_raw)) > 100:
            ET_raw = ET_raw / 1000.0
        ET = np.where(np.isnan(ET_raw), DEFAULT_ET, ET_raw)
        ET = np.where(ET < 0, 0.0, ET)
        et_status = f"✅ 读取成功 (max={np.nanmax(ET):.1f}mm)"
    else:
        ET = np.full((rows, cols), DEFAULT_ET, dtype=np.float32)
        et_status = f"⚠️ 缺失,用默认值{DEFAULT_ET}"
    
    # --- 5.2 水位阈值设置 ---
    if 601 <= md <= 616:       rm_min, rm_target, rm_max = 20, 40, 80
    elif 616 <= md <= 628:     rm_min, rm_target, rm_max = 30, 50, 100
    elif 629 <= md <= 701:     rm_min, rm_target, rm_max = 0, 0, 0
    elif 702 <= md <= 708:     rm_min, rm_target, rm_max = 10, 40, 80
    elif 709 <= md <= 715:     rm_min, rm_target, rm_max = 0, 0, 0
    elif 716 <= md <= 801:     rm_min, rm_target, rm_max = 20, 60, 100
    elif 802 <= md <= 830:     rm_min, rm_target, rm_max = 30, 50, 80
    else:                       rm_min, rm_target, rm_max = 0, 0, 0

    if 605 <= md <= 616:       rcc_min, rcc_target, rcc_max = 20, 50, 100
    elif 617 <= md <= 703:     rcc_min, rcc_target, rcc_max = 10, 40, 100
    elif 704 <= md <= 714:     rcc_min, rcc_target, rcc_max = 0, 0, 0
    elif 715 <= md <= 824:     rcc_min, rcc_target, rcc_max = 20, 80, 100
    elif 825 <= md <= 830:     rcc_min, rcc_target, rcc_max = 10, 40, 150
    else:                       rcc_min, rcc_target, rcc_max = 0, 0, 0
    
    # 记录前一天水位（用于日志）
    h_rm_prev = h_rm.copy()
    h_rcc_paddy_prev = h_rcc_paddy.copy()
    
    # --- 5.3 RM 水量平衡 ---
    h_rm[rm_mask] = np.maximum(0.0, h_rm[rm_mask] + P[rm_mask] - ET[rm_mask] - S_LOSS)
    drain_rm = np.zeros((rows, cols), dtype=np.float32)
    
    # 晒田期：仅暴雨排水
    sun_rm = rm_mask & (rm_target == 0)
    storm_rm = sun_rm & (P > STORM_THRESHOLD) & (h_rm > 0)
    drain_rm[storm_rm] = h_rm[storm_rm]
    h_rm[storm_rm] = 0.0
    
    # 灌溉
    irr_rm = rm_mask & (rm_target > 0) & (h_rm < rm_min)
    h_rm[irr_rm] = rm_target
    
    # 有雨安全排水
    dr_rain_rm = rm_mask & (rm_target > 0) & (P > 0) & (h_rm > rm_max)
    drain_rm[dr_rain_rm] = h_rm[dr_rain_rm] - rm_max
    h_rm[dr_rain_rm] = rm_max
    
    # --- 5.4 RCC 两箱水量平衡 ---
    h_rcc_paddy[rcc_mask] = np.maximum(0.0, h_rcc_paddy[rcc_mask] + P[rcc_mask] - ET[rcc_mask] - S_LOSS)
    vol_to_ditch = np.zeros((rows, cols), dtype=np.float32)
    
    # 晒田期：仅暴雨入沟
    sun_rcc = rcc_mask & (rcc_target == 0)
    storm_rcc = sun_rcc & (P > STORM_THRESHOLD) & (h_rcc_paddy > 0)
    vol_to_ditch[storm_rcc] += (h_rcc_paddy[storm_rcc] / 1000.0) * A_paddy
    h_rcc_paddy[storm_rcc] = 0.0
    
    # 灌溉
    irr_rcc = rcc_mask & (rcc_target > 0) & (h_rcc_paddy < rcc_min)
    h_rcc_paddy[irr_rcc] = rcc_target
    
    # 有雨安全排水（稻田→沟）
    dr_rain_rcc = rcc_mask & (rcc_target > 0) & (P > 0) & (h_rcc_paddy > rcc_max)
    vol_to_ditch[dr_rain_rcc] += ((h_rcc_paddy[dr_rain_rcc] - rcc_max) / 1000.0) * A_paddy
    h_rcc_paddy[dr_rain_rcc] = rcc_max
    
    # 沟渠平衡
    v_rain_d = (P / 1000.0) * A_ditch
    v_et_d = (ET / 1000.0) * A_ditch
    v_s_d_val = (S_LOSS / 1000.0) * A_ditch
    
    v_rcc_ditch[rcc_mask] = np.maximum(0.0,
        v_rcc_ditch[rcc_mask]
        + v_rain_d[rcc_mask]
        - v_et_d[rcc_mask]
        - v_s_d_val
        + vol_to_ditch[rcc_mask]
    )
    
    v_max_ditch = depth_to_volume_ditch_mm(RCC_DITCH_DEPTH_MAX, L_ditch)
    q_out = np.zeros((rows, cols), dtype=np.float32)
    q_out[rcc_mask] = np.maximum(0.0, v_rcc_ditch[rcc_mask] - v_max_ditch)
    v_rcc_ditch[rcc_mask] = np.minimum(v_rcc_ditch[rcc_mask], v_max_ditch)
    
    # --- 5.5 TN浓度动态 ---
    # 施肥
    for stage, cfg in FERTILIZER_CONFIG['rice'].items():
        if cfg['date'] is not None and md == cfg['date']:
            C0 = calculate_tn_initial_vec(nfer_data * cfg['ratio'], ph_data, som_data, stage)
            c_tn_rm[rm_mask] += C0[rm_mask]
            rice_stage = stage
    
    for stage, cfg in FERTILIZER_CONFIG['cray'].items():
        if cfg['date'] is not None and md == cfg['date']:
            C0 = calculate_tn_initial_vec(nfer_data * cfg['ratio'], ph_data, som_data, stage)
            c_tn_rcc[rcc_mask] += C0[rcc_mask]
            cray_stage = stage
    
    # 衰减
    c_tn_rm[rm_mask] *= np.exp(-TN_DECAY_K['rice'][rice_stage])
    c_tn_rcc[rcc_mask] *= np.exp(-TN_DECAY_K['cray'][cray_stage])
    c_tn_rm = np.maximum(0.001, c_tn_rm)
    c_tn_rcc = np.maximum(0.001, c_tn_rcc)
    
    # --- 5.6 负荷计算 ---
    daily_load_rm = np.zeros((rows, cols), dtype=np.float32)
    daily_load_rm[rm_mask] = drain_rm[rm_mask] * c_tn_rm[rm_mask] * 0.01
    accum_load_rm += daily_load_rm
    
    sys_drain_mm = np.zeros((rows, cols), dtype=np.float32)
    sys_drain_mm[rcc_mask] = q_out[rcc_mask] / A_total * 1000.0
    daily_load_rcc = np.zeros((rows, cols), dtype=np.float32)
    daily_load_rcc[rcc_mask] = sys_drain_mm[rcc_mask] * c_tn_rcc[rcc_mask] * 0.01
    accum_load_rcc += daily_load_rcc
    
    # ========================================
    # 🌟 DEBUG详细过程日志
    # ========================================
    if DEBUG_DAILY and day_idx < DEBUG_FIRST_N_DAYS:
        # 只统计掩膜内的像元
        rm_count = np.sum(rm_mask)
        rcc_count = np.sum(rcc_mask)
        
        # RM统计
        if rm_count > 0:
            rm_h_mean_prev = np.mean(h_rm_prev[rm_mask])
            rm_h_mean_now = np.mean(h_rm[rm_mask])
            rm_irr_num = np.sum(irr_rm)
            rm_drain_num = np.sum(drain_rm > 0)
            rm_drain_mean = np.mean(drain_rm[drain_rm > 0]) if rm_drain_num > 0 else 0
            rm_tn_mean = np.mean(c_tn_rm[rm_mask])
        else:
            rm_h_mean_prev = rm_h_mean_now = rm_irr_num = rm_drain_num = rm_tn_mean = 0
        
        # RCC统计
        if rcc_count > 0:
            rcc_h_mean_prev = np.mean(h_rcc_paddy_prev[rcc_mask])
            rcc_h_mean_now = np.mean(h_rcc_paddy[rcc_mask])
            rcc_irr_num = np.sum(irr_rcc)
            rcc_ditch_v_mean = np.mean(v_rcc_ditch[rcc_mask])
            rcc_out_num = np.sum(q_out > 0)
            rcc_tn_mean = np.mean(c_tn_rcc[rcc_mask])
        else:
            rcc_h_mean_prev = rcc_h_mean_now = rcc_irr_num = rcc_ditch_v_mean = rcc_out_num = rcc_tn_mean = 0
        
        print(f"\n{'─'*70}")
        print(f"📅 {date_str} (DOY={doy}, MMDD={md}) | 降雨:{p_status} | ET:{et_status}")
        print(f"   阈值: RM=[{rm_min},{rm_target},{rm_max}] RCC=[{rcc_min},{rcc_target},{rcc_max}]")
        print(f"   🌾 RM: 水位 {rm_h_mean_prev:.1f}→{rm_h_mean_now:.1f}mm | "
              f"灌溉{rm_irr_num}像元 | 排水{rm_drain_num}像元(均{rm_drain_mean:.1f}mm) | "
              f"TN={rm_tn_mean:.2f}")
        print(f"   🦐 RCC: 稻田水位 {rcc_h_mean_prev:.1f}→{rcc_h_mean_now:.1f}mm | "
              f"灌溉{rcc_irr_num}像元 | 沟体积={rcc_ditch_v_mean:.1f}m³ | "
              f"外排{rcc_out_num}像元 | TN={rcc_tn_mean:.2f}")
        if md in [605, 618, 707, 610]:
            print(f"   ⚡ 今日为施肥日！")
    
    # 简略日志（每10天或异常天气）
    elif day_idx % 10 == 0 or np.nanmax(P) > 50:
        rm_drain_num = np.sum(drain_rm > 0)
        rcc_out_num = np.sum(q_out > 0)
        print(f"📅 {date_str} | P:{np.nanmean(P):.2f} ET:{np.nanmean(ET):.2f} | "
              f"RM排水:{rm_drain_num}像元 RCC外排:{rcc_out_num}像元")

print("\n" + "=" * 70)

# ==========================================
# 6. 结果导出与统计
# ==========================================
print("\n" + "=" * 60)
print("📊 正在计算最终流失负荷并分别导出...")

driver = gdal.GetDriverByName("GTiff")

export_list = [
    {"name": "RM", "code": 1, "desc": "单季稻", "data": accum_load_rm},
    {"name": "RCC", "code": 3, "desc": "稻虾共作", "data": accum_load_rcc}
]

for item in export_list:
    code = item["code"]
    desc = item["desc"]
    arr = item["data"]
    mask = (mask_data == code)

    export_arr = np.where(mask, arr, -9999).astype(np.float32)
    valid = export_arr[export_arr != -9999]
    valid = valid[(valid > 0) & (~np.isnan(valid))]
    
    # ⭐️ 修改重点：移除 /1000.0，单位直接保留为 kg
    total_mass_arr = arr * PIXEL_AREA_HA 
    export_mass_arr = np.where(mask, total_mass_arr, -9999).astype(np.float32)

    print(f"\n【{desc} (mask={code})】")
    print(f"   掩膜像元总数: {np.sum(mask)}")
    
    if len(valid) > 0:
        print(f"   负荷>0的像元数: {len(valid)} ({len(valid)/np.sum(mask)*100:.1f}%)")
        print(f"   非零平均负荷: {np.mean(valid):.2f} ± {np.std(valid):.2f} kg/ha")
        print(f"   **最大负荷 (绝对最大值)**: {np.max(valid):.2f} kg/ha")
        
        valid_mass = export_mass_arr[export_mass_arr != -9999]
        valid_mass = valid_mass[(valid_mass > 0) & (~np.isnan(valid_mass))]
        # ⭐️ 修改重点：控制台打印的单位改为 kg
        print(f"   **区域累积总负荷**: {np.sum(valid_mass):.2f} kg")
    else:
        print("   ⚠️ 无有效负荷像元")

    # 导出 1：单位面积负荷图 (kg/ha)
    out_path = os.path.join(OUTPUT_DIR, f"TN_Load_{item['name']}_2022.tif")
    out_ds = driver.Create(out_path, cols, rows, 1, gdal.GDT_Float32)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(mask_ds.GetProjection())
    band = out_ds.GetRasterBand(1)
    band.WriteArray(export_arr)
    band.SetNoDataValue(-9999)
    band.ComputeStatistics(False) 
    out_ds = None
    print(f"   ✅ 已保存单位负荷: {out_path}")

    # 导出 2：总负荷量分布图 (kg)
    out_mass_path = os.path.join(OUTPUT_DIR, f"TN_TotalMass_{item['name']}_2022.tif")
    out_mass_ds = driver.Create(out_mass_path, cols, rows, 1, gdal.GDT_Float32)
    out_mass_ds.SetGeoTransform(gt)
    out_mass_ds.SetProjection(mask_ds.GetProjection())
    mass_band = out_mass_ds.GetRasterBand(1)
    mass_band.WriteArray(export_mass_arr)
    mass_band.SetNoDataValue(-9999)
    mass_band.ComputeStatistics(False)
    out_mass_ds = None
    # ⭐️ 修改重点：输出提示文字加入 kg 单位说明
    print(f"   ✅ 已保存总负荷量(kg): {out_mass_path}")

print("=" * 60)
print("🎉 面尺度耦合模拟与导出完成！")
print("   1. 若PyKrige未安装，已自动回退到RBF插值 (pip install pykrige 可启用克里金)")
print("   2. QGIS中加载结果后，请使用'单波段伪彩色'渲染以查看空间差异")
print("   3. 统计值为'非零像元均值'，与全区域均值不同")