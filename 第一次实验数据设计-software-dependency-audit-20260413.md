---
title: software-dependency-audit 第一次实验数据设计
date: 2026-04-13
tags:
  - APO-SkillsMD
  - SkillsBench
  - software-dependency-audit
  - 实验设计
  - pilot
status: v1
---

# software-dependency-audit 第一次实验数据设计

这份文档的目标不是定义整篇论文的最终实验表，而是给 `APO-SkillsMD` 的**第一个正式单任务 pilot** 一个可直接执行的设计版本。这个 pilot 的核心作用有三点：

1. 跑通从 `P0 初始化 → Trace 评估 → 变异/交叉 → Pareto 选择 → 最终 skill` 的完整闭环。
2. 验证“从冗余池出发的进化”是否能超越**进化前最好的初始技能**。
3. 用一个 SkillsBench 正式任务建立后续和 `EvoSkills` 做更大规模对比的实验模板。

---

## 1. 为什么选 `software-dependency-audit`

作为第一个正式 pilot，这个任务比 `exoplanet-detection-period` 更稳，原因如下：

- **任务边界清楚**：输入是 `/root/package-lock.json`，输出是 `/root/security_audit.csv`，验收对象非常明确。
- **验证器是确定性的**：适合做 trace-guided 进化，不需要 LLM judge。
- **技能结构天然模块化**：这个任务几乎天然分成三段：
  1. 发现漏洞
  2. 补全 CVSS / severity / fixed version 信息
  3. 生成最终 CSV
- **SkillsBench 官方已经证明它对 skills 敏感**：论文把它列在“skills 影响最大”的任务前十里，`No Skills = 8.6%`，`With Skills = 69.4%`，提升 `+60.9pp`。
- **但仍有明显提升空间**：官方并没有把它推到接近 100%，因此适合做首个优化实验。
- **EvoSkills 没公开它在这个具体任务上的单任务结果**：这意味着你不会一上来就撞到对方已经公开的 `100%` 天花板，但也意味着不能直接声称“超过 EvoSkills 本任务表现”，除非后续自己复现。

这几个条件放在一起，使它非常适合做“第一张单任务实验表”。

---

## 2. 官方任务内容

根据 SkillsBench 官方任务页，`software-dependency-audit` 的任务定义可以概括为：

- 角色：你是一个软件安全工程师
- 输入：`/root/package-lock.json`
- 约束：可以使用**离线**工具或数据库
- 只保留：`HIGH` 和 `CRITICAL` 严重等级的漏洞
- 对每个漏洞提取以下字段：
  - `Package`
  - `Version`
  - `CVE_ID`
  - `Severity`
  - `CVSS_Score`
  - `Fixed_Version`
  - `Title`
  - `Url`
- 输出文件：`/root/security_audit.csv`

这不是简单的“跑一个扫描器”任务，而是一个**三模块组合任务**：

1. **扫描模块**
   读取 `package-lock.json`，离线识别依赖漏洞。

2. **信息标准化模块**
   对漏洞结果做字段抽取与归一化，尤其是 `CVSS score`、`Fixed version`、`Severity` 的来源选择和缺失处理。

3. **报告生成模块**
   将结果整理成 verifier 认可的 CSV 结构和字段顺序。

这正好契合你的方法设计：`Trace-guided mutation` 可以对错误模块做定向修复，`crossover` 也有天然的槽位边界，不会像全局重写那样失控。

---

## 3. 去哪里找这个任务内容

这部分要分成五个层级去查，不要只看任务页。

### 3.1 官方任务页：看任务定义

用途：确认输入、输出、约束、字段要求。

- URL: `https://www.skillsbench.ai/tasks/software-dependency-audit`

建议优先确认的内容：

- 输入文件位置
- 输出文件位置
- 输出字段顺序
- 是否允许联网
- 是否只保留 HIGH / CRITICAL

### 3.2 GitHub 任务目录：看 verifier 和环境

用途：确认这个任务的真实结构，而不是只看网页摘要。

- URL: `https://github.com/benchflow-ai/skillsbench/tree/main/tasks/software-dependency-audit`

这个目录下重点看 5 个位置：

- `instruction.md`
  任务文字说明的原始版本。
- `task.toml`
  任务元信息。
- `environment/`
  环境依赖、数据文件、官方 skills。
- `tests/`
  verifier 逻辑。需要理解它检查什么，但**不要把测试细节喂给进化 prompt**。
- `solution/`
  oracle 方案。这个目录可用于后验分析和 sanity check，但**不要把 oracle 内容作为优化输入**。

### 3.3 SkillsBench 官方 skills 页：看官方 curated baseline

