# APO-SkillsMD 代码框架实施计划

## Context

项目 `/Users/zhangzuhao/code-project/autoskills` 是 AAAI 2027 投稿的研究代码仓库，目前只有一份详细的实验框架设计文档（`🌟🌟实验框架设计-20260412.md`，541 行），**尚无任何代码**。需要从零构建 APO-SkillsMD 的完整实现：一个针对 Claude Code "skills"（SKILL.md + scripts/ 包）的进化优化框架，包含 4 个核心组件（冗余池初始化、沙盒执行+Trace、Trace-guided 变异+模块级交叉、Pareto 多目标选择）+ 主循环 + 4 组实验（主对比、组件消融、初始化对比、定性分析）。

**用户确认的关键决策**：
- **范围**：完整 4 组件 + 主循环，小规模可端到端跑通（N₀=6，2-3 代）
- **Agent**：自建极简 agent loop（借鉴 Claude Agent SDK 设计模式，但 provider-agnostic）
- **LLM**：`LLMClient` 抽象，MiniMax 默认，保留 OpenAI/Anthropic/Gemini/Qwen 插拔；key 从 `.env` 读取，**绝不入库**
- **沙盒**：`Sandbox` 抽象基类 + 三档运行环境（`offline-local` / `offline-extended` / `network-whitelist`）；默认 subprocess 后端，Docker 后端作可插拔 TODO
- **数据**：SkillsBench 来自 `github.com/benchflow-ai/skillsbench`；冗余池来自 `github.com/sickn33/antigravity-awesome-skills` + SkillsMP；baseline skill 来自 `github.com/anthropics/skills`

---

## 目标目录结构

```
autoskills/
├── pyproject.toml                 # PEP 621, 依赖 + ruff/mypy 配置
├── .env.example                   # MINIMAX_API_KEY 等
├── .gitignore                     # data/ results/ .env
├── configs/                       # default.yaml + 各实验 YAML
│
├── src/apo_skillsmd/
│   ├── config.py                  # pydantic-settings AppSettings
│   ├── types.py                   # 共享枚举/类型
│   │
│   ├── skill/
│   │   ├── model.py               # Skill, SkillFrontmatter, ScriptFile
│   │   ├── loader.py              # load_skill(path) -> Skill（解析 frontmatter + scripts/）
│   │   └── serializer.py          # dump_skill
│   │
│   ├── llm/
│   │   ├── base.py                # LLMClient ABC, LLMResponse, ToolSchema, ToolCall
│   │   ├── tool_adapters.py       # 三家 tool_use 格式互译
│   │   ├── minimax.py             # 默认后端
│   │   ├── openai.py / anthropic.py / gemini.py / qwen.py
│   │   ├── cache.py               # diskcache 包装
│   │   └── factory.py             # build_llm(settings)
│   │
│   ├── agent/
│   │   ├── loop.py                # AgentLoop.run(task, skill) -> AgentResult
│   │   ├── tools.py               # bash / file_read / file_write / file_list
│   │   ├── prompt.py              # build_system_prompt(skill)
│   │   └── trace_emitter.py
│   │
│   ├── sandbox/
│   │   ├── base.py                # Sandbox ABC + SandboxProfile 枚举
│   │   ├── profiles.py            # 三档 profile 配置
│   │   ├── subprocess_backend.py  # 默认后端（rlimit + tempdir jail）
│   │   └── docker_backend.py      # TODO 桩
│   │
│   ├── safety/
│   │   ├── filter.py              # SafetyFilter.scan(skill) -> Verdict
│   │   ├── static_bandit.py       # Bandit Python API 封装
│   │   ├── regex_rules.py         # prompt-injection / eval/exec 等
│   │   └── runtime_guard.py       # 软拦截（hash 匹配、越界写）
│   │
│   ├── trace/
│   │   ├── schema.py              # Trace, ModuleEvent (pydantic)
│   │   ├── recorder.py            # tool 级 + 可选 sys.settrace
│   │   └── attribution.py
│   │
│   ├── evolution/                 # 4 组件
│   │   ├── init_pool.py           # 组件①
│   │   ├── retrieval.py           # BM25 / embedding 检索
│   │   ├── mutation.py            # 组件③a：trace-guided 变异
│   │   ├── slot_align.py          # LLM 功能槽对齐
│   │   ├── crossover.py           # 组件③b：模块级交叉（5 步算法）
│   │   ├── escape.py              # 逃逸机制
│   │   ├── pareto.py              # 组件④：NSGA-II
│   │   └── loop.py                # 主驱动，含消融开关
│   │
│   ├── bench/
│   │   ├── skillsbench.py         # TaskSpec 加载 + 验证器执行
│   │   ├── pool_sources.py        # antigravity + SkillsMP 抓取
│   │   └── baselines.py           # anthropics/skills 加载
│   │
│   └── experiments/
│       ├── base.py                # ExperimentRunner + ResultStore
│       ├── exp1_main.py / exp2_ablation.py / exp3_init.py / exp4_qualitative.py
│       └── aggregate.py
│
├── scripts/
│   ├── download_skillsbench.py    # git clone
│   ├── download_skill_pools.py    # antigravity + SkillsMP
│   ├── download_baselines.py      # anthropics/skills
│   ├── smoke_phase1.py
│   └── run_experiment.py          # CLI 入口
│
├── data/        # gitignored
├── results/     # gitignored
└── tests/       # unit/ + integration/ + fixtures/
```

