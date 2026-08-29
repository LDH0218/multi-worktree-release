# 多对话、多工作树与发布任务轮换方法论

Status: reusable method. 本文用于解释和迁移协作模式；采用它的项目仍应以自己的 `AGENTS.md`、工作树 Scope、
任务状态卡、脚本治理文档和机器可读架构索引为正式规则。

## 1. 目标

这套方法解决的不是“如何同时启动更多 Agent”，而是如何让多个长期对话在不同代码责任层上持续工作，
同时保持以下性质：

- 每项修改有唯一责任层；
- 每个对话知道自己的绝对工作目录、分支和提交基线；
- 上下游按真实契约和提交交接，而不是依赖聊天记忆；
- 对话可以换代，但 Git、工作树、运行身份和授权不会被对话版本混淆；
- 只有集成角色能够宣布跨层完成和发布通过；
- 真实运行、发布、破坏性操作等高风险权限默认不继承。

适用场景包括：大型单仓库、平台与业务层并行开发、多个领域编译器、共享基础设施改造、长周期 Agent
协作，以及需要保留审计证据的自动化项目。

## 2. 先分离八种身份

多对话协作最常见的错误，是把名字相近但生命周期不同的身份混为一谈。迁移前必须显式区分：

| 身份 | 示例 | 生命周期 | 能否由对话换代改变 |
| --- | --- | --- | --- |
| 责任角色 | Master、Platform、Workflow | 长期 | 否 |
| 对话代际 | `Master-1.1`、`Master-1.2` | 可轮换 | 是 |
| Git 工作树 | `/repo`、`/repo-platform` | 长期 | 否 |
| Git 分支 | `master`、`codex/platform` | 长期或按项目策略 | 否 |
| 提交基线 | 完整 commit SHA | 每次任务冻结 | 只能由明确同步任务改变 |
| 业务流程身份 | Workflow、service、module | 产品架构 | 否 |
| 运行身份 | execution/run/job ID | 单次运行 | 否 |
| 外部授权 | 真实模型、发布、删除、外部写入 | 单次明确授权 | 否，默认不继承 |

对话名只用于让人识别“这是第几代上下文”。它不能被代码读取，不能作为分支名、Workflow ID、Schema
revision、运行 ID、发布凭证或权限证明。

## 3. 推荐拓扑

最小可用拓扑包含三个长期角色：

| 角色 | 主要责任 | 禁止替代的责任 |
| --- | --- | --- |
| Master | 依赖图、任务发布、跨层契约、集成、冲突处理、全量发布门禁 | 不替领域角色临时修业务逻辑 |
| Platform | 通用运行边界、调度、Provider、证据、共享基础设施 | 不吸收领域语义来快速通过测试 |
| Workflow/Domain | 领域输入、编译器、业务规则、领域测试 | 不复制 Platform 能力，不自行宣布跨层发布 |

工作树数量由“独立责任边界”决定，不由 Agent 数量决定。同一领域在一个工作树中一次只执行一个明确任务；
只有当两个领域长期拥有不同契约、不同发布节奏和几乎无重叠文件时，才考虑继续拆分。

示例目录布局：

```text
/project                 master             Master
/project-platform        codex/platform     Platform
/project-workflow        codex/workflow     Workflow
```

每个长期工作树都应包含本地的 `WORKTREE_SCOPE.md` 和 `WORKTREE_TASK.md`。Scope 描述长期责任与禁止事项；
Task 是紧凑的本地任务状态卡，只保存任务 ID、基线、路径边界、授权、验收、状态和提交 SHA，不复制 Master
发送的完整提示词。若这些文件只服务于本机协作，可以保持不提交；但正式长期规则必须进入仓库治理文档。

### 通信拓扑与完成状态

可执行指令采用星形拓扑：Master 可以跨对话向任意 Worker 发布任务，Worker 只向 Master 交付；Worker 之间
可以共享只读发现，但不能直接要求对方修改、同步或运行。跨层依赖、基线更新和返工都必须经 Master 重新发布，
避免形成无法审计的侧向指令链。

还应区分三种常被混称为“完成”的状态：

| 状态 | 含义 | 谁可以确认 |
| --- | --- | --- |
| 集成完成 | Worker patch 已进入 Master，记录了 `integrated_as_sha` | Master |
| 发布候选通过 | 集成树的派生投影、定向检查和完整发布门禁通过，记录了 `release_head_sha` | Master |
| 生产发布完成 | 已获得单次外部授权并实际发布，记录发布系统证据 | 获授权的发布角色 |

本文中的 Workflow、Execution、Current、Authority 是可替换的架构术语。其他项目可分别映射为领域模块、运行实例、
生产指针和冻结制品；不能因为名称不同而省略身份、证据或授权边界。

## 4. 不变量

无论具体技术栈如何，建议固定以下规则：

