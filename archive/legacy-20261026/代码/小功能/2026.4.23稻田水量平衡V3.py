import numpy as np
import matplotlib.pyplot as plt
import os
import math
import datetime
import csv
import glob
from osgeo import gdal, ogr, osr

class ModelConfig:
    # 🌟 路径参数
    SHP_PATH = r"D:\桌面文件\毕业论文\制图\点位图\江平原t.shp"
    FOLDER_PATH = r"D:\桌面文件\mode\rain\rain daily tiff\2022"
    ET_FOLDER_PATH = r"D:\桌面文件\mode\蒸散发\T_2022_daily_tiff"
    
    OUTPUT_CSV_PATH = r"D:\#data\Python\模型验证\V5\水量平衡验证\水量平衡.csv"
    OBSERVED_CSV_PATH = r"D:\#data\Python\模型验证\V4\田面水.csv" 
    
    # 🌟 坐标与模拟参数
    POINT_X = 112.6166  
    POINT_Y = 30.3833   
    START_DATE = "2022-06-05"
    END_DATE = "2022-09-23"

    # 🌟 面积与物理参数
    AREA_RM = 1100.0             
    AREA_RCC_TOTAL = 3100.0      
    AREA_RCC_DITCH_TOP = 930.0   
    AREA_RCC_PADDY = 2170.0      
    LENGTH_DITCH = 285.0         
    DITCH_COEF_B = 0.9           
    DITCH_COEF_A = 1.1667        
    
    DEFAULT_ET = 5.0                     
    S = 2.0                      
    RCC_DITCH_NORMAL = 800.0  
    RCC_DITCH_MAX = 900.0        

# ==========================================
# 工具函数：对齐提取与单位还原
# ==========================================
def find_daily_file(folder, year, doy):
    if not os.path.exists(folder): return None
    patterns = [f"*{year}*{doy:03d}*.tif", f"*{year}*Day_{doy:03d}*.tif"]
    for p in patterns:
        matches = glob.glob(os.path.join(folder, p))
        if matches: return matches[0]
    return None

def get_pixel_value_aligned(tif_path, shp_path, lon, lat):
    if tif_path is None or not os.path.exists(tif_path): return None
    gdal.PushErrorHandler('CPLQuietErrorHandler')
    vrt_ds = gdal.Warp('', tif_path, format='VRT', cutlineDSName=shp_path, cropToCutline=True,
                       srcSRS='EPSG:4326', dstSRS='EPSG:4326', resampleAlg=gdal.GRA_Bilinear)
    gdal.PopErrorHandler()
    if vrt_ds is None: return None
    gt = vrt_ds.GetGeoTransform()
    col = int((lon - gt[0]) / gt[1])
    row = int((lat - gt[3]) / gt[5])
    if col < 0 or col >= vrt_ds.RasterXSize or row < 0 or row >= vrt_ds.RasterYSize: return None
    band = vrt_ds.GetRasterBand(1)
    val_array = band.ReadAsArray(col, row, 1, 1) 
    if val_array is not None:
        raw_val = float(val_array[0, 0])
        return raw_val / 1000.0 if abs(raw_val) > 100 else raw_val
    return None

def depth_to_volume_ditch(h_mm, cfg):
    h_m = h_mm / 1000.0
    return cfg.LENGTH_DITCH * (cfg.DITCH_COEF_B * h_m + cfg.DITCH_COEF_A * h_m**2)

def volume_to_depth_ditch(v_m3, cfg):
    a, b, c = cfg.DITCH_COEF_A, cfg.DITCH_COEF_B, -(v_m3 / cfg.LENGTH_DITCH)
    h_m = (-b + math.sqrt(b**2 - 4*a*c)) / (2*a)
    return h_m * 1000.0

def read_observed_data(filepath, year):
    observed = {}
    if not os.path.exists(filepath): return observed
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_date = row.get('日期', '').strip()
            if raw_date.isdigit():
                m, d = int(raw_date) // 100, int(raw_date) % 100
                observed[f"{year}-{m:02d}-{d:02d}"] = {
                    "实测_RM_水位_mm": row.get('水稻mm', ''),
                    "实测_RCC_稻田水位_mm": row.get('稻虾mm', '')
                }
    return observed