用途：确认这个任务官方配了哪些技能，它们应该作为**human-curated baseline**，而不是你的初始冗余池 `P0`。

- URL: `https://www.skillsbench.ai/skills`

目前公开能确认和 `software-dependency-audit` 直接关联的 3 个官方 skills 是：

- `cvss-score-extraction`
- `trivy-offline-vulnerability-scanning`
- `vulnerability-csv-reporting`

注意：这 3 个技能非常像 benchmark 作者为这个任务手工挑好的“标准配方”。  
它们应当只出现在 `Curated-Skills baseline`，**不应直接作为你的冗余池初始种群**。

### 3.4 SkillsBench 论文：看任务在 benchmark 中的位置

用途：确认这个任务是不是值得做、在整个基准中的难度和技能增益如何。

- 论文 PDF: `https://www.skillsbench.ai/skillsbench.pdf`

这篇论文里和你这次实验最相关的两类信息是：

- 整体方法学：
  SkillsBench 采用 paired evaluation，分别跑 `No Skills / With Skills / Self-Generated Skills`。
- 任务级统计：
  `software-dependency-audit` 被列为 skills 提升最大的前 10 个任务之一，结果是：
  - `No Skills = 8.6%`
  - `With Skills = 69.4%`
  - `Δ = +60.9pp`

这说明它是一个**典型的“技能有用，但并未被解完”的任务**。

### 3.5 EvoSkills 官方页和论文：看外部比较边界

用途：确认和 EvoSkills 的比较该怎么说，什么能比，什么不能比。

- 官网: `https://evoskills.net/`
- 论文: `https://arxiv.org/abs/2604.01687`

当前公开能确认的是：

- EvoSkills 在 SkillsBench 总体上达到 `71.1% pass rate`
- 官网公开了 `exoplanet transit period detection` 的 case study
- **没有公开 `software-dependency-audit` 的逐任务结果或最终 evolved skill 文件**

因此，这个首个 pilot 的正确口径是：

- 可以说：这个任务来自和 EvoSkills 相同的 benchmark
- 不能说：本任务上已经超过 EvoSkills
- 只有在你自己复现 EvoSkills 跑这题之后，才能做任务级直接 PK

### 3.6 推荐搜索关键词

如果后面要自己补材料，建议直接用下面这些查询：

- `site:skillsbench.ai/tasks "software-dependency-audit"`
- `site:github.com/benchflow-ai/skillsbench "software-dependency-audit"`
- `site:skillsbench.ai/skills "software-dependency-audit"`
- `site:skillsbench.ai/skillsbench.pdf "software-dependency-audit"`
- `site:evoskills.net SkillsBench 71.1`

---

## 4. 这次实验到底要回答什么问题

这次实验不要贪多，只回答 3 个问题。

### Q1. 从冗余池初始化出发，进化后能否优于进化前最好的技能？

这是这次实验最核心的问题。  
如果 `APO-Full` 连 `P0-Best` 都打不过，就说明“进化”部分还没真正起作用。

### Q2. 我们的方法能否优于标准基线？

这里的标准基线是：

- `No-Skill`
- `Self-Generated`
- `Curated-Skills`

如果 `APO-Full` 能稳定超过这 3 个基线，那么这个单任务实验就成立。

### Q3. 这种提升的代价有多大？

你不能只报最终 pass。  
必须把**搜索期成本**和**部署期成本**分开：

- 搜索期：为了进化出最终 skill，你花了多少 token / 候选评估 / 代数
- 部署期：最终 skill 单次执行时花了多少 token / 时间

这点很重要，因为你的方法和 EvoSkills 一样都属于“搜索后部署”，只报最终通过率不够。

---

## 5. 基线和对比对象怎么设

### 5.1 必须包含的基线

这次单任务实验建议至少包含下面 5 组。

| 条件               | 作用                          | 是否必须 |
| ---------------- | --------------------------- | ---- |
| `No-Skill`       | 裸跑基线，确认任务原始难度               | 必须   |
| `Self-Generated` | 一次性生成单个 skill，不做优化          | 必须   |
| `Curated-Skills` | SkillsBench 官方 3 个技能包       | 必须   |
| `P0-Best`        | 初始冗余池中最好的单个 skill，代表“进化前上界” | 必须   |
| `APO-Full`       | 你的完整方法                      | 必须   |

### 5.2 可以加但不是首轮必需的对照

