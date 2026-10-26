# 稻虾TN模型

`main`保存已完成验证并合并的正式代码。2022、2024模型分别放在独立目录，按年份保留配置、功能谱系和运行记录。

| 代码目录 | 功能 | 年度集成分支 |
|---|---|---|
| [models/2022](models/2022/) | 2022当前/历史区域配置、点位模型源码谱系、ET/晒田功能及关键源区识别 | [model/2022](https://github.com/QMsama/rice-crafish/tree/model/2022) |
| [models/2024](models/2024/) | 2024当前区域模型、管理日历、QGIS入口与14个历史情景运行摘要 | [model/2024](https://github.com/QMsama/rice-crafish/tree/model/2024) |

## 使用模型

先进入对应模型目录，再按照该目录的README准备外部数据并运行。例如在仓库根目录的PowerShell中：

```powershell
Set-Location .\models\2022
& 'C:\Program Files\QGIS 3.44.12\bin\python-qgis-ltr.bat' .\run_model.py --preset paper_2022 --root 'E:\#岑俊毅\2.论文\2.稻虾综合种养'
```

运行2024时，在仓库根目录进入`models/2024`，配置为`current_2024`。模型目录内README所说的运行根目录，指该年份的模型目录。SOURCE_MANIFEST中的发布路径也相对于所在年份目录。

区域模型的运行、缓存与清单保存在数据项目的`.codex-work/regional_reproduction`。2022关键源区工具通过显式数据根运行；点位源码快照按其README恢复配套批次输入。对应数据合同和核验记录位于各年份目录。

## 功能开发与合并

每个功能建立独立分支，例如`feat/2022-natural-drydown`。开发、检查和代码提交完成后创建PR，将已验证功能合并到`main`。PR采用merge方式，保留功能分支的提交及汇合记录。操作规则见[DEVELOPMENT.md](DEVELOPMENT.md)。

年度分支保留本次对应年份的集成记录，可用于开发和版本对照。继续在年度分支工作前，先同步最新main。普通单功能开发从最新main创建feat分支，直接通过PR合入main。

## 历史与追溯

各模型目录的CHANGELOG、VERSION、SOURCE_MANIFEST、history和VERIFICATION分别记录功能变化、来源批次、代码哈希与检查结果。仓库级变更见[CHANGELOG.md](CHANGELOG.md)。

原仓库完整文件树保存在[archive/legacy-20261026](archive/legacy-20261026/)，并由[同名归档分支](https://github.com/QMsama/rice-crafish/tree/archive/legacy-20261026)固定。原提交历史保留，归档代码按其历史环境与数据条件解释。
