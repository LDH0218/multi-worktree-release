# Roadmap：先交付轻量 FAST，再决定是否继续 v2

> 状态：非规范路线图。本文描述后续产品方向和执行顺序，不改变当前 `SKILL.md`、Schema、校验器或既有 v1 行为。

## 目标

让普通低风险任务不再承担多工作树治理成本，同时保留现有 Master/Worker 流程处理复杂、高风险和需要恢复的发布任务。

最终只向用户暴露两条路径：

```text
简单任务 → FAST → 修改 → 测试 → 提交 → 明确授权后推送
复杂任务 → ISOLATED / STRICT → Worker 隔离 → Master 验收 → 发布门禁
```

## 当前基线

- v1 仍是正式协议和唯一规范行为。
- repository adoption 存储原型已经完成，但尚未正式启用。
- 轻量 FAST 路由已经在 Skill 中生效；FAST request / receipt 身份绑定仍是实验原型，不参与当前路由。
- 完整 v2 迁移保持冻结；cycle fence、v2 CLI、Schema 迁移和正式 adoption 不进入当前范围。

## 当前进度

- Phase 0～2：已完成。
- Phase 3：进行中，真实 Pilot `2/5`。
- Pilot 1：同步本文件中过期的阶段与 FAST 基线说明。
  - 范围：只修改当前工作目录中的 `ROADMAP.md`。
  - 验收：本地差异和工作树检查。
  - 治理成本：没有 Plan、Task Spec、Card、额外任务或 worktree；没有升级，也没有使用外部写权限。
- Pilot 2：为 README 增加本路线图入口，并同步 Pilot 进度。
  - 范围：只修改当前工作目录中的 `README.md` 和 `ROADMAP.md`。
  - 验收：链接目标、Markdown 差异和工作树检查。
  - 治理成本：没有 Plan、Task Spec、Card、额外任务或 worktree；没有升级。完成后使用用户已明确授予的正常 push 权限。

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
分类 → 当前任务直接实现 → 本地验收 → 提交 → 经授权推送
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

## Phase 4：正式采用或回退

### 采用

Pilot 通过后：

- 把 FAST 设为低风险任务的默认路径；
- 保留明确升级条件；
- 更新 README 和最小必要模板；
- 删除 Pilot 专用说明，不保留双重规则。

### 回退

Pilot 未通过时：

- 保留当前 v1 严格流程；
- 移除公开 FAST 路由；
- 保留实验提交作为研究材料，不让它成为运行时 authority；
- 根据真实失败原因决定是否做一次窄化修正，不自动重启完整 v2 工程。

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

## 目标模式执行边界

后续使用目标模式时，建议目标为：

> 在不启动正式 v2 迁移的前提下，交付并试点一个轻量 FAST MVP，使低风险单任务无需 Dispatch Plan、Task Spec、Card 或额外 worktree，并在范围、风险或权限变化时安全升级到现有严格流程。

目标模式按 Phase 0 → Phase 4 推进。每个 Phase 都是一个检查点；未达到当前阶段完成标准时不得进入下一阶段。完整 v2 停车区不属于该目标，也不能因目标持续运行而自动扩大范围。

## 停止条件

出现以下任一情况即暂停目标并向用户报告：

- FAST 实现开始复制现有严格流程的状态和记录；
- 为简单任务新增的治理代码明显超过任务执行本身；
- 需要修改正式 v2 Schema、cycle fence 或 repository adoption 才能继续；
- Pilot 显示 FAST 经常误分类或频繁升级；
- 需要新的外部权限、生产权限或不可逆操作；
- 当前阶段没有可验证的用户收益。
