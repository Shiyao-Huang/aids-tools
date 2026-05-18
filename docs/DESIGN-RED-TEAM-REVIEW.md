# AIDS 设计红队审查 — 最尖锐问题

> 每个新增设计逐一攻击，找出失败场景、token 浪费、配置陷阱、数据丢失风险
> 审查者：Lock Architect (architect)，Bach 定理视角
> 日期：2026-05-18

---

## 1. Query Router (`aids q`)

**设计**：`detect_query_target()` → 5 resolver → `format_query_text()`

### 尖锐问题

**Q1: token 爆炸 — 5 个 resolver 全跑一遍，每个都返回 items，compact 模式下真的省 token 吗？**

实测：`aids q README.md` 不加 `--include` 时默认跑 identity + history + signature + impact + ratings 五个 resolver。每个 resolver 都调 `recent_traces()`，同一个文件最多被扫描 3-4 次。`format_query_text` 在 compact 模式下截断到 1200 chars，但截断位置可能正好在关键的 impact 或 signature 结果中间。

风险：agent 收到的信息不完整——看到 "signature: ok" 但没看到 "impact: HIGH RISK" 因为被截断了。

**建议**：compact 模式应该按风险优先级排序模块输出（signature fail → bad rating → high impact → identity → history），而不是按固定 module 顺序。

**Q2: `_fuzzy_traces()` 和 `_fuzzy_sessions()` 全表扫描**

`_fuzzy_traces` 遍历所有 traces JSONL 文件的每一行。当 trace 积累到 10000+ 条时，`aids q "some random text"` 会非常慢。

**建议**：需要 O(1) 或 O(log n) 的索引，或者对 unknown kind 直接拒绝/限制扫描范围。

**Q3: detect_query_target 优先级问题**

如果 query 包含 `tr_` 前缀的普通英文单词（如 `tr_test` 是 trace ID 格式），会误判为 trace kind。实际上 `tr_` 前缀冲突概率低但非零。

---

## 2. Impact (`aids impact`)

**设计**：GitNexus → grep fallback → git log fallback → imports fallback

### 尖锐问题

**Q4: GitNexus "Multiple repositories indexed" 错误被静默吃掉**

`resolve_impact` 里检查了 `"multiple repositories indexed" not in str(gn.get("summary", "")).lower()`，但只影响 query router 的输出。`cmd_impact()` 直接调 `gitnexus_file_context(file_path, cwd)` 并无条件信任结果——如果 GitNexus 返回多 repo 错误，`gn` 会有 `available=True` 但 `summary` 是错误信息，人看到的 "GitNexus: Error: Multiple repositories indexed..." 被当成正常结果。

**建议**：`cmd_impact` 和 `resolve_impact` 应统一错误处理逻辑，不能一个有 fallback 另一个没有。

**Q5: grep fallback 的 `_grep_impact` 全目录扫描没有深度限制**

`root.rglob("*")` 会扫描整个 cwd。在大型 monorepo 中，这会遍历 node_modules、.git、build 产物等。虽然有 `ignored` 集合，但只排除了 4 个目录。一个 10000 文件的仓库会读 10000 个文件的内容。

**建议**：加文件数/时间上限，或用 `git ls-files` 代替 rglob。

**Q6: `_fallback_grep_imports` 用 ast 解析失败会怎样？**

如果目标文件不是合法 Python（如 .js、.md、JSONL），ast.parse 会抛异常。需要确认有 try/except 包裹。

---

## 3. Signature / Hash Chain

**设计**：trace 写入时记录 `pre_hash` + `post_hash`，resolver 检查状态

### 尖锐问题

**Q7: hash_chain 策略实际上没有链**

当前实现只记录每条 trace 的 `pre_hash`（操作前文件 hash）和 `post_hash`（操作后文件 hash），但**没有 trace-to-trace 的链式签名**。每条 trace 是独立的。这和真正的 hash chain（每条记录包含 `prev_record_hash`）完全不同。

