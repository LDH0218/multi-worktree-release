# Capability-Specific Authorization Model

状态：设计提案；本文件不修改 Schema、Python 校验器或任何运行时代码。

适用基线：`schema_version=1`，冻结提交 `595692cc6f0b5b2a51f81d68c18cdbe7f5d5bd37`。

## 1. 结论与边界

推荐把版本化的嵌套 capability 模型作为下一版的规范持久化格式：`authorization.schema_version=2`，四种 capability 都有独立、显式的授权对象。现有 v1 flat envelope 保留为兼容读取格式，并通过一个拒绝歧义的确定性适配器转换为 v2；它不应继续作为新的规范写入格式。

这项选择解决了 v1 的三个根本问题：

1. `target`、`route`、`provider` 与预算目前是 envelope 级共享字段，无法安全表达不同 capability 的不同目标和预算。
2. 为了兼容新增字段而在 flat envelope 中复制字段，会产生两个可能互相矛盾的授权来源。
3. `target` 当前是 `string|null`，而 Python 手工校验没有把所有 Schema 类型和结构约束落实到运行时。

v2 的安全不变量如下：

- `external_call`、`create_execution`、`publish`、`destructive_operation` 互不蕴含；执行一个同时涉及多个 capability 的动作，必须取得每个 capability 的独立授权。
- 四个 capability 键始终存在。拒绝的 capability 使用完整的 `allowed=false`、`target=null`、`max_calls=0` 等显式默认值；缺失不是拒绝值，而是契约错误。
- 任何允许的 capability 都必须绑定结构化目标、受控输入摘要和有时限的授权。过期、缺字段、类型不符、摘要不符或语义不明确时一律拒绝。
- v1 到 v2 的迁移会改变授权对象的结构和摘要。它是 authority-boundary change，不能通过原 task 的普通 revision 静默扩大或改变授权；需要 Master 发布新的 superseding task。

## 2. v1 基线与已确认的缺口

当前 v1 envelope 的字段是四个顶层布尔值，以及共享的 `target`、`controlled_input`、`route`、`provider`、`max_calls`、`max_cost`、`cost_unit`、`fresh_execution_required`、`resume_execution_id`、`expires_at` 和 `envelope_digest`。

现有 Schema 已约束基本 JSON 类型，Python 校验器也检查了布尔值、非负整数、fresh/resume 互斥、受控输入摘要和 envelope 摘要。但两层仍有以下需要由下一版明确解决的差异或缺口：

- Schema 的 `target` 仍是字符串或 null，不能表达目标种类、精确资源标识和 scope。
- Schema 对 `controlled_input` 使用开放类型；摘要规范实际上只允许 null、布尔、整数、字符串、数组和字符串键对象，且禁止浮点数。
- Python 的 `TypedDict`/运行时检查（未来应采用）必须显式拒绝 `bool` 作为 `int`，拒绝额外字段，并落实 Schema 的 `minLength`、`format`、`enum` 和递归类型；不能只依赖静态类型或 `isinstance(value, int)`。
- v1 的校验把所有已允许 capability 都要求同一组 `target`、输入、route、provider 和 expiry，无法区分本地 publish/destructive 与远程调用的要求。
- `max_calls` 和 `max_cost` 是 envelope 级预算；当多个 capability 同时为 true 时，无法证明预算是否共享、复制还是分别消耗。
- `expires_at` 目前是格式检查，不等于在执行时检查“当前时间早于 expiry”。

本设计只定义契约和迁移语义，不在本任务中实现上述修订。

## 3. Capability 定义