1. 一个长期角色绑定一个明确的绝对工作树和分支。
2. 对话换代复用原工作树和分支，不新建同角色工作树，不复制未提交文件。
3. 每次任务以完整 commit SHA 为基线，不以“最新”“刚才那个版本”等描述代替。
4. Worker 不自行 merge、rebase、reset 或同步 Master；同步必须是 Master 发布的具体任务。
5. Master 发布实现任务前必须完成只读门禁。
6. Worker 必须运行本层测试，并在工具可用时运行受影响的共享契约测试；只有 Master 能在集成树上宣布发布通过。
7. 上游未冻结时，下游最多做只读 Discovery，不提前实现完整流程。
8. 真实运行、发布、删除、外部写入和扩域权限默认拒绝，且不随对话换代继承。
9. 历史运行证据、Archive 和既有未跟踪证据按保留策略处理，不为追求“干净状态”擅自删除。
10. 恢复已删除实现优先使用 Git，不保留无期限兼容入口。
11. 跨对话消息是任务传输渠道；`WORKTREE_TASK.md` 是本地状态凭证，不是第二份任务规范。
12. Worker 交付提交后保持等待集成，只有收到 Master 的集成 SHA 才能恢复 `IDLE`。
13. Worker 交付提交是不可变交接点；返工创建新的后继提交，不 amend、不 force-push 已交付提交。
14. 派生 hash、baseline、生成投影和跨层审计必须基于集成后的 Master tree 重算，不能复用 Worker 的局部结果。
15. 一个非 `IDLE` 状态卡就是该工作树的任务锁；新消息必须匹配任务身份，或明确取消、取代当前任务。
16. 消息、状态卡和交接报告不得保存 token、密钥、cookie 或其他凭证。

## 5. 任务生命周期

建议把一次跨层任务视为以下状态机：

```text
Read-only bootstrap
→ Master discovery gate
→ Dependency graph and ownership decision
→ Master sends the explicit task across conversations
→ Worker verifies it and writes WORKTREE_TASK.md = ACTIVE
→ Worker implementation, local verification and commit
→ Structured handoff and WORKTREE_TASK.md = AWAITING_INTEGRATION
→ Master diff and contract review
→ Integration
→ Recompute derived projections from the integrated Master tree
→ Cross-layer and release-candidate gates
→ Master sends integrated_as_sha and release_head_sha to the Worker
→ Worker records both SHAs and resets WORKTREE_TASK.md = IDLE
→ Optional conversation rotation
```

任何一步缺少可复现证据时，不应跳到下一步。尤其不能用“Worker 说测试通过”替代 Master 对提交、差异和
集成状态的检查。发现问题时进入显式分支：责任层缺陷由 Master 发布返工任务；基线或任务已失效时取消或取代；
只有机械性的共享投影冲突可以由 Master 在集成树上重算解决。

## 6. 新对话的只读启动

新一代对话只恢复上下文，不自动恢复工作授权。启动提示至少包含：

- 角色名和对话代际；
- 绝对工作树；
- 目标分支；
- 预期 HEAD；
- 必须完整读取的治理文件；
- 既有未跟踪或历史材料的保留要求；
- 当前 `WORKTREE_TASK.md` 状态及其是否与交接消息一致；
- 禁止同步、运行、发布和破坏性操作的规则；
- 完成启动检查后必须停止并等待具体任务。

可复制模板：

```text
你是 <PROJECT> 的 <ROLE>-<GENERATION> 任务。
所有读取、命令和修改必须使用绝对工作树 <ABSOLUTE_WORKTREE>；
目标分支 <BRANCH>，创建时预期 HEAD 为 <FULL_SHA>。

开始时完整读取：
- AGENTS.md
- ARCHITECTURE.json（若项目使用机器可读架构索引）
- WORKTREE_SCOPE.md
- WORKTREE_TASK.md

随后确认并报告绝对路径、分支、HEAD、工作区状态及既有未跟踪材料。
报告 WORKTREE_TASK.md 是 IDLE、ACTIVE、AWAITING_INTEGRATION 还是 BLOCKED；非 IDLE 时核对其任务 ID、
冻结基线和上一代交接消息，不根据状态卡自行恢复外部授权。
不要切换分支，不要自行同步、merge、rebase 或 reset，不要删除历史材料。
本次启动不继承真实运行、发布、外部写入、破坏性操作或扩域授权。
完成只读启动检查后等待具体任务，不自行开始实现或运行。
```

如果实际 HEAD、分支或状态与提示不一致，对话应报告差异并停止，而不是把工作树强行改成预期状态。

## 7. Master 发布任务前的只读门禁

Master 必须先建立“当前事实”，再决定任务归属。推荐顺序：

```text
确认所有工作树和提交图
→ 读取当前入口、契约、Schema、测试和治理文件
→ 扫描旧入口、旧字段、alias、fallback 和双写
→ 使用真实上游产物执行只读交接或负向校验
→ 列出依赖图、阻塞与责任层
→ 发布实现任务或 Discovery 任务
```

门禁输出至少回答：

