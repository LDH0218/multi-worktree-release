# Roadmap：轻量 FAST 已采用，完整 v2 继续冻结

> 状态：非规范路线图。本文描述后续产品方向和执行顺序，不改变当前 `SKILL.md`、Schema、校验器或既有 v1 行为。

## 目标

让普通低风险任务不再承担多工作树治理成本，同时保留现有 Master/Worker 流程处理复杂、高风险和需要恢复的发布任务。

最终只向用户暴露两条路径：

```text
简单任务 → FAST → 修改 → 测试 → 提交 → 已有明确授权则推送，否则先请求授权
复杂任务 → ISOLATED / STRICT → Worker 隔离 → Master 验收 → 发布门禁
```

## 当前基线

- v1 仍是正式协议和唯一规范行为。
- repository adoption 存储原型已经完成，但尚未正式启用。
- 轻量 FAST 路由已经在 Skill 中生效；FAST request / receipt 身份绑定仍是实验原型，不参与当前路由。
- 完整 v2 迁移保持冻结；cycle fence、v2 CLI、Schema 迁移和正式 adoption 不进入当前范围。

## 当前进度

- Phase 0～3：已完成。
- Phase 4：已采用 FAST 作为低风险任务的默认路径。
- Phase 3 共完成 5 个真实低风险维护任务：正确分类 `5/5`，额外治理步骤 `0`，中途升级 `0`，测试、授权或用户材料遗漏 `0`。
- 试点提交：`d628c83`、`4959390`、`9853834`、`c76a8dd`、`9c644c3`。正常 push 只复用了用户明确授予的持续授权。
- 现有 ISOLATED / STRICT 流程继续处理复杂和高风险任务；完整 v2 停车区继续冻结。
- 2026-08-31 已完成持续测试基线；下一阶段只等待真实 FAST/STRICT 任务和旧 Master 发布批次决策，不制造测试任务。

## 路线原则

1. 先解决真实痛点：简单任务流程过重。
2. 不为了完成设计文档而继续实现没有实际需求的基础设施。
3. FAST 默认不创建 Dispatch Plan、Task Spec、Worker Card、Master Card、新任务或额外 worktree。
4. FAST 只减少协作治理成本，不扩大 push、发布、外部调用或破坏性操作权限。
5. 任何不确定分类都升级到现有严格流程，不在 FAST 内继续增加状态机。
6. 每个阶段结束后先评估收益，再决定是否进入下一阶段。

## Phase 0：建立实验检查点

### 工作

- 推送已经验收的 FAST 身份绑定提交。
- 将 adoption 和 FAST binding 明确标记为实验原型。
- 冻结完整 v2 实现顺序，不继续 cycle fence 等后续模块。

### 完成标准

- `main` 与远端一致。
- 当前测试全部通过。
- 没有任何代码把 v2 当作仓库默认协议。

## Phase 1：冻结 FAST MVP 规则

### FAST 准入条件

任务必须同时满足：

- 可由一个 Codex 任务在当前工作目录完成；
- 不需要并行 Worker 或独立 worktree；
- 不修改协议、Schema、状态机、授权模型、发布语义或安全边界；
- 不涉及数据库迁移、不可逆数据修改或复杂生产操作；
- 不依赖跨对话恢复才能安全完成；
- 验收命令明确且可在本地完成；
- 外部写操作仍能在执行前单独请求明确授权。

### 强制升级条件

出现任一情况就升级为 ISOLATED 或 STRICT：

- 多个独立责任需要并行交付；
- 修改治理契约、权限、安全、持久状态或发布机制；
- 任务需要长期恢复、跨对话接管或跨机器迁移；
- 涉及生产发布、不可逆操作或高影响外部写入；
- 工作范围在执行中明显扩大；
- FAST 验收失败后无法通过一次局部修正解决；
- 无法确定任务是否仍属于低风险范围。

### 完成标准

- 分类规则短小、可解释，并能覆盖真实任务。
- 用户不需要理解 revision、digest、Card 或状态机。
- FAST 与严格流程的权限边界一致。

## Phase 2：实现最小 FAST 路径

### 用户可见流程

```text
分类 → 当前任务直接实现 → 本地验收 → 提交 → 已有明确授权则推送，否则先请求授权
```

### 最小实现范围

- 在 Skill 中增加 FAST 判定和升级规则。
- FAST 不创建新的持久协调记录。
- Git 提交和测试结果作为默认交付证据。
- 仅在确有审计价值时生成轻量 Operation Receipt；不得把 Receipt 发展成另一套 Plan/Card。
- 普通 Worker 模型保持 `gpt-5.6-luna / max / priority`；Master 仅用于实际进入严格流程的任务。

