# 2022点位模型源码快照

本目录保存2022年RM（水稻单作）与RCC（稻虾共作）的点位计算源码，覆盖栅格驱动浓度、alpha/k联合校准、背景投饵、人工观测重算、自然晒田、晒田控水和逐日ET计算。各节点的来源批次、功能和区域配置关系见 [点位模型谱系](../history/point-lineage.md)。

当前点位结果对应原项目 `.codex-work/qgis_point_2022/et_recompute_runs/20261022_213821`。本目录采用源码快照交付方式；原有路径推导、运行指针、输入断言和正式文件哈希保护均保留。执行这些入口需要恢复原项目的目录布局和配套本地数据。

## 文件职责

| 源码 | 职责 |
|---|---|
| run_point_2022.py | 点位坐标和背景栅格提取、施肥C0、逐日浓度及基础结果 |
| observation_input.py、bounded_k.py、result_report.py | 观测读取、受约束k率定、结果整理 |
| run_joint_point_2022.py | 第一次事件alpha/k联合校准及后续事件评价 |
| run_feed_background_2022.py | 共同背景和RCC投饵浓度附加项 |
| run_manual_observations.py | 人工点选CSV读取、日期和评价角色、参数重算 |
| recompute_natural_drydown.py | 零目标期停止补灌、自然消退与超容量溢流 |
| recompute_drying_control.py、drying_control.py | 指定晒田期排至0及RM7/9—15阶段阈值 |
| recompute_with_et.py | 当前逐日ET田面水量、固定参数TN及出口负荷重算 |
| build_validation_delivery.py | 田面/沟渠水量、观测列对齐和负荷数据准备 |
| compare_original_water_rules.py、run_legacy_water_observations.py、run_water_level_2022.py | 旧水量规则及观测来源追溯 |
| config.json | 点位位置、回归系数和背景输入配置；各批次日历以其冻结事件表为准 |

## 目录与环境合同

源码原位置为 `<项目根>/.codex-work/qgis_point_2022/`。脚本通过 `HERE.parents[1]` 或 `Path(__file__).resolve().parents[2]` 推导项目根；部分脚本顶部还固定了原项目绝对路径。将本目录直接作为任意克隆位置的运行目录，会改变这些路径的含义。

对应本机项目根为 `E:\#岑俊毅\2.论文\2.稻虾综合种养`。实际复现应在独立的项目副本中恢复同样的 `.codex-work/qgis_point_2022/` 层级，按源码合同核对项目根和全部输入指向，使输入、输出及指针均定位到该副本，再执行对应节点。保留生产项目的正式成果及指针。恢复历史版本时使用该批次保存的源码和配置，当前源码同时用于标明现行功能状态。

环境依赖为Python 3及相应入口使用的GDAL/NumPy、openpyxl、Matplotlib；QGIS环境可提供GDAL与QGIS交互能力。历史水量入口还导入原项目 `模型/2026.6.27/python计算/model_v6` 下的 `management.py`、`regional_hydrology.py` 等模块，并读取旧水量V3源码和观测表。

## 当前ET入口的本地输入

`recompute_with_et.py` 需要以下相互配套的文件：

1. `drying_control_latest.json` 及其指向批次 `drying_control_runs/20261022_110405/daily_full_precision.csv`，提供前序逐日输入和管理阈值。
2. `active_tn_run.json` 指向的 `et_recompute_runs/20261022_213821/tn/`，包含 `config.json`、`event_parameters.csv`、`daily_components.csv`、`observations.csv`，以及存在时的 `calendar_provenance.json`。前四项参与重算和对照，日历来源文件随结果保存。
3. 本目录 `config.json`；其中回归系数用于校验C0，坐标用于ET像元读取。配套模型事件采用冻结 `tn/event_parameters.csv`；示例config里的事件日期不替代它。
4. 原项目 `模型/2026.9.3/模型背景数据/蒸散发/ET_2022_point_20220605_20220923.csv` 和111个ET栅格。表列 `date`、`ET_file`、`ET_mm_day` 需逐日对应；ET_file为本地文件路径，栅格单位、scale和offset参与校验。
5. 原项目 `模型/2026.9.3/提取数据/点位验证/` 下的 `水量平衡.csv`、`TN模拟对齐数据.csv`、`负荷计算.xlsx`，以及被接受基准批次的 `final/` 对应文件。
6. `build_validation_delivery.py` 读取的 `2022旧版观测水位模拟_20261019_134725/旧版水位观测值.csv`；`模型/2026.6.27/毕业论文/验证终稿/` 下的水量、TN列标题模板CSV和 `负荷/负荷V2.xlsx`。这些本地模板和观测属于运行合同。

