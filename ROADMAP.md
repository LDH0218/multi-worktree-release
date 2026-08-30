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
- 2026-08-31 已完成即时 FAST/STRICT、失败路径、Gate 和旧 Master 取消模拟；真实任务抽样改为可选后续验证，不再阻塞当前测试目标。

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

FAST 已正式采用。目标模式可以立即使用一次性临时 Git 仓库和临时 JSON fixture 验证 FAST + v1 STRICT，不需要等待或制造真实任务。测试复用当前 `MWR｜Master-1.0`、现有 Worker 对话和五个既有 worktree；除非用户明确要求新增长期责任角色，不创建新对话或 worktree。

### 已验证基线

- [x] **T0：状态基线**：Master 与远端 SHA 一致；五个 Worker 工作树 tracked clean，五张 Worker Card 均为 `IDLE`；当前 Plan/Task Spec/Master Card 契约校验通过。
- [x] **T1：路由与权限**：独立 Worker 完成 7/7 路由场景；危险任务不会留在 FAST，FAST、模型 profile 和消息运输均不授予 external call、create execution、publish 或 destructive 权限。
- [x] **T2：契约与实验隔离回归**：主契约测试 88/88，通过 34 项 Gate 聚焦复跑；v2 adoption 11/11、FAST binding 15/15，且两个原型未进入正式路由。
- [x] **T3：历史恢复证据**：已有真实 baseline mismatch 在 Worker `ACTIVE` 前停止；状态历史 1.0→1.1 轮换、返工 successor commit、并行 wave、候选 HEAD 失效和重新验收均有持久记录与测试证据。

基线保留两个兼容事实，不把它们误报为失败：Dispatch 图 Worker 的空闲 Card 仍是合法 v1 flat default-deny；旧 Master Card 仍为 `ACTIVE`，其旧 HEAD 候选为 `STALE`，表示该严格发布批次尚未正式关闭。

### Test Phase A：即时 FAST 模拟（已完成）

- [x] 在一次性临时 Git 仓库中完成单文件任务；第一次验收按设计失败，恰好一次局部修正后通过。
- [x] 证明 FAST 没有创建 Dispatch Plan、Task Spec、Card、额外 worktree、Operation Receipt 或 adoption receipt。
- [x] 越界路径在交付前被拒绝；错误 baseline 在 `ACTIVE` 前停止；连续第二次验收失败时决定升级 STRICT。
- [x] 模拟全过程没有 external call、execution、publication 或 destructive action。

### Test Phase B：即时 STRICT 模拟（已完成）

- [x] 临时 Plan、Task Spec、Worker Card 和 Master Card 通过 Schema、digest、模型和默认拒绝授权校验。
- [x] Worker 完成 `IDLE → ACTIVE → AWAITING_INTEGRATION → ACTIVE(rework) → AWAITING_INTEGRATION → IDLE`。
- [x] Master handoff 完成 `RECEIVED → INTEGRATED`；原 Worker commit 保持可达，返工使用其 successor commit。
- [x] objective 或 frozen baseline 改变均判定为 `SUPERSEDE`，不得伪装成 `REVISE`。
- [x] Plan 历史转换、Worker/Master 历史转换和最终三记录 cross-record 一致性分别通过公开 CLI。

### Test Phase C：Candidate、Gate 与负向矩阵（已完成）

- [x] 模拟集成 HEAD 改变后返回 `ALL`，两个已注册 Gate 全部失效。
- [x] 旧 HEAD 证据复用被拒绝，没有使用 tree 或 patch 等价旁路。
- [x] 主契约套件 `88/88`、Candidate evidence 聚焦矩阵 `34/34` 均通过。
- [x] 真实 `.codex`、五张 Worker Card 和六个工作树在测试前后保持不变或 tracked clean。

### Test Phase D：旧 Master 取消模拟（已完成，未操作 live 状态）

- [x] 只复制 `mwr-hardening-2026-08-30` 的当前 Plan 和 Master Card 到临时目录。
- [x] 模拟 `ACTIVE → IDLE`：record/time 前进，活动锁清空，候选归零为 canonical v2 `NONE`，34 条 Worker handoff 原样保留。
- [x] previous/current Master 历史校验通过；真实 Master Card 仍为 `ACTIVE + STALE`，没有被关闭、取消或 supersede。
- [x] 记录设计缺口：当前协议没有规范的 Master closeout/history 持久位置，不能把清空后的当前 Card 单独当成可靠关闭历史。

### Test Phase E：结论（已完成）

- [x] 即时模拟证明当前 FAST + v1 STRICT 的主要成功和失败路径可以运行，未发现需要立即修改正式协议的 release blocker。
- [x] v2 adoption、FAST binding、cycle fence 和 v2 CLI 均未启用或进入正式路由。
- [x] 未增加长期测试脚本；临时 harness 和 fixture 不进入仓库。
- [x] 独立只读复核任务实际完成了两次运行，但应用没有返回可见报告正文，因此独立结论诚实记录为 `NOT_PROVEN`，不推断为 PASS。

### 已知限制与后续任务

- `NOT_PROVEN`：当前历史 CLI 会将 supplied previous Plan 的归档文件路径用于 Plan/Master locator 比较，而 Master 同批次又必须保持固定的 normative `dispatch_plan_path`。本轮分别验证 Plan 转换和 Worker/Master 转换，不声称得到单次 CLI 的 complete 三记录历史报告。
- `NOT_PROVEN`：旧 Master 的真实关闭历史没有规范持久位置。本轮只模拟取消；若要关闭 live 批次，应另开 STRICT 设计任务，先定义可恢复的 closeout/history 记录。
- 可选现场抽样：未来自然出现真实 FAST 或 STRICT 任务时，记录分类、额外治理步骤、升级和恢复结果；它们不再是本测试目标的完成门槛，也不得为了计数制造任务。

### 目标模式入口

建议目标为：

> 在不启动正式 v2、不修改 live `.codex`、不制造真实交付任务的前提下，立即使用一次性临时 Git 仓库和临时 JSON fixture 执行 ROADMAP.md 的 Test Phase A→E。验证 FAST 一次修正与第二次失败升级、STRICT 状态与返工、默认拒绝授权、SUPERSEDE 边界、Candidate HEAD 失效和旧 Master 取消模拟；运行 88 项主契约和 34 项 Gate 聚焦测试。开始与结束都核对真实状态哈希和工作树洁净度，缺少证据写 `NOT_PROVEN`。只更新本路线图并提交；已有正常 push 授权可以用于 `origin/main`，但 force-push、Tag、GitHub Release、生产发布、破坏性操作和其他外部系统写入仍需单独授权。

上述即时目标已于 2026-08-31 完成。后续目标模式可以重跑同样的临时验证或等待自然发生的真实任务抽样，但不得把真实抽样当成阻塞条件，也不得为它增加新的长期基础设施。

## 停止条件

出现以下任一情况即暂停目标并向用户报告：

- FAST 实现开始复制现有严格流程的状态和记录；
- 为简单任务新增的治理代码明显超过任务执行本身；
- 需要修改正式 v2 Schema、cycle fence 或 repository adoption 才能继续；
- Pilot 显示 FAST 经常误分类或频繁升级；
- 需要新的外部权限、生产权限或不可逆操作；
- 当前阶段没有可验证的用户收益。