| Capability | 允许的动作 | 不自动允许的动作 |
| --- | --- | --- |
| `external_call` | 对指定远程 service/endpoint 发起受限的真实外部调用 | 创建 job、发布、删除或覆盖资源 |
| `create_execution` | 为指定 execution system 创建一次新的 bounded execution；若明确使用 resume 模式，则只恢复指定 execution | 任意外部调用、发布或破坏性动作 |
| `publish` | 把指定 artifact/ref 暴露到指定 publication target | 发布过程所需的网络调用、创建 job 或删除旧版本；这些必须另有 capability |
| `destructive_operation` | 对指定 resource 的明确 scope 执行不可逆、删除、覆盖或权限撤销操作 | 任意其他资源、通配符范围或隐含的外部调用 |

`publish` 若需要调用远程发布服务，必须同时具有 `publish` 和 `external_call` 两个 grant；`destructive_operation` 同理。这样“业务动作”和“实现该动作所需的外部副作用”不会通过名称或调用链隐式获得。

## 4. 按 capability 的字段矩阵

下表描述“该 capability 的 `allowed=true` 时”的要求。`N` 表示字段仍必须存在，但只能使用明确的无授权值；`—` 表示该字段不属于该 capability grant，不能用 null 或默认值补齐；`C` 表示按目标 transport 或预算条件化。`allowed=false` 的完整默认值见第 6 节。

| capability | `target` | `controlled_input` / digest | `route` / `provider` | `max_calls` | `max_cost` / `cost_unit` | `expires_at` | fresh / resume | capability-specific gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `external_call` | `R`；`kind=service`、`transport=remote`；scope 可为空但不得是隐含通配符 | `R`；即使无参数也用 `{}` 并计算 digest | `R`；均为非空字符串 | `R`；至少为 1，按该 capability 独立扣减 | `C`；非负整数；`max_cost>0` 时 `cost_unit` 必须是非空字符串，等于 0 时必须为 null | `R`；带时区且执行时尚未到期 | `—`；execution-only 字段不进入此 grant | 只允许目标 service 的受控调用，不得把 provider 名称当作目标 scope |
| `create_execution` | `R`；`kind=execution`；目标 id 是 execution system/job class 的精确标识 | `R`；输入是不可变的 job spec/参数，必须有 digest | `C`；remote target 必须有非空 route/provider，local target 必须都为 null | `R`；至少为 1，创建或恢复的次数上限独立计算 | `C`；同上，预算属于 execution capability | `R`；执行时尚未到期 | `R`：新建模式为 `true/null`；恢复模式为 `false/<exact-id>`，二者只能选一 | resume 只允许指定的 execution id；不得借 resume 字段创建新 execution 或换 id |
| `publish` | `R`；`kind=publication`；scope 至少给出一个精确 ref 或 artifact path | `R`；必须绑定待发布内容/commit/ref 的 digest | `C`；remote publication 必须有非空 route/provider，local publication 必须都为 null | `N`：必须为 0；远程实现所需调用由单独 `external_call` grant 计数 | `C`；可为 0；若有发布费用，单位必须明确 | `R`；执行时尚未到期 | `—`；execution-only 字段不进入此 grant | 不因 publish=true 而自动获得外部调用、execution 或 destructive 权限 |
| `destructive_operation` | `R`；`kind=resource`；scope 至少给出一个精确 path 或 ref，禁止 `*` 等通配范围 | `R`；输入必须描述具体操作和资源版本，并有 digest | `C`；remote resource 必须有非空 route/provider，local resource 必须都为 null | `N`：必须为 0；若通过远程服务执行，另需 `external_call` | `C`；非负整数；费用上限不等于破坏性权限 | `R`；执行时尚未到期 | `—`；execution-only 字段不进入此 grant | 目标和 scope 必须足够精确以阻止“删除所有”或隐式扩大范围 |

补充规则：

- `max_calls` 是 capability-local budget，不是四种 capability 共享的 envelope budget。一个动作需要两个 capability 时，两个预算分别校验和消耗；不能把一个 grant 的剩余次数转借给另一个 grant。
- `max_cost=0` 表示该 capability 没有费用预算，而不是无限预算。未知的费用单位、浮点金额、负数或超出预算都拒绝。
- `route` 描述允许的路由/入口，`provider` 描述允许的服务提供方；二者不能只靠 `target.id` 推断。local target 必须显式使用 null。
- `expires_at` 是 envelope 级共同截止时间，保护同一受控输入下的所有 grants。若未来需要不同 capability 的 expiry，应新增明确的版本化 per-capability expiry，而不是复用过期的 root 字段。

