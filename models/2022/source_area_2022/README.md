# 2022年TN关键源区识别

本工具从2022年RM、RCC区域TN负荷和像元质量结果计算相对高贡献像元，完成负荷—面积经验曲线、县市统计、原网格分区与地图输出。三个计算脚本沿用源算法；统一入口负责数据路径、独立输出目录和Python环境。

## 运行环境

使用带GDAL/OGR/OSR、NumPy和matplotlib的Python。推荐QGIS自带Python；统一入口通过当前 `sys.executable` 顺序启动三个脚本，继承同一环境。

```powershell
& 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat' '.\source_area_2022\run_source_area.py' --root 'E:\project-data'
```

将QGIS安装位置、脚本位置和数据根替换为实际路径。数据可存放在仓库外；`--root` 指向数据树根目录。

## 数据约定

`--root` 下提供四幅栅格，单位分别为kg/ha和kg/像元：

```text
模型/2026.9.3/面上推广/TN_Load_RM_2022.tif
模型/2026.9.3/面上推广/TN_Load_RCC_2022.tif
模型/2026.9.3/面上推广/TN_TotalMass_RM_2022.tif
模型/2026.9.3/面上推广/TN_TotalMass_RCC_2022.tif
```

负荷和质量栅格应使用相同有效掩膜、行列、投影和地理变换，米制投影的像元面积由地理变换计算。有效零负荷保留，NoData和非有限值按源算法处理。

县界默认读取 `模型/2026.6.27/毕业论文/制图` 下找到的第一个 `县.shp`。为明确数据来源，建议通过 `--county-boundary` 指定完整shapefile路径；字段为 `县代码`、`县名`、`市名`、`省名`。源流程的空间初筛范围使用经纬度，因此县界输入应使用WGS84经纬度坐标；统计前县界会投影至负荷栅格坐标系。

研究区轮廓默认读取 `模型/2026.9.3/模型背景数据/江汉平原矢量/江平原t.shp`。`--study-boundary` 可指定其他位置。两个参数的相对路径均相对 `--root` 解析；shapefile须保留shp、shx、dbf、prj等配套文件。

```powershell
& 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat' '.\source_area_2022\run_source_area.py' --root 'E:\project-data' --county-boundary 'boundaries\县.shp' --study-boundary 'boundaries\江平原t.shp'
```

绘图默认加载系统微软雅黑字体，字体文件可用 `--font` 指定；字体不可用时采用DejaVu Sans。DejaVu Sans对中文字符的覆盖取决于本机字体环境。

## 算法和阈值

每个模式独立计算 `U_i=M_i/A_i` 和面积加权均值 `mean=ΣM_i/ΣA_i`。像元相对贡献斜率为 `s_i=U_i/mean`。源算法的分级为：

| 编码 | 类别 | 条件 |
|---|---|---|
| 0 | 有效范围外 | NoData |
| 1 | 其他有效种植区 | s≤1 |
| 2 | 次关键源区 | 1<s≤2 |
| 3 | 关键源区 | s>2 |

经验累计曲线按单位面积负荷降序排列，展示面积和质量累计贡献。阈值1和2为本流程采用的相对贡献分级界限。县市归属使用原始网格像元中心；县市关键区负荷贡献以本模式全域关键区质量为分母，县内关键区面积比例以县内本模式有效面积为分母。

识别对象为2022-06-05至2022-09-23固定管理情景下田块系统出口的相对高贡献区域。模型情景与空间统计的一致性核验分别保留记录；独立实测验证需要对应的监测证据。

## 输出与复现

每轮输出固定写入 `--root/.codex-work/source_area_runs/时间_UUID/`，完整保留三步各自所需层级。控制台首先显示本轮 `RUN_DIRECTORY`，完成后显示 `COMPLETED_RUN_DIRECTORY`。

```text
run_manifest.json
load_area_figure/figure_data.json
load_area_figure/RM_curve.csv
load_area_figure/RCC_curve.csv
source_area_map/agent_county/county_source_statistics.json
source_area_map/agent_county/county_source_statistics.csv
source_area_map/agent_county/selected_counties_projected.gpkg
source_area_map/TN_source_class_RM_2022.tif
source_area_map/TN_source_class_RCC_2022.tif
source_area_map/map_verification.json
```

同目录另有曲线和分布图及县代码栅格等运行产物。`run_manifest.json` 保存输入与脚本SHA-256、Python解释器和三个步骤退出状态。分类脚本保存后重新打开分类栅格，并检查关键像元数与曲线、县市统计一致。运行前原始栅格与真实观测由使用者单独准备。

采用该2022参考数据时，完整运行的参考统计如下；阈值实际计算保留完整精度。

| 模式 | 平均负荷 kg/ha | 关键区阈值 kg/ha | 全域质量 t | 关键像元数 |
|---|---:|---:|---:|---:|
| RM | 2.836984784 | 5.673969568 | 1615.540246454 | 11658 |
| RCC | 3.882241606 | 7.764483212 | 1314.639748315 | 3501 |

参考数据的县界覆盖率两模式均为100%，重叠和未归属有效像元均为0。替换输入后应重新检查这些统计与空间覆盖。