# ==========================================
# 核心模拟逻辑
# ==========================================
def run_unified_simulation(cfg, observed_data=None):
    if observed_data is None: observed_data = {}
    
    rm_h, rcc_paddy_h = 0.0, 0.0
    rcc_ditch_v = depth_to_volume_ditch(cfg.RCC_DITCH_NORMAL, cfg)
    
    start_date = datetime.datetime.strptime(cfg.START_DATE, "%Y-%m-%d")
    end_date = datetime.datetime.strptime(cfg.END_DATE, "%Y-%m-%d")
    delta_days = (end_date - start_date).days + 1
    daily_records = []
    
    print(f"🚀 模拟启动，正在同步降雨、蒸散发并执行水位管理...")

    for day_index in range(delta_days):
        current_date = start_date + datetime.timedelta(days=day_index)
        doy = current_date.timetuple().tm_yday
        date_str = current_date.strftime("%Y-%m-%d")
        current_md = current_date.month * 100 + current_date.day
        
        # 1. 提取降雨和蒸散发
        p_file = find_daily_file(cfg.FOLDER_PATH, current_date.year, doy)
        P = get_pixel_value_aligned(p_file, cfg.SHP_PATH, cfg.POINT_X, cfg.POINT_Y) or 0.0
        et_file = find_daily_file(cfg.ET_FOLDER_PATH, current_date.year, doy)
        daily_et = get_pixel_value_aligned(et_file, cfg.SHP_PATH, cfg.POINT_X, cfg.POINT_Y) or cfg.DEFAULT_ET

        # 2. 水位控制阈值设置
        # RM 阈值
        if 605 <= current_md <= 615: rm_h_min, rm_h_target, rm_hd_max = 20, 40, 80
        elif 616 <= current_md <= 628: rm_h_min, rm_h_target, rm_hd_max = 30, 50, 100
        elif 629 <= current_md <= 701: rm_h_min, rm_h_target, rm_hd_max = 0, 0, 0
        elif 702 <= current_md <= 709: rm_h_min, rm_h_target, rm_hd_max = 10, 40, 80
        elif 710 <= current_md <= 715: rm_h_min, rm_h_target, rm_hd_max = 0, 0, 0
        elif 716 <= current_md <= 801: rm_h_min, rm_h_target, rm_hd_max = 20, 60, 100
        elif 802 <= current_md <= 830: rm_h_min, rm_h_target, rm_hd_max = 30, 50, 80
        else: rm_h_min, rm_h_target, rm_hd_max = 0, 0, 0

        # RCC 阈值
        if 605 <= current_md <= 618: rcc_h_min, rcc_h_target, rcc_hd_max = 20, 50, 70
        elif 619 <= current_md <= 703: rcc_h_min, rcc_h_target, rcc_hd_max = 10, 30, 100
        elif 704 <= current_md <= 714: rcc_h_min, rcc_h_target, rcc_hd_max = 0, 0, 0
        elif 715 <= current_md <= 824: rcc_h_min, rcc_h_target, rcc_hd_max = 30, 70, 100
        elif 825 <= current_md <= 830: rcc_h_min, rcc_h_target, rcc_hd_max = 20, 50, 150
        else: rcc_h_min, rcc_h_target, rcc_hd_max = 0, 0, 0

        # 3. RM 模拟过程
        rm_irr, rm_drain = 0.0, 0.0
        rm_h = max(0, rm_h + P - daily_et - cfg.S)
        if rm_h_target == 0:
            rm_drain, rm_h = rm_h, 0
        else:
            if rm_h < rm_h_min: rm_irr, rm_h = rm_h_target - rm_h, rm_h_target
            if P > 0 and rm_h > rm_hd_max: rm_drain, rm_h = rm_h - rm_hd_max, rm_hd_max
            elif P == 0 and rm_h > rm_h_target: rm_drain, rm_h = rm_h - rm_h_target, rm_h_target

        # 4. RCC 模拟过程
        rcc_irr, rcc_paddy_to_ditch_vol = 0.0, 0.0
        rcc_paddy_h = max(0, rcc_paddy_h + P - daily_et - cfg.S)
        if rcc_h_target == 0:
            rcc_paddy_to_ditch_vol, rcc_paddy_h = (rcc_paddy_h / 1000.0) * cfg.AREA_RCC_PADDY, 0
        else:
            if rcc_paddy_h < rcc_h_min: rcc_irr, rcc_paddy_h = rcc_h_target - rcc_paddy_h, rcc_h_target
            if P > 0 and rcc_paddy_h > rcc_hd_max: 
                rcc_paddy_to_ditch_vol, rcc_paddy_h = ((rcc_paddy_h - rcc_hd_max)/1000.0) * cfg.AREA_RCC_PADDY, rcc_hd_max
            elif P == 0 and rcc_paddy_h > rcc_h_target:
                rcc_paddy_to_ditch_vol, rcc_paddy_h = ((rcc_paddy_h - rcc_h_target)/1000.0) * cfg.AREA_RCC_PADDY, rcc_h_target

        # 5. 🌟 重点修改：RCC 沟渠水量平衡 (当超过900mm时，排水至800mm)
        current_h_m = volume_to_depth_ditch(rcc_ditch_v, cfg) / 1000.0
        current_surface_area = cfg.LENGTH_DITCH * (cfg.DITCH_COEF_B + 2 * cfg.DITCH_COEF_A * current_h_m)
        v_rain_ditch = (P / 1000.0) * cfg.AREA_RCC_DITCH_TOP
        v_et_ditch = (daily_et / 1000.0) * current_surface_area
        v_s_ditch = (cfg.S / 1000.0) * current_surface_area
        
        # 加上降雨、扣除蒸散发和渗漏、加上稻田排过来的水，算出沟渠当前的总体积
        rcc_ditch_v = max(0, rcc_ditch_v + v_rain_ditch - v_et_ditch - v_s_ditch + rcc_paddy_to_ditch_vol)
        
        max_vol = depth_to_volume_ditch(cfg.RCC_DITCH_MAX, cfg)       # 900mm 对应的体积
        normal_vol = depth_to_volume_ditch(cfg.RCC_DITCH_NORMAL, cfg) # 800mm 对应的体积
        
        # 判断排水：一旦超过 900mm，则排空至 800mm
        if rcc_ditch_v > max_vol:
            q_rcc_ditch = rcc_ditch_v - normal_vol # 排水量 = 当前体积 - 800mm时的体积
            rcc_ditch_v = normal_vol               # 沟渠水量重置为 800mm时的体积
            rcc_ditch_h = cfg.RCC_DITCH_NORMAL     # 沟渠水位重置为 800mm
        else:
            q_rcc_ditch = 0.0
            rcc_ditch_h = volume_to_depth_ditch(rcc_ditch_v, cfg)

        # 记录
        obs_rm = observed_data.get(date_str, {}).get("实测_RM_水位_mm", "")
        obs_rcc = observed_data.get(date_str, {}).get("实测_RCC_稻田水位_mm", "")
        daily_records.append({
            "日期": date_str, "降雨量_P_mm": round(P, 2), "蒸散发_ET_mm": round(daily_et, 3),
            "RM_水位_mm": round(rm_h, 2), "实测_RM_水位_mm": obs_rm, "RM_灌溉量_mm": round(rm_irr, 2),
            "RM_排水量_mm": round(rm_drain, 2),
            "RCC_稻田水位_mm": round(rcc_paddy_h, 2), "实测_RCC_稻田水位_mm": obs_rcc,
            "RCC_稻田灌溉量_mm": round(rcc_irr, 2),
            "RCC_沟渠水位_mm": round(rcc_ditch_h, 2), "RCC_稻田直排量_m3": round(rcc_paddy_to_ditch_vol, 2),
            "RCC_沟渠排出量_m3": round(q_rcc_ditch, 2), "RCC_系统总排出量_m3": round(q_rcc_ditch, 2)
        })

    return daily_records