## 5. 结构化 target

### 5.1 规范语义

v2 的 capability grant 使用以下结构，而不是字符串：

```json
{
  "kind": "service | execution | publication | resource",
  "id": "exact-stable-identifier",
  "transport": "local | remote",
  "scope": {
    "paths": ["exact/path"],
    "refs": ["exact/ref"]
  }
}
```

四个字段都是必填字段，且 target object `additionalProperties=false`。字段语义是：

- `kind` 是 capability 的目标类别。它必须分别匹配 `service`、`execution`、`publication` 或 `resource`，不能以任意字符串代替。
- `id` 是稳定、非空、大小写和空白均按原值比较的精确标识符；不得放入 secret、token 或凭据。
- `transport=remote` 时，执行必须走 envelope 中声明的 route/provider；`transport=local` 时 route/provider 必须为 null。
- `scope.paths` 和 `scope.refs` 是精确字符串列表，不是 glob。列表不能有重复项；为稳定摘要，按 UTF-8 字典序保存。一般 service/execution 可以为空；publication/resource 至少一个列表非空。
- scope 为空、含 `*`、含隐式“全部”语义或依赖调用方自行补全时，publication 和 destructive grant 无效。

推荐的 Schema 形状如下（仅为设计，不在本任务中改写 `references/contracts.schema.json`）：

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["kind", "id", "transport", "scope"],
  "properties": {
    "kind": {
      "enum": ["service", "execution", "publication", "resource"]
    },
    "id": {"type": "string", "minLength": 1},
    "transport": {"enum": ["local", "remote"]},
    "scope": {
      "type": "object",
      "additionalProperties": false,
      "required": ["paths", "refs"],
      "properties": {
        "paths": {
          "type": "array",
          "items": {"type": "string", "minLength": 1},
          "uniqueItems": true
        },
        "refs": {
          "type": "array",
          "items": {"type": "string", "minLength": 1},
          "uniqueItems": true
        }
      }
    }
  }
}
```

在 capability-specific definition 中再用 `const`/`oneOf` 收紧 `kind`：service grant 只接受 `kind=service` 且 remote，execution grant 只接受 `kind=execution`，publication grant 只接受 `kind=publication`，destructive grant 只接受 `kind=resource`。scope 非空、数组排序和禁止 `*` 属于 Python 语义校验，因为通用 JSON Schema 不足以表达所有这些跨字段规则。

### 5.2 Schema/Python 类型对齐表

Schema 类型与 Python 类型必须同时有静态声明和运行时检查，不能让其中一层隐式转换：

| Schema 规则 | Python 静态/运行时规则 | 不能接受的值 |
| --- | --- | --- |
| `boolean` | `bool`；运行时使用 `isinstance(value, bool)` | `0`、`1`、`"true"` |
| `integer`, `minimum: 0` | `int` 且 `not isinstance(value, bool)`，再检查 `>=0` | `true`、`1.0`、`"1"`、负数 |
| `string`, `minLength: 1` | `str`，不 trim、不 coercion，再检查长度 | null、空串、数字 |
| nullable string | `str | None`，分支明确 | 其他类型或空对象 |
| digest pattern | `str` + `re.fullmatch(r"sha256:[0-9a-f]{64}")` | 大写 hex、裸 hex、数字 |
| RFC 3339 date-time | `str` 解析为带 timezone 的 aware `datetime`；另做 expiry 比较 | 无时区、不可解析、已过期 |
| canonical JSON value | `None | bool | int | str | list[CanonicalValue] | dict[str, CanonicalValue]` | float、tuple、bytes、非字符串 key |
| structured target object | `TypedDict`/等价数据类 + exact-key runtime check | 字符串 target、缺 key、额外 key、任意 object |
| arrays with `uniqueItems` | `list[T]`；运行时检查成员类型、无重复、scope 已排序 | tuple、重复 scope、混合类型 |
| `additionalProperties=false` | `set(value.keys())` 必须等于定义的 required key set | 忽略未知字段或静默保留扩展字段 |

建议的 Python 类型别名（示意）为：

```python
type CanonicalValue = None | bool | int | str | list["CanonicalValue"] | dict[str, "CanonicalValue"]