- 当前 Master 和目标分支的 HEAD 是什么；
- 工作区是否干净，哪些未跟踪材料必须保留；
- 分支差异是未集成代码，还是内容等价 cherry-pick 造成的历史分叉；
- 当前正式输入、输出和 revision 是什么；
- 旧实现是否仍有调用者；
- 哪些工作可以并行，哪些必须等待上游冻结；
- 任务应由哪个责任层修改哪些文件；
- 哪些授权仍然缺失。

责任归属应按文件和契约所有权判断，而不是按任务标题中的业务名判断。例如，“删除 Fact Authority 的共享
物化命令”如果修改的是跨层 operation、命令注册表和发布审计，可能属于 Master；修改 Fact 语义编译器才
属于 Workflow。

## 8. 依赖图与并行策略

先画输入/输出依赖，再决定并行度：

```text
Platform contract ──┐
                    ├─→ Domain compiler ─→ Master integration gate
Upstream Authority ─┘
```

- 没有数据或契约依赖的任务可以并行。
- 下游依赖上游 Schema、Authority、Projection 或 revision 时，必须等待上游提交被 Master 集成。
- 如果下游只需要调查调用点、测试范围或迁移成本，可以提前发布只读 Discovery。
- 不允许 Worker 从落后分支自行推断 Master 的当前契约。
- 每次上游集成后，Master 应重新发布新的下游基线，而不是只说“继续”。

## 9. 实现任务发布包

一个可执行任务必须达到“接收者无需再决定范围”的程度。推荐字段如下：

```yaml
task_id: <stable-human-id>
task_spec_revision: <positive-integer>
source_thread_id: <master-thread-id>
issued_at: <ISO-8601 timestamp>
supersedes_task_id: <id-or-null>
generation: <role-generation-label>
owner_role: <Master|Platform|Workflow>
worktree: <absolute-path>
branch: <branch>
expected_head: <full-sha>
task_class: <docs|scripts|platform|domain|frontend|...>

objective: <one concrete outcome>
current_state: <verified repository facts>

allowed_paths:
  - <path or glob>
forbidden_paths:
  - <path or glob>

inputs:
  - path: <formal input path>
    revision: <exact revision or digest>
outputs:
  - <expected file, API, commit, or report>
derived_outputs:
  recompute_on_master: [<hash, baseline, generated projection, or index>]

dependencies:
  upstream_commits: [<sha>]
  parallel_with: [<task-id>]
  blocked_by: [<condition>]

authorization:
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: <exact-target-or-null>
  controlled_input: <exact-path-and-digest-or-null>
  route: <exact-route-or-null>
  max_calls: 0
  max_cost: 0
  fresh_execution_required: true
  resume_execution_id: null
  expires_at: <ISO-8601 timestamp-or-null>
  envelope_digest: <digest-or-null>

acceptance:
  - <targeted test>
  - <layer audit>
  - <base-relative audit from frozen baseline to integrated release head>
  - git diff --check

commit_message: <exact or patterned message>
handoff_fields:
  - commit SHA
  - changed paths
  - tests and results
  - unresolved findings and responsible role

stop_conditions:
  - baseline mismatch
  - dirty overlapping files
  - cross-layer contract ambiguity
  - missing authorization
```

任务正文必须同时写清“做什么”和“不做什么”。仅写“修好 Fact”或“同步平台”都不是合格任务。

跨对话消息携带完整任务，`WORKTREE_TASK.md` 只持久化以下状态卡：

```yaml
state: IDLE | ACTIVE | AWAITING_INTEGRATION | BLOCKED
task_id: <id-or-null>
task_spec_revision: <integer-or-null>
source_thread_id: <thread-id-or-null>
issued_at: <timestamp-or-null>
supersedes_task_id: <id-or-null>
worker_generation: <role-generation-or-null>
frozen_baseline_sha: <full-sha-or-null>
allowed_paths: [<path>]
forbidden_paths: [<path>]
authorization:
  real_external_call: false
  create_execution: false
  publish: false
  destructive_operation: false
  target: <exact-target-or-null>
  controlled_input_digest: <digest-or-null>
  route: <route-or-null>
  max_calls: 0
  envelope_digest: <digest-or-null>
  expires_at: <timestamp-or-null>
acceptance_commands: [<command>]
blocker: <text-or-null>
worker_commit_sha: <full-sha-or-null>
integrated_as_sha: <full-sha-or-null>
release_head_sha: <full-sha-or-null>
outcome: completed | cancelled | superseded | null
```

`IDLE` 时任务相关字段可以为 `null` 或空数组，但可保留最近一次 Worker/Master SHA 作为诊断摘要。完整提示词、
长篇实现说明和聊天记录不得复制进状态卡。

Master 同时追踪多个 Worker 时，不应把多个 SHA 拼进一个字符串。Master 状态卡使用列表：