---

## 关键数据结构

- **`Skill`**：`id`, `path`, `frontmatter`, `md_body`, `scripts: dict[str, ScriptFile]`, `resources`, `content_hash`, `provenance(source, parents, generation)`
- **`Trace`**（严格对齐设计文档 §2.2）：`skill_id`, `task_id`, `success`, `execution_tokens`, `module_events: list[ModuleEvent]`, `final_output`
- **`ModuleEvent`**：`module="scripts/<file>.py:<fn>"`, `entered`, `exceptions`, `duration_ms`, `output_summary`
- **`ParetoCandidate`**：`skill`, `eval(pass_rate, exec_tokens, trace)`, `rank`, `crowding`
- **`TaskSpec`**：`task_id`, `domain`, `description`, `inputs`, `verifier`, `test_cases`

---

## Agent 循环设计（provider-agnostic）

1. **系统提示词**：Claude-Code 风格前言 + SKILL.md 正文 + 工具列表（schema-only）。`scripts/` 不进 prompt，放在沙盒文件系统，agent 通过 `file_list`/`file_read` 发现
2. **工具集**：`bash(cmd,timeout)`, `file_read(path)`, `file_write(path,content)`, `file_list(path)` — 每个工具 JSON-schema 化，调用委托给当前 `Sandbox`
3. **主循环**：`llm.complete(msgs, tools=schemas)` → 若无 tool_calls 且 assistant 发 DONE 或 max_steps → break；否则执行 tool_calls、发 `ModuleEvent`、回 tool_result
4. **Provider 规范化**（`tool_adapters.py`）：
   - Anthropic：`tool_use` blocks
   - OpenAI/MiniMax：`tool_calls`（JSON 字符串参数）
   - Gemini：`functionCall`
   - 统一内部表示 `ToolCall(id, name, args: dict)`
5. **Trace 发射点**：loop 开始 → 工具 start/end（每次 → `ModuleEvent`）→ LLM usage 累加 → loop 结束（`final_output` + 沙盒 diff）
6. **缓存**：`CachedLLMClient` 用 diskcache，key=sha256(provider+model+messages+tools+params)；mutation/crossover 也走它，跨代大幅节省

---

## 分阶段实施（5 个阶段，每阶段可端到端）

### Phase 1 — 骨架（1-2 天）
`pyproject.toml` + `config.py` + `llm/base.py` + `llm/minimax.py` + `llm/factory.py` + `agent/loop.py` + `agent/tools.py`（临时用 in-process tempdir 代沙盒）+ 1 个 mock `TaskSpec` 夹具。
**出口**：`python scripts/smoke_phase1.py` 能调 MiniMax 完成 bash 工具调用并返回 `AgentResult`。

### Phase 2 — 沙盒 + 安全 + skill 加载
`sandbox/base.py` + `sandbox/subprocess_backend.py`（三档 profile 全实现）+ `safety/filter.py`（Bandit + 正则）+ `skill/loader.py` + `skill/serializer.py`。替换 Phase 1 临时沙盒。每档 profile 的拒绝行为有单测。

### Phase 3 — SkillsBench + Trace
`scripts/download_skillsbench.py` + `bench/skillsbench.py` + `trace/schema.py` + `trace/recorder.py` + trace 发射通过 agent loop 串起。
**出口**：1 个真实 SkillsBench 任务 + 1 个 baseline skill 端到端，产出完整 `Trace` JSON。

### Phase 4 — 进化循环
`evolution/init_pool.py` → `retrieval.py` → `mutation.py` → `slot_align.py` → `crossover.py` → `pareto.py` → `escape.py` → `loop.py` + `scripts/download_skill_pools.py`。
**出口**：`N₀=6, gens=2` 跑 1 个任务，产出 Pareto 前沿。