用 Bach 定理 B-2 的语言：当前设计的 forge cost ≈ 删除一条 trace + 改文件。没有链式签名，攻击者可以删掉中间的 trace，剩余 trace 的 hash 都是对的。

**建议**：如果要叫 "hash_chain"，必须实现真正的链。否则改名 "per_trace_hash" 并在文档中明确声明局限性。

**Q8: `resolve_signature` 只读不验证**

它检查 `pre_hash`/`post_hash` 是否存在，但不实际重算文件 hash 并比对。`status: "hash_present"` 只表示"字段有值"，不代表"hash 正确"。

**建议**：`aids verify` 命令需要实际比对文件 hash vs 记录 hash，并报告篡改证据。

**Q9: Bash 命令没有 hash**

Bash 操作的 `resource_path` 是 `bash:command...`，不是文件路径。`sha256_file` 对 bash resource 不适用，所以 Bash trace 永远是 `unsigned`。但 Bash 是最容易伪造的工具（改命令没人知道）。

---

## 4. Identity / Session

**设计**：`register_session()` + `load_session()` + `current_session_id()`

### 尖锐问题

**Q10: identity split — 同一 agent 多个 session_id**

QA 已确认：11 个活跃 session 中，早期 trace 缺 `role`/`display_name`。根因是 `cmd_hook_post_tool_use` 写 trace 时没有从 session 文件回填身份。

但更深层的问题是：**没有 agent_id**。每次 agent 重启都是新 session_id，同一个 "Lock Architect" 会有 N 个 session 文件。`aids q` 按 session 查不到跨 session 的完整历史。

**建议**：需要稳定的 `agent_id`（基于 display_name + role + team 的 fingerprint），trace 同时记录 `session_id` + `agent_id`。

**Q11: `register_session` 每次覆盖**

每次 hook 触发都调 `register_session`，会用当前 env 覆盖 session 文件。如果 agent 的 env 变了（比如换了 task_id），旧的信息就丢了。

**建议**：punch-in 后的核心字段（display_name, role, runtime）不应被后续覆盖；可变字段（goal, task_id）应追加为 history，不覆盖。

---

## 5. Config System

**设计**：`~/.aids/config.json` + `DEFAULT_QUERY_CONFIG` + `_deep_merge_dict`

### 尖锐问题

**Q12: config 只影响 query，不impact/sign/session/doctor**

`load_aids_config()` 只在 `cmd_query` 和 resolver 里使用。`cmd_impact`、`cmd_doctor`、`cmd_stats`、`cmd_export` 都不读 config。用户在 config 里关了 impact，`aids impact` 仍然会跑。

**建议**：要么 config 是全局的（所有命令都读），要么明确声明 config scope 只覆盖 query router。不能一半一半。

**Q13: `_deep_merge_dict` 不验证 schema**

用户写错 config（如 `"signature": "hash_chain"` 而不是 `"signature": {"strategy": "hash_chain"}`），不会报错，只会在运行时静默失败或走到默认值。

**建议**：`load_aids_config` 后加 schema 验证 + `aids doctor` 检查 config validity。

---

## 6. Bash Resource Index

**设计**：`index_key()` 对长 key sha256 哈希化，`detect_resources()` 解析重定向

### 尖锐问题

**Q14: `short(tool_input.get("command"), 240)` 在 detect_resources 截断了 Bash 命令**

line 718：`cmd = short(tool_input.get("command") or "", 240)` — 超过 240 字符的 Bash 命令被截断存入 `resource_path: "bash:truncated..."`。但 `parse_bash_write_resources` 用的是原始 `tool_input.get("command")`。

问题：如果重定向在 240 字符之后（`some_long_command ... > output.txt`），`resource_path` 记录的是截断版本，`who-touched output.txt` 能查到（因为 parse_bash_write_resources 用原始命令），但 trace 记录的 `bash:` resource 是截断的。

