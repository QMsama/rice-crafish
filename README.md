# 稻虾TN模型 · 2024主线

`model/2024`是2024年的稳定主线，维护2024区域模型、管理日历、QGIS入口及历史情景运行记录。本分支代码位于[models/2024](models/2024/)。

## 开发与合并

从最新`model/2024`建立`feat/2024-功能`分支，完成开发、验证、版本记录和审阅，再通过PR以merge commit合并回`model/2024`。功能分支起点与PR目标均为本年度主线，规则见[DEVELOPMENT.md](DEVELOPMENT.md)和[BRANCH_POLICY.json](BRANCH_POLICY.json)。

## 运行与追溯

在仓库根目录先进入`models/2024`，再按该目录README准备数据并运行。该README中的“本分支根目录”和脚本完整路径均指`models/2024`模型包目录。源码、配置、输入阈值、历史记录与VERIFICATION由该模型目录维护，SOURCE_MANIFEST路径相对于该目录。

[另一年度主线](https://github.com/QMsama/rice-crafish/tree/model/2022)单独维护其模型和功能。年度入口及归档见[仓库导航](https://github.com/QMsama/rice-crafish/tree/main)。原仓库文件树保存在[archive/legacy-20261026](archive/legacy-20261026/)，历史提交持续保留。