联合校准与人工观测入口另需其指定观测工作簿/CSV、`joint_runs/20261008_221451_815334` 冻结数据及背景栅格提取记录。年度施氮栅格 `Nfer-2018` 为ENVI二进制，需要旁边的 `Nfer-2018.hdr`；应一并保留辅助元数据。观测、冻结运行数据、模板和气象栅格由原项目本地数据集提供。

## 20261022_213821核对与恢复

当前冻结批次的校验依据包括 `manifest.json`、`independent_verification.json`、`tn/calendar_provenance.json`、`delivery_verification.json` 和 `final/` 三份成果。该批次222行田面水量、306行浓度和111天出口负荷在2026-10-26进行了只读独立重放；RM/RCC负荷分别为7.115176870522225、4.030369093045514 kg/ha。

2026-10-26检查时，正式水量和TN两CSV与该批次 `final/` 文件SHA256一致。正式 `负荷计算.xlsx` SHA256为 `c9822bb0bb53498d980088646f11ec9ed006e43423a7d0db913df00d87ea2fef`，冻结 `final/负荷计算.xlsx` 为 `c8334442086d899c7bc826209032bdac66a5f2c471078bd839c9fa018a3bbee6`。此项是文件级来源差异，原入口会在正式文件保护处停止。

恢复顺序如下：

1. 先确定要复现的完整批次，保存当前正式数据、运行指针和哈希记录，在独立项目副本中恢复其源码和配套输入。
2. 对照该批次清单与 `final/`，分别核对三份成果、输入表、事件日历和指针。对于工作簿差异，核对工作表内容、公式、数值、保存记录及来源；文件哈希本身仅用于识别文件版本。
3. 需要复现213821时，在副本内恢复该批次配套的 `final/` 数据和指针；需要评估当前工作簿时，先确认其来源和适用批次，再恢复该批次完整数据集。使参考成果与所选冻结数据同属一个经核对的运行状态。
4. 保留源码原有哈希断言和接受基准逻辑。输入状态与所选基准匹配后，继续执行对应流程；新计算、缓存、日志和检查记录存入副本项目 `.codex-work/`，检查结果后再决定成果采用范围。

`recompute_with_et.py` 在导入时读取指针，主流程新建运行目录并在末尾更新ET指针；部分历史入口在顶层即创建文件夹。应先完成上述数据和路径核对，再加载或执行入口。本页因此按恢复合同说明使用方式。

## 结果解释

点位水量和出口负荷时段为2022年6月5日至9月23日；TN组件还保存6月至10月的153天序列。RM按0.11 ha、RCC按0.31 ha系统面积归一化，质量公式为 `M_kg = 0.001 × V_m3 × C_mg/L`。RCC田面入沟为内部转移，系统外排取沟渠出口。

当前点位模型以田面浓度代表RCC出口TN，用陆地ET代理沟渠耗水，使用经验施肥、背景和投饵项。参数率定、历法选择和全期拟合包含部分相同观测。区域 `paper_2022` 采用逐像元背景输入、RM普通无雨日保水/雨日至少120 mm上限、RCC沟400/400 mm；`legacy_2022` 的RM沿阶段雨日上限、RCC沟800/900 mm。点位与区域各自对应其输入空间、管理规则和评价证据。