def export_to_csv(records, output_path):
    if not records: return
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    keys = records[0].keys()
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(records)
    print(f"✅ 模拟完成！数据已成功保存至: {output_path}")

# ==========================================
# 画图与评估模块
# ==========================================
def plot_and_evaluate(daily_records):
    print("📊 正在提取实测匹配数据并生成拟合图...")
    
    plt.rcParams['font.sans-serif'] = ['SimHei'] 
    plt.rcParams['axes.unicode_minus'] = False

    dates_rm, v_rm_sim, v_rm_obs, p_rm = [], [], [], []
    dates_rcc, v_rcc_sim, v_rcc_obs, p_rcc = [], [], [], []

    for row in daily_records:
        date_str = row["日期"]
        _, m, d = date_str.split('-')
        label_date = f"{int(m)}-{int(d)}"
        
        o_rm = row["实测_RM_水位_mm"]
        if o_rm != "":
            dates_rm.append(label_date)
            v_rm_sim.append(row["RM_水位_mm"])
            v_rm_obs.append(float(o_rm))
            p_rm.append(row["降雨量_P_mm"])

        o_rcc = row["实测_RCC_稻田水位_mm"]
        if o_rcc != "":
            dates_rcc.append(label_date)
            v_rcc_sim.append(row["RCC_稻田水位_mm"])
            v_rcc_obs.append(float(o_rcc))
            p_rcc.append(row["降雨量_P_mm"])

    def calc_metrics(sim, obs):
        if not sim or not obs: return 0.0, 0.0
        s, o = np.array(sim), np.array(obs)
        rmse = np.sqrt(np.mean((s - o)**2))
        ss_res = np.sum((o - s)**2)
        ss_tot = np.sum((o - np.mean(o))**2)
        r2 = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        return r2, rmse

    rm_r2, rm_rmse = calc_metrics(v_rm_sim, v_rm_obs)
    rcc_r2, rcc_rmse = calc_metrics(v_rcc_sim, v_rcc_obs)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
    
    x_rm = range(len(dates_rm))
    ax1.plot(x_rm, v_rm_obs, color='#AAAAAA', linestyle='--', linewidth=1.5, label='观测值')
    ax1.plot(x_rm, v_rm_sim, color='red', marker='.', linestyle='none', markersize=8, label='预测值')
    
    ax1.set_title(f"水稻单作 (RM) 田面水位拟合\n$R^2$ = {rm_r2:.3f}, RMSE = {rm_rmse:.2f} mm")
    ax1.set_ylabel("田面水位（mm）")
    ax1.set_xticks(x_rm)
    ax1.set_xticklabels(dates_rm, rotation=90)
    ax1.legend(loc='lower left')
    ax1.grid(True, linestyle=':', alpha=0.3)

    ax1_p = ax1.twinx()
    ax1_p.bar(x_rm, p_rm, color='#7cb5ec', width=0.4, alpha=0.7, label='降雨量')
    ax1_p.set_ylabel("降雨量（mm）")
    ax1_p.set_ylim(max(p_rm) * 3 if max(p_rm) > 0 else 100, 0)
    ax1_p.legend(loc='upper right')

    x_rcc = range(len(dates_rcc))
    ax2.plot(x_rcc, v_rcc_obs, color='#AAAAAA', linestyle='--', linewidth=1.5, label='观测值')
    ax2.plot(x_rcc, v_rcc_sim, color='red', marker='.', linestyle='none', markersize=8, label='预测值')
    
    ax2.set_title(f"稻虾共作 (RCC) 稻田水位拟合\n$R^2$ = {rcc_r2:.3f}, RMSE = {rcc_rmse:.2f} mm")
    ax2.set_ylabel("田面水位（mm）")
    ax2.set_xticks(x_rcc)
    ax2.set_xticklabels(dates_rcc, rotation=90)
    ax2.legend(loc='lower left')
    ax2.grid(True, linestyle=':', alpha=0.3)

    ax2_p = ax2.twinx()
    ax2_p.bar(x_rcc, p_rcc, color='#7cb5ec', width=0.4, alpha=0.7, label='降雨量')
    ax2_p.set_ylabel("降雨量（mm）")
    ax2_p.set_ylim(max(p_rcc) * 3 if max(p_rcc) > 0 else 100, 0)
    ax2_p.legend(loc='upper right')

    plt.tight_layout()
    plt.show()

# ==========================================
# 运行主程序 
# ==========================================
cfg = ModelConfig()

simulation_year = cfg.START_DATE.split('-')[0]
observed_data = read_observed_data(cfg.OBSERVED_CSV_PATH, simulation_year)

simulation_results = run_unified_simulation(cfg, observed_data)
export_to_csv(simulation_results, cfg.OUTPUT_CSV_PATH)
plot_and_evaluate(simulation_results)