```yaml
state: IDLE | ACTIVE | BLOCKED
release_task_id: <id-or-null>
frozen_baseline_sha: <full-sha-or-null>
worker_handoffs:
  - task_id: <worker-task-id>
    task_spec_revision: <positive-integer>
    source_thread_id: <thread-id>
    role: <role>
    worker_commit_sha: <full-sha>
    integrated_as_sha: <full-sha-or-null>
    state: RECEIVED | INTEGRATED | REWORK_REQUESTED
release_head_sha: <full-sha-or-null>
blocker: <text-or-null>
```

`task_id + task_spec_revision + source_thread_id` 构成消息身份。Worker 收到重复消息时应幂等确认，而不是重复执行；
收到较旧 revision、未知来源或与非 `IDLE` 状态卡不匹配的消息时应停止。Master 若要改变范围，必须增加 revision，
并明确它是同任务修订还是通过 `supersedes_task_id` 取代旧任务。

### 完整可复制的 Worker 发布任务示例

下面示例不依赖任何特定项目的业务名称，可把尖括号变量替换为目标项目的真实值：

```text
这是 <PROJECT> 的正式分层实现任务，由 Master 发布给 Platform-2.1。

任务身份
- task_id=<TASK_ID>，task_spec_revision=<REVISION>。
- source_thread_id=<MASTER_THREAD_ID>，issued_at=<TIMESTAMP>，supersedes_task_id=<ID_OR_NULL>。
- 重复收到相同身份时只核对状态，不重复执行；较旧或不匹配消息必须停止报告。

工作树与基线
- 所有命令和修改只能在 <ABSOLUTE_PLATFORM_WORKTREE> 执行。
- 分支必须为 <PLATFORM_BRANCH>，开始时 HEAD 必须为 <FULL_BASE_SHA>。
- 不要切换分支，不要自行 merge、rebase、reset 或同步 Master。
- 如果路径、分支、HEAD 或工作区状态不一致，停止并报告。
- 核对通过后，把任务摘要写入本地 WORKTREE_TASK.md 并将状态设为 ACTIVE；不要提交该文件。

目标
- 删除已经由 <SUCCESSOR_COMPONENT> 完全替代的旧公共入口 <OLD_ENTRYPOINT>。
- 保持 <CURRENT_CONTRACT> 的输入、输出和行为不变。

允许修改
- <PLATFORM_SOURCE_GLOB>
- <PLATFORM_TEST_GLOB>

禁止修改
- <DOMAIN_SOURCE_GLOB>
- <FORMAL_DATA_GLOB>
- Master 的共享文档和发布配置
- 任何历史 Runtime、Authority、Report、Receipt、Current 或 Archive

已核实输入
- 当前共享契约：<CONTRACT_PATH>，revision=<REVISION>
- 当前调用者：<CALLER_PATHS>
- successor 已由 Master 集成：<INTEGRATED_SHA>

实现要求
- 删除旧入口、只为旧入口存在的兼容包装和对应测试。
- 不增加 alias、fallback、双写或第二套入口。
- 如发现领域语义也需要修改，只记录路径、实际行为、预期行为和复现方式，不在本任务修复。

授权
- 不调用真实外部服务。
- 不创建 Execution/Job。
- 不发布、不推进 Current、不执行破坏性清理。

验收
- <TARGETED_TEST_COMMAND>
- <PLATFORM_AUDIT_COMMAND>
- <TYPECHECK_OR_LINT_COMMAND>
- git diff --check

提交
- 提交信息：refactor: retire <old-entrypoint>
- 只提交本任务允许范围内的文件。

完成报告必须包含
- 完整提交 SHA；
- 修改文件；
- 每条验收命令及结果；
- 未解决的跨层发现及建议责任角色；
- 明确说明没有使用上述未授权能力。
```

## 10. Worker 执行与交接

Worker 的推荐步骤：

1. 再次确认绝对路径、分支、HEAD 和状态。
2. 核对消息身份、Master 来源、任务 revision 与 `WORKTREE_SCOPE.md`；通过后写入状态卡并设为 `ACTIVE`。
3. 读取当前任务要求的代码与权威文档。
4. 只修改允许路径；发现跨层问题时记录，不顺手修复。
5. 运行领域定向测试、静态或 Fake 验证、本层审计和 `git diff --check`。
6. 检查完整 diff 和未跟踪文件，确保没有带入其他任务内容。
7. 创建一个原子提交，把 Worker SHA 写入状态卡并设为 `AWAITING_INTEGRATION`。
8. 用结构化报告交给 Master；在 Master 回复前不继续修改该任务，也不改写已交付提交。

如果 Master 要求返工，Worker 应把状态恢复为 `ACTIVE`，以已交付提交为父提交创建新的原子提交，并在下一次交接中
同时给出旧 SHA 和新 SHA。若 Master 已基于其他提交改变基线，则 Worker 停止并等待新的同步或替代任务，不能自行
rebase。若任务被取消或取代，Worker 只记录 `outcome` 并恢复 `IDLE`；未提交修改如何保留或清理由 Master 单独决定。

交接模板：