| 条件                     | 作用                           | 首轮是否建议 |
| ---------------------- | ---------------------------- | ------ |
| `Market-Best`          | 如果你有外部市场排序，可以选市场排名最高的单 skill | 可选     |
| `w/o Crossover`        | 验证交叉模块的价值                    | 第二轮再加  |
| `w/o Trace`            | 验证 trace 相对谱系归因的价值           | 第二轮再加  |
| `w/o Pareto`           | 验证多目标选择是否有用                  | 第二轮再加  |
| `EvoSkills-Reproduced` | 真正的任务级 SOTA 对比               | 后续再加   |

### 5.3 这次实验最重要的比较关系

不要把所有行都当成同等重要。主次要分清：

#### 第一主对比

`APO-Full` vs `P0-Best`

这是最能回答你自己方法是否真的有效的比较。

#### 第二主对比

`APO-Full` vs `Curated-Skills`

这是最能说明“自动进化是否能超过官方人工精选技能”的比较。

#### 第三主对比

`APO-Full` vs `No-Skill / Self-Generated`

这两个主要是兜底基线，用来证明任务确实需要 skill，而且一次性生成不够。

### 5.4 和 EvoSkills 怎么比

这部分必须收口，不要写虚。

这次首轮单任务实验里：

- `EvoSkills 71.1%` 只能作为**benchmark-level 背景数字**
- **不能**把它和本任务单任务 pass rate 直接放在同一张主表里比较
- 只有当你自己复现 EvoSkills 并在 `software-dependency-audit` 上跑出任务级结果后，才能在单任务表里加 `EvoSkills-Reproduced`

因此，这次实验文档中的正确表述是：

> This pilot is benchmark-aligned with EvoSkills but not yet a task-level direct comparison to EvoSkills, because public materials do not report a per-task result for software-dependency-audit.

---

## 6. 初始冗余池 `P0` 怎么构造

这部分是这次实验的关键。如果 `P0` 选错了，实验结论会非常脆。

### 6.1 绝对不要做的事

- 不要直接把 SkillsBench 官方这 3 个 task skills 当 `P0`
- 不要把 `solution/` 里的 oracle 逻辑反写成 skill
- 不要把 `tests/` 里的断言内容喂给 mutation prompt
- 不要从任务目录里“抄一个接近答案的技能组合”再假装是市场冗余池

### 6.2 `P0` 的正确来源

`P0` 应该来自**外部或更一般的安全技能库**，而不是 benchmark 自带 task folder。

建议从你自己的 skill 仓库、公开 skill 市场、社区 skill 集合中检索下面几类技能：

- 依赖漏洞扫描
- 离线 Trivy 扫描
- `package-lock.json` 分析
- CVSS / severity 规范化
- GHSA / NVD / RedHat 漏洞字段解析
- CSV 报告生成
- 安全审计工作流

### 6.3 建议的检索关键词

建议至少跑下面这些检索 query：

- `dependency vulnerability scan`
- `offline trivy audit`
- `package-lock security audit`
- `npm lockfile vulnerability`
- `cvss score extraction`
- `security csv reporting`
- `vulnerability advisory normalization`
- `dependency security report`

### 6.4 建议的 `P0` 组成

建议 `N0 = 10`，并尽量覆盖 4 类能力，而不是全堆在同一类扫描器上：

- 扫描类：`3` 个
- CVSS / advisory 归一化类：`3` 个
- 报告生成类：`2` 个
- 端到端安全审计工作流类：`2` 个

如果真实检索不到足够技能，可以最多用 `≤ 30%` 的 LLM 合成 skill 补齐。

### 6.5 `P0-Best` 的定义

`P0-Best` 不是“市场评分最高的 skill”，而是：

> 在同一任务、同一 agent、同一执行设置下，对 `P0` 中所有候选逐个跑一次后，**实际表现最好的那个单 skill**。

这是你这次实验里最重要的“进化前基线”。

---

## 7. 具体实验流程

### 7.1 固定执行配置

为了避免首个实验就把变量放太多，建议先固定：

- 任务：`software-dependency-audit`
- agent harness：固定一个，不要混用
- foundation model：固定一个，不要混用
- temperature：固定
- 最大执行步数 / 超时：固定
- 文件系统和网络权限：固定

如果你后面要和 EvoSkills 更严肃地对比，正式版最好对齐到：

- `Claude Opus 4.6 + Claude Code`

但如果当前只是先把框架跑通，先用你现有可用的 agent 配置也可以，只要在文档和结果表里明确标注：

> This is a pilot configuration and not yet a strict apples-to-apples reproduction of EvoSkills.

### 7.2 运行次数

建议每个条件至少跑 `5` 次独立 trial。

如果 harness 支持 `seed`：

- 固定 5 个 seeds，在所有条件下共用

如果 harness 不支持 `seed`：