### Phase 5 — 实验驱动
`experiments/base.py` + 4 个 runner + `aggregate.py` + config YAMLs。消融开关挂在 `EvolutionDriver` 构造参数上。

---

## 关键文件（需实现/修改）

- `src/apo_skillsmd/agent/loop.py` — Agent 主循环
- `src/apo_skillsmd/llm/base.py` + `llm/tool_adapters.py` — Provider 抽象 + tool-use 互译
- `src/apo_skillsmd/sandbox/base.py` + `sandbox/subprocess_backend.py` — 三档沙盒
- `src/apo_skillsmd/evolution/crossover.py` — 模块级交叉 5 步算法（设计文档 §2.3.2）
- `src/apo_skillsmd/evolution/pareto.py` — NSGA-II
- `src/apo_skillsmd/evolution/loop.py` — 主驱动，含所有消融开关
- `src/apo_skillsmd/trace/schema.py` — Trace 与设计文档严格对齐

---

## 依赖

**核心**：`pydantic>=2.6`, `pydantic-settings>=2.2`, `httpx>=0.27`, `pyyaml`, `python-frontmatter`, `bandit`, `gitpython`, `rank-bm25`, `numpy`, `rich`, `tenacity`, `diskcache`

**可选 extras**：`[anthropic]anthropic`, `[openai]openai`（也用于 MiniMax 兼容），`[gemini]google-generativeai`, `[qwen]dashscope`, `[docker]docker`, `[embed]sentence-transformers`

**Dev**：`pytest`, `pytest-asyncio`, `ruff`, `mypy`

---

## 已知权衡与开放问题

1. **自建 agent vs Claude Agent SDK**：SDK 仅绑 Anthropic，无法满足多 provider 要求。借鉴其设计模式但自己实现；代价是要自己处理并行 tool_call、流式、安全停止等边缘情况
2. **Tool-use 格式三家不兼容**：所有差异封进 `tool_adapters.py`，每家加 round-trip 单测
3. **Bandit 对 LLM 生成代码噪声大**：按严重度 ≥ MEDIUM 过滤 + 类别白名单；加正则补 Bandit 漏的 prompt-injection 字符串
4. **macOS 网络隔离受限**：`offline-local` 在 macOS 上是 best-effort（env + Python socket 拦截），真正隔离需 Docker 后端。profile 文档里明确标注
5. **Trace recorder 侵入性**：先只做 tool 级事件（bash/file ops）作 first-class `ModuleEvent`；函数级 `sys.settrace` 留到 Phase 3.5 再加，避免一上来就卡在脚本注入细节
6. **Docker 后端延后**：`Sandbox` ABC 不带任何 subprocess 字段，`docker_backend.py` 先是 `NotImplementedError` 桩；将来切换只改 config

---

## 安全提醒

用户在对话中直接贴了 MiniMax API key。**必须立即轮换**，并确保：
- 代码中所有 API key 只从环境变量 / `.env` 读取
- `.env` 在 `.gitignore` 中
- `.env.example` 只放占位符
- 任何日志/trace 输出都不落 key

---

## 验证（端到端烟测）

### Phase 1 烟测
```bash
cp .env.example .env   # 填入 MINIMAX_API_KEY（用轮换后的新 key）
python -m pip install -e .
python scripts/smoke_phase1.py \
    --skill tests/fixtures/mock_skill \
    --task tests/fixtures/mock_task.json
```
预期：agent loop 跑 2-5 轮，调 `bash("echo hello > out.txt")`，tempdir 里写出文件，返回 `AgentResult(final_output, token_usage>0)`。

### Phase 4 烟测（最小进化）
```bash
python scripts/download_skillsbench.py --out data/skillsbench
python scripts/download_skill_pools.py --out data/skill_pool
python scripts/run_experiment.py --config configs/default.yaml \
    --task-id skillsbench/<选一个任务> \
    --n0 6 --generations 2 --out results/smoke_phase4
```
预期产物在 `results/smoke_phase4/`：
- `generation_{0,1,2}/population.jsonl` + `evaluations.jsonl` + `mutants.jsonl` + `offspring.jsonl` + `selected.jsonl`
- `final_pareto.json`：≥1 个非支配 skill
- `summary.csv`：代数间 best pass_rate 单调非递减
- `safety_rejects.jsonl`：可能非空（设计文档 §3.2 要求记录）

两个烟测通过即表示 scaffolding 可用，Phase 5 实验可上。

### 单元测试
每阶段配套单测；整合测在阶段边界增加：`test_agent_loop_mock.py`（Phase 1-2 边界）、`test_evolution_small.py`（Phase 4 出口）。