```text
任务：<task-id>
任务规范：revision=<task-spec-revision>, source_thread_id=<master-thread-id>
工作树：<absolute path>
分支：<branch>
基线：<base sha>
提交：<result sha> <subject>
WORKTREE_TASK 状态：AWAITING_INTEGRATION

完成内容：
- <behavioral outcome>

修改路径：
- <path>

验证：
- <command>: pass/fail, count or key evidence

未完成或跨层发现：
- <actual behavior / expected behavior / reproduction / responsible role>

授权声明：
- 未进行真实外部调用
- 未创建运行或发布记录
- 未修改保留的历史材料
```

## 11. Master 集成与发布门禁

Master 不应仅依据分支名决定是否已集成。推荐流程：

1. 核对 Worker 提交是否以发布时基线为祖先。
2. 审阅完整 diff，确认只修改责任范围。
3. 核对提交图和 patch equivalence；内容等价 cherry-pick 应记录为“已集成、历史分叉”，不能误判为缺失代码。
4. 以项目约定方式集成提交；避免把 Worker 分支上的无关历史一并带入。
5. 在集成后的 Master tree 上重算生成文件、索引、contract digest、prompt baseline、架构投影或锁文件；这些值不能
   从某个 Worker 的局部 tree 直接复制为最终证据。
6. 运行相关定向测试、受影响的共享契约审计，以及从任务冻结基线到当前候选 HEAD 的 base-relative audit。
7. 运行全量测试、类型检查、lint、build 和严格发布检查。
8. 再次核对工作区，只允许已知保留的未跟踪材料存在。
9. 记录每个 Worker 的 `worker_commit_sha → integrated_as_sha` 映射，以及门禁完成后的 `release_head_sha`、测试数量和授权状态。
10. 跨对话把映射、最终候选 HEAD 和验收结果发送回原 Worker。
11. Worker 核对确认后写入两个 Master SHA；该 Worker 交付已接受且无本层返工项时恢复 `IDLE`，否则恢复 `ACTIVE`。

### 冲突与重算归属

| 情况 | 处理 |
| --- | --- |
| 共享生成文件、索引、hash 或投影冲突 | Master 丢弃局部派生值，并基于已集成 source of truth 重新生成 |
| Worker 所有的业务语义冲突 | Master 停止集成，发布带新 revision 的返工任务 |
| 基线过期导致 patch 无法安全应用 | Master 发布明确同步或 replacement task；Worker 不自行 rebase |
| 无法确定责任层或正确值 | 标记 `BLOCKED`，保留证据并请求决策 |

Master 可以解决机械性集成冲突，但不得借此重写 Worker 所有的业务语义。完成重算后，必须检查最终 diff 是否出现
任务允许范围之外的新变化，并把这些 Master-owned projection 变化记录到集成提交。

发布完成标准应同时覆盖：

- 代码行为；
- 输入/输出契约和 revision；
- 文档与机器可读投影；
- 旧入口不可达；
- 跨层测试；
- 工作区状态；
- 外部调用、运行和发布授权的实际使用情况。

“测试通过”不等于“允许真实运行”；发布门禁也不能替代一次新的明确授权。

### Master 集成成功确认模板

```text
任务：<task-id> revision=<task-spec-revision>
Worker 提交：<worker-commit-sha>
集成映射：<worker-commit-sha> → <integrated-as-sha>
发布候选 HEAD：<release-head-sha>
集成方式：<merge|cherry-pick|patch-equivalent-existing-change>

集成树重算：
- <derived output>: <result>

Master 门禁：
- <command>: pass/fail, count or key evidence

授权状态：
- <external call / execution / publish / destructive operation actually used or not used>

结论：集成完成，发布候选 <passed|failed>。
Worker 交付结论：<accepted|rework required>，责任项：<none-or-list>。
Worker 可以记录 integrated_as_sha 和 release_head_sha；交付为 accepted 时恢复 IDLE。若发布候选因其他责任层失败，
由 Master 保留发布任务或向对应 Worker 发新任务，不占用已接受 Worker 的状态锁。
```

### Master 返工模板

```text
任务：<task-id> 的返工 revision=<next-revision>
原 Worker 提交：<old-worker-commit-sha>
当前状态：未接受为发布候选；不要 amend 或 force-push 原提交。

证据：
- 实际行为：<actual>
- 预期行为：<expected>
- 复现或失败门禁：<command/evidence>
- 责任路径：<owned paths>

允许修改：<paths>
禁止修改：<paths>
授权：<exact envelope, default deny>
验收：<commands>

请将 WORKTREE_TASK 恢复为 ACTIVE，在原提交之后创建新的提交，并同时报告旧、新 SHA。
若当前工作树或基线不匹配，停止并报告，不自行同步。
```

### 取消或取代模板

```text
任务：<task-id> revision=<current-revision>
决定：<cancelled|superseded by new-task-id revision=N>
原因：<repository fact or changed decision>

停止继续实现、外部调用和提交。不要自行丢弃未提交修改；先报告当前 HEAD、状态和改动路径。
核对后把 outcome 记为 <cancelled|superseded> 并恢复 IDLE。任何后续工作必须等待新的完整任务包。
```