- 进行 5 次独立重复运行
- 用 trial id 代替 seed id

### 7.3 搜索期和报告期分开

为了尽量避免“在同一批试次上既搜索又汇报”的问题，建议分两阶段：

#### 搜索期

- 用 `3` 个固定 trial / seed 做进化搜索
- 所有候选的 mutation / crossover / selection 都只在这 3 个 trial 上决定

#### 报告期

- 用另外 `5` 个 fresh trial / seed 只评估最终选出的 skill
- `No-Skill / Self-Generated / Curated-Skills / P0-Best / APO-Full` 都在这 5 个报告 trial 上跑

这当然不能完全消除 benchmark overfitting，但至少能把“搜索用的试次”和“汇报用的试次”分开。

### 7.4 进化预算

首个正式 pilot 建议用下面这组参数：

- `N0 = 10`
- `B = 5` 代
- 每个 parent 每代做 `1` 次 mutation
- 每代最多做 `2~3` 个 crossover child
- 连续 `3` 代无改进时，注入 `1~2` 个 escape skill

这样每次完整 run 的 candidate 数量大致可控，不会一开始就预算爆炸。

---

## 8. 指标设计

### 8.1 主指标

#### `Pass Rate`

定义：

- 在报告期 5 个 trial 中，通过 verifier 的比例

这是首表主指标。

### 8.2 必须补充的成本指标

#### `Deployment Token Cost`

- 最终 skill 在报告期单次执行时的平均 token 消耗

#### `Search Token Cost`

- 为得到最终 skill，整个进化过程消耗的总 token

#### `Wall-Clock Time`

- 报告期单次运行时间
- 搜索期总时间

#### `Generation-to-First-Pass`

- 在搜索期中，第几代首次出现通过 verifier 的 skill

这几个指标必须一起报。  
否则你只能说明“最终会不会过”，不能说明“值不值得这样搜索”。

### 8.3 可选诊断指标

下面这些不是主表必需，但非常适合单任务分析：

#### `CSV Row Precision / Recall / F1`

方法：

- 通过 `solution/` 或 oracle 输出做后验对比
- 只用于分析，不用于进化时打分

这样可以看出失败是因为：

- 漏洞漏检
- 多报了无关漏洞
- 字段不完整
- CSV 格式错误

#### `Safety Reject Rate`

- 被安全过滤器拦掉的候选占比

#### `Module Usage Trace`

- 记录最终成功 skill 到底调用了哪些模块

这对于后面写“从 general workflow 演化到 task-specific pipeline”很有用。

---

## 9. 数据记录设计

这次实验建议至少落 4 张表。

### 9.1 `baseline_report.csv`

记录所有非进化基线在报告期的结果。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `task_id` | 固定为 `software-dependency-audit` |
| `condition` | `no_skill / self_generated / curated_skills / p0_best` |
| `trial_id` | 第几次独立运行 |
| `passed` | 是否通过 verifier |
| `runtime_tokens` | 单次执行 token |
| `runtime_seconds` | 单次执行时间 |
| `output_path` | 生成文件路径 |
| `notes` | 失败摘要 |

### 9.2 `evolution_candidates.csv`

记录所有进化候选。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `run_id` | 一次完整 evolution run 的编号 |
| `generation` | 所在代数 |
| `candidate_id` | 个体 id |
| `parent_ids` | 父代 id |
| `op_type` | `init / mutate / crossover / escape` |
| `passed` | 是否通过 verifier |
| `pass_rate_search` | 在搜索 trial 上的 pass rate |
| `runtime_tokens` | 单次执行 token |
| `search_tokens_accum` | 累计搜索 token |
| `safety_rejected` | 是否被安全过滤 |
| `trace_path` | 对应 trace 文件 |

### 9.3 `final_report.csv`

记录 `APO-Full` 最终胜出 skill 在报告期的结果。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `run_id` | 对应哪次 evolution run |
| `final_skill_id` | 最终选中 skill |
| `trial_id` | 报告期 trial |
| `passed` | 是否通过 |
| `runtime_tokens` | 执行 token |
| `runtime_seconds` | 执行时间 |
| `csv_f1` | 可选，离线分析值 |

### 9.4 `run_summary.csv`

记录每个完整条件的一行汇总。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `condition` | 条件名 |
| `pass_rate_report` | 报告期通过率 |
| `mean_runtime_tokens` | 平均部署 token |
| `mean_runtime_seconds` | 平均部署时间 |
| `total_search_tokens` | 总搜索 token |
| `generation_to_first_pass` | 首次通过所在代 |
| `num_candidates_evaluated` | 评估过的候选数 |
| `num_safety_rejects` | 安全过滤个数 |