**信息还原度被破坏**：用户说"信息还原度第一"，但 Bash trace 在 240 字符处截断。

**建议**：trace 的 `resource_path` 不截断（保真），只在 index key 和显示层截断。

**Q15: `parse_bash_write_resources` 只覆盖最简单的重定向**

需要确认覆盖了：`>file`、`> file`、`>>file`、`>> file`、`2>file`、`&>file`、`| tee file`、`| tee -a file`、`1>file`、`>file 2>&1`、heredoc `cat > file << EOF`、process substitution `> >(tee file)`、变量 `>$HOME/file`、quoted `>"file with spaces"`。

如果只覆盖了前 4 种，大量真实 Bash 命令的写入目标会被漏掉。

---

## 7. Output / Token Budget

**设计**：`format_query_text` 1200 chars 截断

### 尖锐问题

**Q16: 截断没有"渐进披露"提示**

当前截断是 `text[:max_chars-2].rstrip() + "…"`，但用户不知道被裁了什么、怎么展开。之前讨论的 `compact 742/1200 chars, hidden: history+12, more: aids q --full` 没有实现。

**建议**：截断时输出 hidden 统计和 next command 建议。

**Q17: 1200 chars 包含 emoji 和中文字符**

emoji（👤📜✍️💥⭐）在 UTF-8 中是 4 字节，中文是 3 字节。按 chars 截断和按 bytes 截断差异很大。1200 个"字符"如果是中文/emoji，实际 token 消耗远超纯 ASCII。

**建议**：预算应该按 token 估算（约 chars/4 for CJK），而不是按 chars。

---

## 8. Install / Uninstall

### 尖锐问题

**Q18: `cmd_doctor` 检查 `lock_mechanism` 但显示 "windows/msvcrt"**

line 2446：`lock_mech = "fcntl.flock" if fcntl is not None else "windows/msvcrt"`。但实际 Windows fallback 用的是 `os.rename()`，不是 msvcrt。Doctor 输出和实际实现不一致。

**Q19: 没有卸载命令**

有 `install.sh` 但没有 `uninstall.sh`。用户提到"安装和卸载脚本都需要"。`cmd_doctor` 检查 hook 配置存在，但没有命令移除它们。

---

## 9. 并发 / FileLock

### 尖锐问题

**Q20: `acquire_with_timeout` 在 Windows rename 模式下 busy-wait**

`_try_acquire_rename` 用 `os.rename(temp, lock)` 原子性获取锁，但 `acquire_with_timeout` 的 retry loop 在高并发下会反复创建临时文件然后 rename 失败。每次 retry 都有文件 I/O。

**建议**：rename fallback 的 retry interval 应该更长（1s 而不是 0.5s），或者用 exponential backoff。

---

## 总结：最高优先级修复

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| Q7 | hash_chain 不是真正的链 | B-2 定理不满足，forge cost 虚高 | **P0** |
| Q10 | 无 agent_id，身份分裂 | 跨 session 查询失效，审计断裂 | **P0** |
| Q14 | Bash 命令 240 截断破坏保真 | 信息还原度被破坏（用户明确要求） | **P0** |
| Q1 | compact 截断可能丢关键信息 | agent 看不到 HIGH RISK | **P1** |
| Q4 | GitNexus 多 repo 错误处理不统一 | impact 命令输出垃圾 | **P1** |
| Q12 | config 只影响 query | 用户以为关了模块但没关 | **P1** |
| Q16 | 截断无渐进披露提示 | 用户不知道被裁了什么 | **P1** |
| Q2 | fuzzy 全表扫描 | 性能随数据量线性退化 | **P2** |
| Q8 | signature 只读不验证 | `hash_present` 不代表 `hash_correct` | **P2** |
| Q13 | config 无 schema 验证 | 静默配置错误 | **P2** |