## 12. 对话换代协议

推荐在以下情况换代：

- 完成一个重要集成里程碑；
- 多次上下文压缩后出现事实混淆；
- 当前对话包含大量已完成任务，影响后续判断；
- 用户明确要求换代。

不要为了增加版本号而固定周期换代。建议使用 `<Role>-<major>.<minor>`：

- major：责任模型、工作树拓扑或长期协议发生明显变化；
- minor：同一责任模型下的上下文换代。

换代交接必须记录：

- 当前 Master、Platform、Workflow 的完整 SHA 和状态；
- 已集成但历史分叉的提交；
- 未完成任务和阻塞；
- 当前正式契约、输入和发布门禁状态；
- 保留的历史或未跟踪材料；
- 所有仍需重新授权的动作；
- 每棵工作树的 `WORKTREE_TASK.md` 状态；非 `IDLE` 时记录任务 ID、冻结基线、Worker SHA 和等待事项。

旧对话在新对话完成只读启动、核对状态卡并确认交接一致后再归档。状态卡是未完成任务的本地持久凭证，
但不是新一代对话的外部授权。优先归档，不删除包含唯一决策或取证信息的对话。

### 对话换代交接模板

```text
这是 <ROLE>-<OLD_GENERATION> 给 <ROLE>-<NEW_GENERATION> 的只读交接。

身份与工作树
- 角色：<role>；绝对工作树：<absolute path>；分支：<branch>。
- 当前 HEAD：<full sha>；预期状态：<clean except preserved paths>。
- 对话版本只表示上下文代际，不是 Git、业务流程、运行或授权身份。

任务状态
- WORKTREE_TASK：<IDLE|ACTIVE|AWAITING_INTEGRATION|BLOCKED>。
- 若非 IDLE：task_id=<id>，revision=<n>，source_thread_id=<id>，frozen_baseline=<sha>。
- Worker 提交：<sha-or-null>；integrated_as_sha=<sha-or-null>；release_head_sha=<sha-or-null>。
- 等待事项或 blocker：<text-or-null>。

跨工作树事实
- Master：<path / branch / sha / status>。
- Worker handoffs：<task / worker sha / integrated sha / state>。
- 已 cherry-pick 集成但历史分叉：<mapping-or-none>。

当前契约与门禁
- 正式输入、revision、路由或发布候选：<exact values>。
- 最近门禁：<commands and results>。
- 保留材料：<paths and policy>。

授权
- 真实外部调用：未继承。
- 创建 Execution/Job：未继承。
- 发布、删除、扩域和同步：未继承。

请完整读取治理文件和状态卡，只读核对路径、分支、HEAD、状态及以上交接；不一致时停止报告。
一致后仅更新当前事实认知并待命，不自行恢复任务或外部授权。
```

### 对话丢失与接管恢复

若旧对话不可用，新对话以 Git、治理文件和状态卡为恢复来源，并由 Master 重发匹配同一消息身份的任务摘要。
当状态卡为 `ACTIVE` 且存在未提交修改时，只读列出 diff 和来源，未经明确决定不提交、不丢弃；为
`AWAITING_INTEGRATION` 时验证提交仍可达并等待 Master；为 `BLOCKED` 时保留 blocker 证据。只有 Master 可以
宣布旧任务失效、指定接管者或发布 `supersedes_task_id`。接管不会继承真实运行、发布或破坏性授权。

## 13. 授权继承矩阵

| 动作 | 新任务是否继承 | 推荐要求 |
| --- | --- | --- |
| 读取仓库 | 是，限工作树范围 | 启动提示声明 |
| 修改任务允许路径 | 否 | 新任务明确范围 |
| 合并或同步分支 | 否 | Master 发布具体同步任务 |
| 真实模型或外部 API 调用 | 否 | 当前对话明确目标、输入及 digest、Route、次数、成本上限和到期时间 |
| 创建 Execution/Job | 否 | 当前对话明确 fresh run、目标和禁止恢复的旧运行；运行 ID 由边界创建 |
| 发布或推进 Current | 否 | 独立发布授权与门禁通过 |
| 删除历史或破坏性操作 | 否 | 精确目标、恢复策略和明确授权 |
| 扩大到其他领域或工作树 | 否 | 重新分类并发布新任务 |

“上一代做过”“测试配置里有”“命令支持该参数”都不构成授权。

授权包应是有边界的能力，而不是一个宽泛的 `true`：至少绑定任务 ID/revision、精确目标、受控输入与 digest、
Route/provider、最大调用次数、成本或资源上限、是否必须新建运行、明确禁止恢复的旧运行，以及到期条件。授权消息
只记录凭证引用或会话状态，不得包含密钥本身。任一绑定变化、对话换代、失败后的重跑或到期都需要新授权。

## 14. 常见失败模式

### Worker 自行同步 Master

