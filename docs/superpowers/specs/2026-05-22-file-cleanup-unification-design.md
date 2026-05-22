# File Cleanup Unification Design

**Date:** 2026-05-22

## Goal

梳理并统一 Edge 端临时文件、预览缓存、打印下载文件、转换文件与文件访问 token 的生命周期管理，减少重复状态、重复删除和残留资源，降低后续排查“文件没删干净 / 文件提前被删 / 状态不一致”问题的成本。

本次设计的目标不是“重写打印流程”，而是在尽量不改变现有业务行为的前提下，把清理职责收口到更少、更明确的入口。

## Non-Goals

- 不改二维码、预览、打印的接口契约
- 不调整打印任务成功/失败的业务判定规则
- 不修改当前 SSE / WebSocket 会话绑定方案
- 不把整个项目重构成复杂的资源框架或引入外部依赖
- 不处理与打印机管理、管理端 UI 无关的配置持久化问题

## Current Problems

### 1. 预览文件存在双份状态

当前至少有两份“预览文件索引”：

- `main.py` 中的全局 `preview_files`
- `file_manager.py` 中 `FileManager.preview_files`

两边都可能持有 `file_id -> path/pdf_path` 的映射，也都可能参与删除。这样会带来：

- 状态更新不同步
- 一处已经删除，另一处还以为文件存在
- URL 变化、打印提交、取消时出现重复清理

### 2. 删除入口分散

当前文件删除逻辑分散在：

- `main.py` 里直接 `os.remove(...)`
- `FileManager.cleanup_file(...)`
- `PrinterManager.submit_print_job_with_cleanup(...)`
- `portable_temp.cleanup_temp_dir(...)`

结果是“谁负责删文件”并不是单点，而是多点分散。后续要改清理策略时，很容易漏掉某个分支。

### 3. 磁盘文件与内存缓存不是同一个管理面

当前项目会同时生成和持有：

- 预览原文件
- 预览 PDF
- 打印下载文件
- 打印转换文件
- `preview_cache`
- `preview_page_cache`
- `preview_page_meta`
- `file_access_tokens`

但这些状态并不由同一个组件统一维护。部分资源有 TTL，部分只靠事件触发 `pop()`，导致异常中断时更容易残留。

### 4. token 缺乏统一过期回收

`file_access_tokens` 当前主要是“成功下载时用完即删”。若页面中断、下载失败、会话切换，token 可能残留在进程内，直到重启才消失。

### 5. 打印文件清理和任务监控耦合过深

`submit_print_job_with_cleanup()` 当前同时负责：

- 提交打印
- 判断是否成功
- 根据 `job_id` 或无 `job_id` 情况等待
- 延迟删除打印下载文件
- 延迟删除转换文件

它既是打印提交函数，又是文件生命周期控制器，职责过重。后续只要改监控逻辑，就容易连带影响文件清理。

## Design Principles

### 单一权威状态

同一类临时资源只能有一个权威 owner。业务代码不再自己维护平行映射。

### 统一释放入口

业务流程不直接做磁盘删除，只表达“这个资源该释放了”。真正的删除、缓存清空、失败兜底，都由统一组件执行。

### 渐进式收口

先统一预览链路，再统一打印链路。避免一次性大改，把风险压在当前最乱、最常出问题的区域。

### 行为尽量不变

本次优化的重点是“职责收口”，不是“时序重写”。例如：

- 打印后仍然会清理预览资源
- 启动时仍然会扫 `temp/`
- 打印下载文件仍然允许延迟清理

## Proposed Architecture

推荐保留 `file_manager.py` 和 `FileManager` 这个既有入口，但将其职责扩展为当前项目的“临时资源管理器”。

本次不强制改类名，以减少迁移成本；内部职责则统一成以下几组。

### 1. Preview Resource Registry

由 `FileManager` 成为预览资源的唯一权威 owner，维护：

- `file_id`
- `file_url`
- `source_path`
- `pdf_path`
- `created_at`
- `last_access`

它负责：

- 注册预览资源
- 更新访问时间
- 根据 `file_id` 查询预览资源
- 统一释放预览资源

`main.py` 中的全局 `preview_files` 不再作为权威状态存在。

### 2. Preview Cache Registry

`FileManager` 继续接收 `preview_cache` 引用，但进一步扩展为同时管理：

- `preview_cache`
- `preview_page_cache`
- `preview_page_meta`

释放某个 `file_id` 时，必须由一个统一方法同时完成：

- 删预览原文件
- 删预览 PDF
- 清除 base64 预览缓存
- 清除分页图片缓存
- 清除分页元信息

这样业务代码不再自己 scattered `pop()`

### 3. File Access Token Registry

把 `file_access_tokens` 纳入 `FileManager` 统一管理，提供：

- `store_file_access_token(file_id, token, expires_at)`
- `consume_file_access_token(file_id)`  
  成功返回 token，并从 registry 删除
- `cleanup_expired_tokens()`