class TargetScope(TypedDict):
    paths: list[str]
    refs: list[str]

class StructuredTarget(TypedDict):
    kind: Literal["service", "execution", "publication", "resource"]
    id: str
    transport: Literal["local", "remote"]
    scope: TargetScope
```

类型别名不是运行时验证器。解析 JSON 时必须禁止 float（包括 `1.0`），并在整数检查时排除 Python 中 `bool` 是 `int` 子类的情况。JSON Schema 的 `integer` 不能单独表达所有解析器的词法差异，因此“Schema `integer` + Python reject-float”才是本项目的完整契约。

### 5.3 v2 envelope 形状

推荐的 v2 顶层字段是以下固定集合，具体四个 grant 的字段集合使用 `additionalProperties=false`：

```json
{
  "schema_version": 2,
  "capabilities": {
    "external_call": {
      "allowed": false,
      "target": null,
      "route": null,
      "provider": null,
      "max_calls": 0,
      "max_cost": 0,
      "cost_unit": null
    },
    "create_execution": {
      "allowed": false,
      "target": null,
      "route": null,
      "provider": null,
      "max_calls": 0,
      "max_cost": 0,
      "cost_unit": null,
      "fresh_execution_required": true,
      "resume_execution_id": null
    },
    "publish": {
      "allowed": false,
      "target": null,
      "route": null,
      "provider": null,
      "max_calls": 0,
      "max_cost": 0,
      "cost_unit": null
    },
    "destructive_operation": {
      "allowed": false,
      "target": null,
      "route": null,
      "provider": null,
      "max_calls": 0,
      "max_cost": 0,
      "cost_unit": null
    }
  },
  "controlled_input": null,
  "controlled_input_digest": null,
  "expires_at": null,
  "envelope_digest": null
}
```

本设计在两种可选表示中明确选择第一种：`fresh_execution_required` 和 `resume_execution_id` 只存在于 `create_execution` grant。它们不是其他 grant 的 nullable/default placeholder；在 `external_call`、`publish` 和 `destructive_operation` 中出现即违反 exact-key 契约。

上例中的 `envelope_digest=null` 只表示计算摘要前的规范化输入；实际持久化的 envelope 必须写入计算出的 digest。若任意 capability 为 true，root 的 `controlled_input`、`controlled_input_digest` 和 `expires_at` 都必须为具体值；四个 capability 全部拒绝时才使用上述完整默认拒绝 envelope。对非 execution capability，execution-only 字段不进入其 grant；对 execution grant，fresh/resume 字段始终存在。

## 6. 默认拒绝和生命周期规则

### 6.1 默认拒绝

默认拒绝不是“缺字段时猜 false”，而是一个可摘要的完整对象。v2 要求：

- `schema_version`、`capabilities`、四个 capability 键和每个键的完整字段都存在。
- 不认识的 capability、字段、target kind 或 transport 直接拒绝。
- `allowed=false` 的 grant 必须是该 grant 的 canonical denied value：target/route/provider/cost unit 为 null，`max_calls/max_cost` 为 0；只有 `create_execution` grant 才有 execution-only 字段，并且其 fresh 必须为 true、resume 必须为 null。其他 grant 不得出现这两个字段。
- 只要一个 capability 为 true，所有 required context 必须满足矩阵；不会从另一个 capability 借用 target、预算、route 或 expiry。
- 授权摘要是完整性证据，不是授权本身。即使 digest 正确，缺少 capability 或运行时目标不匹配仍然拒绝。

### 6.2 expiry

- 允许的 envelope 必须有带 timezone 的 RFC 3339 `expires_at`。
- 执行时使用 UTC 比较，只有 `now < expires_at` 才允许；`now == expires_at` 已过期，拒绝，不提供隐含 grace period。
- `expires_at=null` 只允许在四个 capability 全部拒绝时出现。
- 过期后不能由 Worker 原地刷新。Master 必须重新签发/发布带新 expiry 和新摘要的 task；如果授权边界发生变化，使用 superseding task。

### 6.3 cost 与调用次数

- 所有预算使用整数原子单位；例如 `USD-cent`，不得使用浮点或未定义单位。
- `max_calls=0` 对 external/create 表示未授权，因为这两类允许动作至少要有一次；对 publish/destructive 的 grant 必须固定为 0。
- `max_cost=0` 表示零预算；`max_cost>0` 必须有非空 `cost_unit`，`max_cost=0` 时 `cost_unit` 必须为 null，避免留下误导性的预算元数据。
- 每次动作必须在执行前检查并原子预留调用数/费用；预计费用未知、单位不一致、超过上限或预算状态无法读取时拒绝。
- 预算只约束已有 capability，不会从零产生 capability，也不允许通过把费用记在另一个 grant 下绕过目标限制。

### 6.4 fresh 与 resume

- 本设计的 canonical 表示是：这两个字段只存在于 `create_execution` grant；其他 grant 必须省略它们，省略是规范要求而不是缺省补值。
- 对 `create_execution` 的 fresh 模式，`fresh_execution_required=true` 且 `resume_execution_id=null`；必须生成新的 execution id，不能复用历史 run。
- 对 `create_execution` 的 resume 模式，`fresh_execution_required=false` 且 `resume_execution_id` 为非空 exact id；只允许恢复这一个 id，不得创建新 run、替换 id 或把 id 当作模式开关。
- `create_execution` grant 两个字段同时出现、同时缺失、resume id 为空、resume id 不在受控输入/运行时上下文中，均拒绝；非 execution grant 出现任一字段也因额外字段而拒绝。
- resume 不从旧 envelope、旧 task 或对话历史继承；它必须在当前 envelope 中显式出现，并受当前 expiry、digest 和 task revision 约束。

## 7. Flat 与嵌套模型比较

### 7.1 兼容 flat-envelope revision

此方案保留四个顶层布尔值和大部分 v1 字段，最小化调用方改动；可以把 `target` 暂时扩展为 `string | structured object`，或增加 `target_v2`、`capability_limits` 等字段。

优点：

- 现有 v1 消费者和默认拒绝对象容易继续工作；迁移可以分阶段进行。
- 共享 expiry/input 的简单单 capability task 几乎不需要改变业务语义。
- 变更范围较小，短期回滚成本较低。

缺点和安全代价：

- 多个 capability 仍共享一个 target 和预算；无法安全表达“允许调用 service A，但只允许发布到 environment B”。
- `target` 的 string/object union 让 Schema/Python 必须支持弱类型兼容，容易把字符串误当作结构化目标。
- 增加 per-capability 字段会形成“顶层布尔 + capability map”的双重真相；字段不一致时必须设计额外的优先级规则。
- 用一个全局 `max_calls` 不能证明 publish/destructive 与外部调用分别受到限制。
- 继续在 v1 中原地改变 authority boundary 会让旧 task digest、旧 plan entry 和旧消费方难以区分。

如果不得不采用 flat 过渡版，至少应限制为“每个 envelope 最多一个 allowed capability”，并将 `target`、预算和 route/provider 都按该 capability 解释；超过一个 allowed capability 时拒绝，而不是复制共享值。即使如此，它也只是迁移桥，不应成为长期规范。

### 7.2 版本化嵌套 capability 模型

此方案使用 `schema_version=2` 和固定的 `capabilities` 对象；每个 capability 有自己的 target、route/provider、调用次数和费用预算，只有真正相关的 capability 才有 fresh/resume 字段。

优点：

- 数据形状直接表达 capability 边界，避免共享字段和重复授权来源。
- `additionalProperties=false`、固定四键和 capability-specific `oneOf/const` 可让 Schema 及 Python 运行时共同拒绝遗漏和错配。
- 每个目标、scope、预算和调用计数都能独立摘要、审计和消费。
- 为未来新增 capability 提供明确的版本边界，不必把旧字段继续解释成越来越多的隐式含义。

成本与控制：

- 需要 v2 Schema、Python 类型/运行时校验器和迁移测试同时上线。
- v1 的多 capability envelope 无法安全自动拆分；部分 task 必须由 Master 重新授权。
- 摘要输入变更会使 task spec、plan 中的 authorization digest 和相关 evidence 失效，需要按治理流程重新发布。

### 7.3 推荐

推荐“嵌套 v2 作为规范写入 + 严格 v1 只读适配”的组合。原因是 capability-specific target 和独立预算是安全边界，而不是展示层便利；为了短期兼容而保留共享 flat 字段会持续制造不可验证的授权歧义。兼容性应放在明确的适配器和迁移门禁中，而不是放宽规范 Schema。

## 8. Schema/Python 实现契约（后续任务范围）

未来实现必须同时更新以下几层，且每一层的字段集合保持一致：

1. JSON Schema：增加 `structured_target`、`target_scope`、四个 capability-specific grant 定义、v2 envelope；所有对象使用 exact required fields 与 `additionalProperties=false`。
2. Python 类型：用 `TypedDict`/等价类型表达 v2 的顶层和四个 grant，并以递归 `CanonicalValue` 替换开放的 `Any`；仅允许 JSON 可摘要值。
3. Python 运行时校验：检查 exact keys、bool/int 边界、字符串长度、enum、RFC 3339 timezone、target kind/transport、scope 排序与非空规则、expiry 及时钟、预算条件和 fresh/resume 互斥。
4. Digest：所有层调用同一个 canonical JSON 实现；对象 key 递归排序、数组顺序保留、UTF-8 编码、无无意义空白，计算对象摘要时把摘要字段置为 null。不得让 Schema validator 使用的归一化方式与 Python digest 方式不同。
5. 负例测试：每个矩阵的缺字段、错类型、额外字段、错误 kind、错误 transport、错误预算、过期、摘要篡改和 v1 歧义迁移都必须有明确失败断言。

Schema 的 `format=date-time` 不能替代 Python 的实际解析和 expiry 比较；Python 的静态类型也不能替代 `additionalProperties=false` 和运行时 exact-key 检查。两者的联合规则才是可执行契约。

## 9. v1 → v2 摘要与迁移规则

### 9.1 确定性映射

适配器可以读取 v1，但必须先完整验证 v1，再生成新的 v2 对象：

- 四个顶层布尔值映射为四个 grant 的 `allowed`。
- v1 的共享 `controlled_input`、`controlled_input_digest` 和 `expires_at` 映射到 v2 root；原值不重新解释、不做隐式序列化。
- v1 的 `route`、`provider`、`max_calls`、`max_cost` 和 `cost_unit` 只有在恰好一个 capability 为 true 时才能映射到那个 grant；不能把一个共享预算复制给多个 grant。
- v1 的 `fresh_execution_required`、`resume_execution_id` 只有在 `create_execution` 是唯一 allowed capability 时才能映射；若没有 `create_execution`，v1 中它们必须已经是 `true/null` 的 canonical 值，而生成的 v2 非 execution grants 省略这两个字段。任何其他 v1 值都拒绝迁移。
- v1 的字符串 `target` 没有 kind、transport 和 scope。若仅凭 capability 名称仍不能证明完整目标语义，适配器必须拒绝并请求 Master 以结构化 target 重新授权；不得从字符串命名、provider 或 route 猜测 scope。
- 对 publication/resource，缺少精确 scope 时一律拒绝迁移，即使字符串看起来像仓库或路径。

迁移成功也不复用 v1 的 `envelope_digest`：v2 的对象字段不同，必须把 v2 `envelope_digest` 置 null 后重新计算。v1 digest 可以作为外部迁移证据保存，但不能冒充 v2 digest 或写入 v2 未声明的字段。

### 9.2 任务与计划传播

- v2 authorization 改变 task spec 的 executable content 和 authority boundary；Master 必须生成新的 task（`supersedes_task_id` 指向旧 task），而不是只提高旧 task 的普通 revision。
- 新 task 的 `task_spec_digest`、authorization envelope digest、Dispatch Plan 中的 `authorization_envelope_digest` 和受影响的 acceptance/evidence digest 全部从新对象重算。
- 旧 v1 task 可以在其 digest 未变且仍处于允许状态时按原契约 grandfather；不能在原 task 内悄悄把 v1 字段解释成 v2。
- 同一 task identity 搭配不同 digest 必须拒绝。摘要相等也只能证明内容相等，不能跨版本授予新能力。

## 10. 必须拒绝的负例

| 负例 | 拒绝原因 |
| --- | --- |
| v2 缺少 `publish` capability 键，调用方把它当作 false | 缺失不是 canonical deny；固定 capability 集合被破坏 |
| `publish.allowed=true`，但只有 `external_call.allowed=false`，而发布实现需要网络调用 | capability 不可传递；必须额外授予 external call |
| v2 的 `target` 是 `"prod"` 字符串 | v2 只接受结构化 target，不能从字符串推断 kind/scope |
| destructive target 的 `scope.paths=[]` 且 `scope.refs=[]`，或含 `"*"` | 目标范围不精确，可能扩大为全量破坏 |
| remote target 的 route/provider 为 null，或 local target 带非空 provider | target transport 与路由边界矛盾 |
| external_call/create_execution 的 `max_calls=0` | 允许动作没有可用调用预算 |
| `max_cost=10` 且 `cost_unit=null`，或 `max_cost=0` 却带 `USD-cent` | 费用上限和单位不完整/误导 |
| `expires_at` 已过期或正好等于当前时间 | 执行条件是严格的 `now < expires_at` |
| `create_execution` grant 的 `fresh_execution_required=true` 同时带 resume id，或 false 却没有 exact id | fresh/resume 模式不唯一 |
| `external_call`、`publish` 或 `destructive_operation` grant 含 `fresh_execution_required` 或 `resume_execution_id` | execution-only 字段不属于这些 grant，违反 exact-key 契约 |
| `controlled_input` 非 null 但 digest 缺失/错误，或输入含 `1.0` | 受控输入未绑定，或不符合 canonical digest 类型 |
| target/scope/capability grant 含 Schema 未声明的额外字段 | `additionalProperties=false` 与 exact-key 规则失败 |
| v1 同时允许 external_call 与 publish，却把一个 flat target/budget 复制给两个 v2 grant | 迁移会放大或歧义化授权，必须重新授权 |
| v1 字符串 target 直接被包装成 v2 `id`，但没有可验证的 kind、transport 或 publication/resource scope | 迁移猜测了目标语义，拒绝并 supersede |
| v2 继续使用旧 v1 `envelope_digest` | 摘要没有覆盖新的字段结构，完整性验证失败 |

## 11. 本任务的实现边界

本任务只交付上述设计文档。Schema、Python 类型、运行时校验、迁移适配器和负例测试属于后续实现任务；本任务不修改 `references/`、`scripts/`、`SKILL.md`、`README.md`、`AGENTS.md` 或 `agents/`。