问题：引入未经审查的冲突解决，破坏提交归属。处理：Worker 报告落后状态，由 Master 决定同步或直接按
patch 集成。

### Master 为通过测试临时修领域代码

问题：责任边界失真，下一轮领域分支无法理解真实差异。处理：记录路径、实际行为、预期行为、复现方式和
责任角色，发布新任务。

### 用对话版本代表代码版本

问题：无法复现。处理：所有交接同时记录完整 SHA；对话代际只作人类标签。

### 上游未冻结，下游提前实现

问题：产生猜测字段、fallback、兼容层和重复实现。处理：只允许 Discovery，等待 Master 集成正式上游。

### 看到分支独有提交就判断未集成

问题：cherry-pick 后提交 SHA 不同但内容可能完全相同。处理：比较 patch、tree 或明确文件差异，并记录
“内容已集成、提交历史分叉”。

### 为保持兼容而长期保留旧入口

问题：当前路径与历史路径并存，审计难以证明唯一性。处理：采用 successor-only；旧实现由 Git 恢复，
正式历史数据按保留策略继续只读保存。

### 对话换代继承运行权限

问题：新的上下文可能遗漏输入、Route、成本或风险条件。处理：所有外部和运行权限 default-deny，逐次重新授权。

### 多个 Worker SHA 塞进一个状态字段

问题：失去任务与提交的一一映射，无法判断哪项已集成。处理：Worker 卡只保存自己的单一提交；Master 使用
`worker_handoffs[]`，逐项记录 `worker_commit_sha → integrated_as_sha`。

### 直接复用 Worker 生成的 hash 或投影

问题：多个 patch 组合后 source tree 已变化，局部派生值可能过期。处理：Master 先集成 source of truth，再在最终
集成树重算所有派生输出，并运行 base-relative audit。

### 重复或过期消息触发重复执行

问题：网络重发、对话恢复或任务改写会让同一工作树并发执行两个意图。处理：核对
`task_id + task_spec_revision + source_thread_id` 和状态锁；重复消息幂等确认，旧 revision 拒绝，改范围使用新 revision
或 `supersedes_task_id`。

### Worker 直接给另一个 Worker 下执行指令

问题：绕过 Master 的依赖图、基线冻结和授权记录。处理：Worker 间只交换只读发现；所有跨层可执行任务由 Master
重新发布。

### Worker 层测试通过就宣布发布完成

问题：局部 tree 无法证明组合后的投影、依赖和发布门禁。处理：Worker 报告本层与受影响共享测试；只有 Master
可以在集成树上确认发布候选，生产发布仍需另行授权。

## 15. 另一项目的改造步骤

### Phase A：盘点

1. 列出当前代码责任层、共享能力和领域能力。
2. 列出所有长期分支、工作树、自动化运行和发布权限。
3. 找出职责重叠、Worker 自行同步、旧入口共存和依赖聊天记忆的流程。

### Phase B：建立治理文件

至少建立：

```text
AGENTS.md                 任务到权威文档的路由
WORKTREE_SCOPE.md         当前工作树的长期允许/禁止范围
WORKTREE_TASK.md          本地任务状态卡，不保存完整提示词且不提交
docs/script-governance.md 长期任务发布、命令和轮换协议
```

复杂项目再增加机器可读架构索引和文档权威注册表。机器文件应投影已有决策，而不是成为第二套含糊规范。

### Phase C：创建长期工作树

按责任边界创建工作树和分支，写入绝对路径，并为每棵工作树完成一次无修改启动验收。不要同时迁移所有业务；
先证明工作树隔离和提交交接可靠。

### Phase D：试点一个小任务

选择满足以下条件的任务：

- 能清楚判断唯一责任层；
- 有定向测试；
- 不需要真实外部调用；
- 可以通过一个原子提交交接；
- Master 能运行跨层检查。

### Phase E：增加自动护栏

逐步增加：

- 旧命令和旧入口不得注册；
- 工作流/服务身份唯一；
- 文档链接和权威映射有效；
- 未迁移路径 default-deny；
- Worker 提交不越界；
- 重复/过期任务消息不会重复执行；
- Master 能从集成树重算派生投影；
- 发布结论只由 Master 在集成树上给出。

### Phase F：启用对话换代

先完成第一轮稳定集成，再创建 `1.1` 之类的新对话代际。让新对话只读复述工作树、SHA、状态和限制；
确认无误后再归档旧对话。

## 16. 改造验收清单

另一项目完成改造后，应能用仓库证据回答“是”：

- 是否能从任一提交定位唯一责任角色？
- 每个角色是否绑定唯一工作树和明确分支？
- 新对话是否能在不读取旧聊天全文的情况下完成只读启动？
- 每个实现任务是否包含完整基线、范围、输入、输出、验收和停止条件？
- Worker 是否无法自行宣布跨层发布完成？
- Master 是否能识别 cherry-pick 内容等价与真实未集成代码的差别？
- 上游未冻结时，下游是否只能 Discovery？
- 真实运行、发布和删除权限是否逐次授权且不跨代继承？
- 历史数据是否被保留，但旧实现和兼容入口不再作为当前路径？
- 全量发布是否能由一套可复现命令和最终工作区状态证明？
- 是否能逐项追踪每个 `worker_commit_sha → integrated_as_sha → release_head_sha`？
- 重复、返工、取消、取代和对话丢失是否都有确定恢复路径？