### 明确不做

- 不实现 cycle fence；
- 不实现 v2 CLI 路由；
- 不迁移 Schema 或现有 v1 记录；
- 不要求普通任务先激活 repository adoption；
- 不为 FAST 创建新的状态机、后台服务或清理系统。

### 完成标准

- 一个符合条件的简单任务可以在单任务、单工作目录内完成。
- 流程中没有 Dispatch Plan、Task Spec 或 Card。
- 测试失败、范围扩大或权限不足时能够在外部动作前升级或停止。
- 现有严格流程和契约测试保持通过。

## Phase 3：真实 Pilot

选择 5～10 个真实低风险任务使用 FAST，不为了测试而制造任务。

每个 Pilot 只记录：

- 是否正确分类；
- 完成时间和额外治理步骤数量；
- 是否发生中途升级；
- 是否遗漏测试、授权或用户材料；
- 用户是否能清楚理解当前状态和下一步。

### Pilot 通过标准

- 没有高风险任务被错误留在 FAST；
- 至少 80% 的合格简单任务无需额外任务、worktree 或持久 Card；
- FAST 相比严格流程明显减少治理步骤；
- 没有因省略 Plan/Card 导致无法恢复的重要工作；
- 用户仍在 push、发布和外部写操作前掌握决定权。

## Phase 4：正式采用（已完成）

采用结论：保留 `SKILL.md` 中“先判断 FAST”的默认路由，以及范围、风险或权限变化时升级到 ISOLATED / STRICT 的规则。

- README 已提供两条路径和 FAST 快速开始示例。
- FAST 不创建机器记录，因此不新增 FAST 模板；现有模板继续只服务严格流程。
- v1 仍是严格流程的正式协议；实验 adoption 和 FAST binding 不参与当前路由。
- force-push、生产发布、破坏性操作和其他未授权外部写入不因 FAST 获得权限。
- 如果后续真实使用出现高风险误分类、频繁升级或重要工作无法恢复，再按实际失败原因窄化或回退 FAST；不会自动启动完整 v2。

## 完整 v2：停车区

以下工作不属于当前目标：

- v1 read-only adapter；
- immutable cycle fence 和 cycle manifest；
- fence/owner cross-record 校验；
- v2 ISOLATED 和 STRICT owner 模型；
- v2 CLI、完整负向矩阵和跨机器恢复；
- Pilots B/C 与正式 repository adoption；
- Schema、validator 和 Skill 的全量 v2 迁移。

只有真实使用证明现有 v1 + FAST 无法解决问题，并且用户明确批准后，才从停车区取回对应工作。不得仅因旧设计列出了后续步骤而继续实现。

## 持续测试路线：目标模式任务

FAST 已正式采用，后续目标模式不再重新实现 Phase 0～4，而是从以下持续测试基线继续。测试复用当前 `MWR｜Master-1.0`、现有 Worker 对话和五个既有 worktree；除非用户明确要求新增长期责任角色，不创建新对话或 worktree。

### 已验证基线

- [x] **T0：状态基线**：Master 与远端 SHA 一致；五个 Worker 工作树 tracked clean，五张 Worker Card 均为 `IDLE`；当前 Plan/Task Spec/Master Card 契约校验通过。
- [x] **T1：路由与权限**：独立 Worker 完成 7/7 路由场景；危险任务不会留在 FAST，FAST、模型 profile 和消息运输均不授予 external call、create execution、publish 或 destructive 权限。
- [x] **T2：契约与实验隔离回归**：主契约测试 88/88，通过 34 项 Gate 聚焦复跑；v2 adoption 11/11、FAST binding 15/15，且两个原型未进入正式路由。
- [x] **T3：历史恢复证据**：已有真实 baseline mismatch 在 Worker `ACTIVE` 前停止；状态历史 1.0→1.1 轮换、返工 successor commit、并行 wave、候选 HEAD 失效和重新验收均有持久记录与测试证据。

基线保留两个兼容事实，不把它们误报为失败：Dispatch 图 Worker 的空闲 Card 仍是合法 v1 flat default-deny；旧 Master Card 仍为 `ACTIVE`，其旧 HEAD 候选为 `STALE`，表示该严格发布批次尚未正式关闭。

### Test Phase A：下一次真实 FAST 现场验证

- [ ] 选择下一个真实、低风险、单任务改动；不得为了完成测试制造文案或占位修改。
- [ ] 在当前 Master 对话和工作目录完成，不创建 Dispatch Plan、Task Spec、Card、新对话或额外 worktree。
- [ ] 记录分类依据、实际修改时间、验证命令、一次局部修正次数、外部授权使用和用户材料保护结果。
- [ ] 创建一个范围清晰的提交；若仍有用户授予的正常 push 持续授权，验证后自动推送 `origin/main`。