---

## 10. 首轮结果表怎么画

这次实验建议至少有两张结果表。

### 表 1：主结果表

| Condition | Report Pass Rate | Mean Runtime Tokens | Mean Runtime Seconds | Total Search Tokens |
| --- | --- | --- | --- | --- |
| No-Skill |  |  |  | 0 |
| Self-Generated |  |  |  | 生成成本另记 |
| Curated-Skills |  |  |  | 0 |
| P0-Best |  |  |  | 检索/筛选成本另记 |
| **APO-Full** |  |  |  |  |

这张表回答：

- 最终有没有更高通过率
- 是不是靠更高部署成本换来的
- 搜索成本大概有多大

### 表 2：进化收益表

| Metric | P0-Best | APO-Full | Delta |
| --- | --- | --- | --- |
| Report Pass Rate |  |  |  |
| Runtime Tokens |  |  |  |
| Runtime Seconds |  |  |  |
| Generation to First Pass | N/A |  |  |

这张表回答：

- 进化相对于“最好的初始候选”到底带来了什么

---

## 11. 结果应该怎么解释

这部分提前写清楚，避免结果出来后再临时找说法。

### 情况 A：`APO-Full > P0-Best > Curated-Skills`

这是最理想结果。

可支持的结论：

- 冗余池初始化有效
- 进化确实优于初始最好技能
- 自动进化超过官方人工精选 skill

### 情况 B：`APO-Full > P0-Best`，但 `APO-Full < Curated-Skills`

说明：

- 进化机制本身是有用的
- 但你的 `P0` 检索质量还不够，或模块交叉还不够强

这时不要急着否定方法，先查：

- 检索回来的 skill 是否太泛
- mutation 是否只在修格式 bug，而没触及漏洞发现核心
- crossover 是否没有把扫描模块和报告模块真正拼起来

### 情况 C：`P0-Best` 已经接近 `APO-Full`

说明：

- 该任务在你当前 skill 市场上可能已经很“近邻可解”
- 进化空间有限

这并不一定否定方法，但会削弱论文亮点。  
这时要考虑：

- 换一个更需要多模块整合的任务
- 或强调“更低部署 token”而不只强调 pass

### 情况 D：`Curated-Skills` 远高于 `APO-Full`

说明：

- benchmark 官方技能已经非常贴任务
- 你的外部冗余池与该任务的距离还太远

这种情况下，首要问题通常不是 evolution，而是 retrieval。

---

## 12. 这次实验的最终建议

把这次 `software-dependency-audit` pilot 的目标收缩为：

1. 先证明 `APO-Full` 能稳定超过 `P0-Best`
2. 再看能不能超过 `Curated-Skills`
3. 同时记录搜索成本和部署成本
4. 暂时不要在单任务表里直接写“超过 EvoSkills”

最重要的结论不是：

> 我是不是已经打赢了 EvoSkills

而是：

> 我的框架在一个正式 SkillsBench 任务上，是否能从外部冗余池出发，进化出比初始最好技能更强、并且成本可解释的 task-specific skill

如果这个问题回答清楚了，这个 pilot 就成功了。

---

## 13. 这次实验的执行清单

- [ ] 打开官方任务页，确认输入输出和字段要求
- [ ] 打开 GitHub 任务目录，确认 `instruction.md / tests / solution / environment`
- [ ] 把官方 3 个 skills 记录为 `Curated-Skills baseline`
- [ ] 检索外部安全技能，构建 `P0`
- [ ] 对 `P0` 做 smoke test，确定 `P0-Best`
- [ ] 运行 `No-Skill / Self-Generated / Curated-Skills / P0-Best`
- [ ] 运行 `APO-Full`
- [ ] 分开记录搜索期与报告期 token
- [ ] 生成主结果表和进化收益表
- [ ] 写清楚“与 EvoSkills benchmark-aligned，但不是本任务 direct comparison”

---

## 14. 参考来源

- SkillsBench 官方任务页：`https://www.skillsbench.ai/tasks/software-dependency-audit`
- SkillsBench GitHub 任务目录：`https://github.com/benchflow-ai/skillsbench/tree/main/tasks/software-dependency-audit`
- SkillsBench 官方 skills 页：`https://www.skillsbench.ai/skills`
- SkillsBench 论文：`https://www.skillsbench.ai/skillsbench.pdf`
- SkillsBench 文档：`https://www.skillsbench.ai/docs/getting-started`
- EvoSkills 官网：`https://evoskills.net/`
- EvoSkills 论文：`https://arxiv.org/abs/2604.01687`
