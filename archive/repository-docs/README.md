# 稻虾TN模型 · 年度主线导航

本仓库有两条独立的模型主线，每年的功能分别开发、验证和合并。

| 年度主线 | 正式代码 | 功能合并目标 |
|---|---|---|
| [model/2022](https://github.com/QMsama/rice-crafish/tree/model/2022) | [2022模型](https://github.com/QMsama/rice-crafish/tree/model/2022/models/2022) | model/2022 |
| [model/2024](https://github.com/QMsama/rice-crafish/tree/model/2024) | [2024模型](https://github.com/QMsama/rice-crafish/tree/model/2024/models/2024) | model/2024 |

`main`维护年份导航、仓库说明、归档入口及2026-10-26固定参考快照。使用最新正式模型时切换到对应年度主线，再进入`models/年份`目录。各年度源码、参数、运行说明和版本更新由其主线维护。

main中的`models/2022`、`models/2024`保留为2026-10-26参考快照，文件哈希与来源记录固定；持续开发和功能合并分别在上表两条年度主线开展。

## 功能工作流

- 2022：model/2022 → feat/2022-功能 → 验证和审阅 → PR合并回model/2022。
- 2024：model/2024 → feat/2024-功能 → 验证和审阅 → PR合并回model/2024。

PR采用merge commit，保留每条年度线上的功能分叉与汇合记录。详细规则见[DEVELOPMENT.md](DEVELOPMENT.md)；机器可读目标见[BRANCH_POLICY.json](BRANCH_POLICY.json)。共用算法分别在两条年度主线上适配和验证。

## 归档与追溯

- [原仓库归档](https://github.com/QMsama/rice-crafish/tree/archive/legacy-20261026)：固定原提交e6fb108，原文件树也保存在[archive/legacy-20261026](archive/legacy-20261026/)中。
- [2026-10-26仓库快照](https://github.com/QMsama/rice-crafish/tree/archive/main-20261026)：固定此前main提交f79b27c，保存当时完整目录及提交历史。
- 各年度模型的CHANGELOG、VERSION、SOURCE_MANIFEST、history和VERIFICATION记录功能变化、运行批次、源码哈希和检查结果。

原始观测、逐日栅格与运行缓存由各年度模型的数据合同指定。计算复现与独立实测评价分别报告。