通过标准：没有危险范围留在 FAST；额外治理记录为 0；验证、授权和用户材料没有遗漏；范围扩大或第二次验收失败时在外部动作前升级。

### Test Phase B：下一次真实 STRICT 现场验证

- [ ] 只在出现真实治理、Schema、授权、状态机、持久化、发布语义或多责任任务时启动，不制造契约变更。
- [ ] 由 Master 在现有空闲 Worker 中选择长期责任最匹配者，冻结完整 SHA，并持久化 Plan、Task Spec 和默认拒绝授权。
- [ ] Master 使用 `gpt-5.6-sol / high / default`；所有 Worker 使用 `gpt-5.6-luna / max / priority`。
- [ ] Worker 完成 preflight、实现、验收、原子提交和结构化 handoff；不得自集成、同步、push 或发布。
- [ ] Master 独立审查、集成、重算证据并关闭 Worker Card；生产发布仍需单独明确授权。

通过标准：Plan/Task Spec/Card/digest 完全一致；错误 baseline 在 `ACTIVE` 前停止；handoff 提交保持不可变；返工使用 successor commit；完成后 Worker 返回 `IDLE`。

### Test Phase C：并行、恢复与故障路径

- [ ] 仅当同时存在两个真实且路径、语义所有权和依赖互不重叠的任务时验证并行 wave；否则使用现有历史证据，不创建假并行任务。
- [ ] 故障注入只使用临时 fixture、现有负向矩阵或只读历史，不改坏 live `.codex` 状态。
- [ ] 自然发生范围扩大、unexpected dependency、baseline mismatch 或 rework 时，记录停止点、保留材料、修订或 supersede 决策及最终锁状态。
- [ ] 集成树 HEAD 变化后验证旧候选证据为 `STALE`，重新运行受影响 Gate；禁止复用旧 HEAD 的通过结果。

通过标准：独立任务不会被错误阻塞；受影响 Worker 在风险动作前停止；未授权动作保持 0；恢复完成后所有工作树 tracked clean。

### Test Phase D：旧 Master 批次决策

- [ ] 只读复核 `mwr-hardening-2026-08-30`：Plan 已无非终态任务，但 Master Card 仍为 `ACTIVE`，候选为旧 HEAD 上的 `STALE`。
- [ ] 由用户决定该批次是继续认证、取消，还是被新的严格发布批次 supersede。目标模式不得自行把 `ACTIVE` 改成 `IDLE`。
- [ ] 获得决定后，按严格状态转换保存证据并验证 Plan/Master/Worker 一致性；不得删除历史 Task Spec、Card 或候选证据。

### Test Phase E：测试结论

- [ ] 汇总 FAST 分类准确率、额外治理步骤、升级次数、baseline mismatch、handoff/rework、Gate 失效和未授权动作。
- [ ] 只有 Test Phase A、B 完成且 Phase D 有明确决定后，才能结束持续测试目标。
- [ ] 若没有严重失败，保持当前 FAST + v1 STRICT，不启动完整 v2；若失败，只修复被证据证明的最窄问题。
- [ ] 测试报告只更新本路线图或一个明确指定的报告文件；验证后提交，并按已有正常 push 授权自动推送。

### 目标模式入口

建议目标为：

> 在不启动正式 v2、不制造无意义任务、不破坏 live `.codex` 状态的前提下，按 ROADMAP.md 的 Test Phase A→E 持续验证现有 FAST + v1 STRICT。复用现有 MWR Master/Worker 对话和 worktree；已完成的 T0～T3 只在当前状态变化时复验。等待并记录下一次真实 FAST 和真实 STRICT 任务，完成旧 Master 批次的用户决策，最终提交可核验测试结论。普通验证后提交可使用已授予的 `origin/main` 正常 push 权限，但 force-push、Tag、GitHub Release、生产发布、破坏性操作和其他外部系统写入仍需单独授权。

若当前没有符合 Phase A 或 B 的真实任务，目标模式必须停止本轮并报告“等待真实任务”，不得创建占位修改、假 Worker 任务或额外基础设施来推动计数。

## 停止条件

出现以下任一情况即暂停目标并向用户报告：

- FAST 实现开始复制现有严格流程的状态和记录；
- 为简单任务新增的治理代码明显超过任务执行本身；
- 需要修改正式 v2 Schema、cycle fence 或 repository adoption 才能继续；
- Pilot 显示 FAST 经常误分类或频繁升级；
- 需要新的外部权限、生产权限或不可逆操作；
- 当前阶段没有可验证的用户收益。