这样 token 的“用完即删”和“过期自动删”可以共存，不再依赖 `main.py` 自己操作全局字典。

### 4. Print Artifact Registry

继续由统一管理器接管打印阶段产生的临时文件，但不改变“打印任务由打印模块提交”的事实。

需要管理的打印临时资源包括：

- 云端下载后的打印文件
- 文档转 PDF 的转换文件
- 其他打印阶段派生的临时文件

建议新增打印资源登记和释放接口，例如：

- `register_print_artifact(job_id, source_path, converted_path=None, cleanup_policy=...)`
- `release_print_artifact(job_id, reason=...)`

这里的核心思想是：

- `PrinterManager` / `cloud_websocket_client.py` 负责决定“什么时候该释放”
- `FileManager` 负责“具体怎么释放”

### 5. Startup And Shutdown Scavenger

保留当前两类兜底：

- 启动时清理 `temp/` 中超过 24 小时的遗留文件
- shutdown 时清理当前仍被 registry 跟踪的预览资源

同时在统一管理器中补齐：

- token 过期清理
- 预览缓存 TTL 清理
- 预览分页缓存 TTL 清理

打印资源的 shutdown 清理由本次实现决定是否一并纳入；若打印资源仍处于进行中，则至少要保证不会因为 shutdown 的 registry 遗留产生脏状态。

## Lifecycle After Refactor

### Preview Flow

1. 云端 `preview_file` 到达
2. `file_access_token` 存入统一 registry
3. `/api/preview` 请求到达
4. 统一 registry 提供并消费 token
5. 下载文件后登记 preview resource
6. 生成并缓存预览图
7. 后续预览命中资源时只更新 `last_access`
8. 如果 URL 变化、用户取消、打印提交或 TTL 过期，则统一释放 preview resource 和相关缓存

### Print Flow

1. 云端下发打印任务
2. 下载打印文件到 `temp/`
3. 统一 registry 登记 print artifact
4. 打印模块完成提交与任务监控
5. 监控代码只发出“成功释放 / 失败释放 / 超时释放”的决策
6. 统一 registry 负责删除打印源文件与转换文件

## Migration Strategy

### Phase 1: Preview Resource Unification

先处理最乱、最频繁的部分：

- 去掉 `main.py` 作为预览文件权威状态的职责
- 统一预览磁盘文件和预览缓存释放入口
- 去掉 URL 变化、打印提交、取消流程中的重复删除代码

这是本次重构的首要阶段，也是最值得先落地的部分。

### Phase 2: Token Lifecycle Unification

在预览资源统一之后，把：

- `file_access_tokens`

也纳入 `FileManager`，补齐 token TTL 清理与消费语义。

### Phase 3: Print Artifact Unification

最后收口打印下载文件与转换文件的删除逻辑：

- `submit_print_job_with_cleanup()` 不再自己深度负责删除实现
- 打印模块只判断释放时机
- 统一管理器负责释放动作

这一步风险最高，因此放到最后。

## Testing Strategy

### Unit Tests

新增围绕资源生命周期的独立测试，覆盖：

- 注册预览资源
- URL 变化释放
- 打印提交释放
- 用户取消释放
- 过期释放
- token 存储、消费、过期清理
- 打印资源登记与释放

### API Tests

保留并扩展当前 `/api/preview`、`/api/print`、`/api/cleanup` 的测试，验证：

- 统一后的资源管理不改变接口行为
- 打印后仍会清掉预览资源
- 取消后仍会清掉预览资源

### Regression Focus

重点防止以下回归：

- 预览文件提前被删，导致二次预览失败
- 打印后预览缓存未清，导致旧文件混入新会话
- token 被重复消费或没有及时过期
- 打印转换文件残留在 `temp/`

## Risks And Mitigations

### 风险 1：清理入口改动后误删仍在使用的文件

缓解方式：

- 先补测试再改逻辑
- Phase 1 只动预览链路，不动打印完成判定
- 所有释放接口带 `reason` 便于日志追踪

### 风险 2：预览缓存从散落 `pop()` 改成统一释放后，部分调用点漏迁移

缓解方式：

- 在 `main.py` 中搜索所有 `preview_cache` / `preview_page_cache` / `preview_page_meta` 直接操作点
- 除初始化和只读场景外，全部切到统一方法

### 风险 3：打印链路迁移时影响当前稳定的打印行为

缓解方式：

- 打印文件统一放在最后一阶段
- 先保持现有监控时序，仅迁移删除动作的 owner

## Success Criteria

满足以下条件即可认为本次统一成功：

- 预览资源只有一个权威 owner
- 业务代码不再散落直接删除预览文件
- 预览相关缓存可以按 `file_id` 一次性完整释放
- `file_access_token` 有统一存储、消费、过期清理逻辑
- 打印文件删除逻辑不再同时分散在多个模块实现细节中
- 全量测试通过，且新增生命周期测试覆盖关键回收场景