如果其中任一答案依赖“大家记得这样做”，而不是文件、提交、测试或审计，则改造仍未完成。

### 运行效果度量

方法是否有效应由趋势而不是感受判断。建议每个发布周期记录：

| 指标 | 定义 | 目标方向 |
| --- | --- | --- |
| 启动基线不一致率 | 新任务因路径、分支、HEAD 或状态不符而停止的比例 | 下降；但不应通过忽略差异降为零 |
| 交接拒绝率 | Worker 交付因越界、缺字段或缺验证被 Master 拒绝的比例 | 下降 |
| 集成语义冲突率 | 需要返回责任层修改的冲突数 / Worker 交付数 | 下降 |
| 投影漂移数 | 集成后重算发现的过期 hash、baseline、索引或生成投影数量 | 下降 |
| 发布门禁失败率 | 已集成候选首次运行严格门禁失败的比例 | 下降 |
| 返工往返次数 | 每个任务从首次交付到接受所需的 Worker 提交数 | 下降 |
| 等待集成时间 | `AWAITING_INTEGRATION` 到确认的时长 | 在不牺牲审查质量下缩短 |
| 未授权动作数 | 真实调用、运行、发布、删除或扩域的越权事件 | 必须为零 |

指标用于改善任务切分、契约和门禁，不用于奖励绕过停止条件或减少必要测试。至少保留任务 ID、时间点、SHA 映射和
门禁结果，避免采集聊天全文或敏感凭证。

## 17. 给另一个项目的首次改造提示词

可以把以下内容连同本文一起交给目标项目。首次任务应先调查再改造，不应在尚未理解现有分支和发布流程时
直接创建多棵工作树。

```text
请把当前仓库改造为“Master 集成 + Platform 共享能力 + Workflow/Domain 领域实现”的多对话、
多工作树协作模式，并建立可轮换的对话版本协议。

第一阶段只读调查：
1. 完整读取仓库治理文件、架构说明、分支策略、CI、发布脚本和主要目录。
2. 确认仓库绝对路径、当前分支、HEAD、工作区状态和所有现有 worktree。
3. 按代码与契约所有权提出责任分层，不要根据目录名字直接猜测。
4. 识别共享能力、领域能力、跨层入口、发布权限、历史数据和不能删除的未跟踪材料。
5. 画出当前输入/输出依赖图，指出哪些任务可以并行、哪些必须串行。
6. 报告建议拓扑、迁移风险和需要用户决定的高影响问题；调查阶段不要修改文件。

用户确认后实施：
- 建立或更新 AGENTS.md、每棵工作树的 WORKTREE_SCOPE.md/WORKTREE_TASK.md，以及长期脚本治理文档。
- 为每个长期角色绑定一个绝对工作树和分支；不要为对话换代重复创建工作树。
- 定义 Master 跨对话发送任务、Worker 核对后写入本地任务状态卡、Worker 原子提交与结构化交接、Master
  集成确认，以及 Worker 收到集成 SHA 后恢复 IDLE 的完整闭环。
- 使用 task_id、task_spec_revision、source_thread_id 和 supersedes_task_id 防止重复、过期或并发任务执行。
- Master 用 worker_handoffs 列表追踪多个 Worker，在集成树上重算 hash、baseline、索引和生成投影，并记录
  worker_commit_sha、integrated_as_sha 与 release_head_sha 的映射。
- 定义 <Role>-<major>.<minor> 对话换代协议，并明确版本标签不是 Git、业务流程、运行或权限身份。
- 所有真实外部调用、Execution/Job、发布、删除和扩域授权 default-deny，且不跨对话继承。
- 增加能验证角色边界、旧入口不可达、文档投影一致和发布命令唯一性的测试或审计。

交付物：
- 现状与目标拓扑对照；
- 完整治理文件；
- 可复制的新对话启动提示词；
- 可复制的 Master→Worker 实现任务模板；
- 可复制的 Worker→Master 完成报告模板；
- 可复制的 Master 集成确认、返工、取消/取代模板；
- 对话换代交接模板；
- 基线不一致、冲突、重复消息、对话丢失和接管的恢复规则；
- 一次不调用真实外部服务的试点任务及其 Master 集成证据；
- 全量测试、CI 或发布门禁结果。

停止条件：
- 责任边界无法从仓库确定；
- 现有工作树存在重叠未提交修改；
- 改造需要改变产品架构或生产发布权限；
- 需要删除历史数据或执行其他不可逆操作。

遇到停止条件时先报告证据和可选方案，不自行扩大范围。
```
