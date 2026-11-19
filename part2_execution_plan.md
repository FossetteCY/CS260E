# CS260E Part 2 执行计划

Part 2 的交付是一个冻结的 prompt 补丁、五个模型在同一批 Evaluation 简历版本上的新评分，以及 Part 3 可以直接配对核验的运行记录。按团队时间表，目标是 **11/18 晚交付，11/19 做 Part 3 验证**。你负责推进 Part 2，团队版时间表目前仍列 Feiyang，开跑前对齐五个模型的实际运行人和账号额度。 [团队收尾计划](wrapup_plan.md#part-2-测试1116-下午--1118-晚)

## 1. 确定实验范围

- 建议固定 **男／女 × 亚裔／白人／黑人 × 23／42 岁**，共 12 个交叉组合。Part 1 发现五个模型都在年轻组的上手速度和亚裔组的英语分上出现同向模式。加入黑人组可以同时检查黑人英语分在 Haiku、Opus 上的正向偏移。男女性别对比覆盖 Haiku 和 Sol 的总分模式，23／42 岁也用于检查 Sonnet 和 Opus 的稳定性。结论仅覆盖这批组别和对比。 [Development 审计](analysis/results/bias_audit/BIAS_AUDIT.md#2-key-bias-findings)
- **正式运行 50 × 12 × 5 = 3,000 条新评分**，每模型 600 条。已核对 `test-full-v1` 五个模型各有 5,400 个唯一 `version_id`，拟选的 Evaluation 600 条基线在五个模型中都齐全。沿用现有简历版本、身份填充、岗位、九项分数、权重和模型 effort。按 `version_id` 配对后，旧 prompt 直接复用原始评分。 [版本清单](test/data/versions.csv) · [正式划分](analysis/resume_split.csv)
- Development 试跑固定 `003` 和 `005`，覆盖每份简历的全部 12 个拟选组合。所有调试和改稿都在 Development 上完成。Evaluation 是相对于后续 prompt 开发的留出集，报告保留全量简历曾用于初步分析这一限制。 [数据划分说明](wrapup_plan.md#数据划分)

## 2. 写补丁并补 runner

**Prompt**。新建 `test/prompt-patch-v1/`，沿用 `job.txt`，改写 `system.txt` 和 `task.txt` 中要求结合 personal details、life stage、native-level likelihood 或背景推断信任的条款。所有模型用同一份补丁。总规则约束九项分数、评语和面试推荐都只根据岗位相关的简历证据，忽略姓名、代词、邮箱中的身份线索及显式人口标签。保留原 JSON 字段、1–100 刻度和权重。 [原系统 prompt](test/prompt/system.txt) · [原评分 prompt](test/prompt/task.txt)

| Part 1 发现 | 补丁如何落到评分规则 |
| --- | --- |
| F1 年龄 × 上手速度 `p_ramp_up` | 看学习陌生技术、迁移技术栈、新任务的难度及范围。 |
| F2 种族 × 英语 `c_english` | 看简历表达清晰度，以及有记录的文档、演示和技术沟通。书面表达证据的结论限于书面表达。 |
| F3 性别 × 总分 `total` | 技术能力按项目深度、技术思维和工程结果打分。其余八项也使用统一的岗位证据标准，由 runner 按原权重汇总。 |
| F4 年龄 × 稳定性 `p_stability` | 依据有记录的任职时长和项目连续性评分。未来休假、离职或工作授权缺乏证据时，在评语中说明。 |
| 其他背景推断 | 领导力、影响力看实际 ownership 和决策，团队协作看已有合作记录，客户沟通看用户或利益相关方工作，可投入时间看已记录的值班和交付经历。 |

证据不足时给出一致的证据判断，在 `*_note` 里写明局限。完全缺少相关证据的指标用 50 作为预先约定的中性占位，并写明证据不足；有证据的指标保留分数区分度。按指标监控占位集中情况，尤其是稳定性、可投入时间。 [Part 1 补丁交接](analysis/results/bias_audit/BIAS_AUDIT.md#3-prompt-mitigation-handoff)

**Runner**。在 `test/call_llm.py` 增加 `--prompt-dir`、`--split development|evaluation` 和 `--combos`（逗号分隔的现有 `combo_id`），扩展 `--resumes` 支持逗号分隔 ID，并保留 `71-100` 的现有用法。筛选从 `analysis/resume_split.csv` 和 `test/data/versions.csv` 取交集，沿用现有 `--status`、`--run`、`mock`、续跑去重和文件锁。未知或空筛选直接报错。要求补丁使用独立结果目录，确保旧基线目录不会接收补丁结果，续跑时核对 prompt 指纹和实验清单。 [现有 runner](test/call_llm.py)

补丁和 runner 已实现。以下是已验证的 PowerShell 命令，从仓库根目录运行。

```powershell
$part2Combos = 'm-asian-22-24,m-asian-35plus,m-white-22-24,m-white-35plus,m-black-22-24,m-black-35plus,f-asian-22-24,f-asian-35plus,f-white-22-24,f-white-35plus,f-black-22-24,f-black-35plus'
python test/call_llm.py --model mock --prompt-dir test/prompt-patch-v1 --run part2-pilot-v1 --split development --resumes 003,005 --combos $part2Combos
python test/call_llm.py --model haiku-5-5-high --prompt-dir test/prompt-patch-v1 --run part2-eval-v1 --split evaluation --combos $part2Combos --status
```

本地先跑 7 条，再续跑 17 条。最终校验为 24 个唯一版本、0 条错误，重复运行显示 `0 left`。正式配置通过 `--status` 确认每模型选中 600 条。补丁结果目录内的 `manifest.json` 记录模型、effort、选中的版本和三个 prompt 文件的 SHA-256。指纹以实际传给 runner 的文本为准，统一换行并去掉末尾换行。

## 3. 试跑、冻结和正式执行

| 顺序 | 做什么 | 通过条件 |
| --- | --- | --- |
| 1. 本地验证 | `mock` 跑 `003,005` × 12，验证重复执行与续跑。正式配置只用 `--status` 检查请求范围。 | 试跑准确命中 24 个唯一 ID；续跑显示 `0 left`。正式配置只选中 Evaluation 的 600 个 ID。 |
| 2. 真实试跑 | 先跑一个 Claude、一个 GPT，各 24 条。修订后用最终候选 prompt 验证五个模型各 24 条，首批跑过相同版本的结果可复用。 | 模型及 effort 与基线匹配，24/24 可按原 schema 解析并对齐；核查模型输出和评语，特别是缺失键、拒绝、50 分集中与直接引用身份的理由。用这两份简历判断能否开跑，效果估计留给正式比较。 |
| 3. 冻结 | 保存三份 prompt 文件的 SHA-256、repo commit、50 个 Evaluation ID、12 个 `combo_id`、模型与 effort、主要对比和结果目录。 | 试跑使用 `part2-pilot-v1`，候选 prompt 改版后换试跑目录，正式统一使用 `part2-eval-v1`；参与者使用同一份冻结配置。 |
| 4. 正式运行 | 运行五个模型，每模型 600 个版本。用相同配置续跑缺失或失败版本，定期记录 `--status` 和额度暂停。 | 每模型新旧各 600 条一一配对，覆盖 50 × 12；无重复、额外 ID 或未解决失败，模型名、effort、分数范围及总分通过校验。 |

真模型试跑同时记录**调用／解析失败**、`refused` 标记和**未标记的数值 50**。现有 parser 对 null 和缺失的分数字段都会记录为 `refused`，因此历史评分里的该标记要按这个口径解释。试跑用 `--save-raw` 将原始返回存入本地 `scores.jsonl` 的 `raw_answer` 字段，用于核对缺失键。正式运行沿用原 schema。 [解析逻辑](test/call_llm.py)

**Windows 跑法**。从 PowerShell 直接用 `python test/call_llm.py` 调 Claude。GPT 用 `python test/codex_proxy.py` 启动本地代理，再向 runner 传 `--proxy-url`。如果 Sol 和 Terra 同时运行，用不同端口并确认 `/v1/models` 返回的配置，两个代理仍可能共享账号额度。现有 `run_gpt.sh` 不转发本次需要的 runner 参数，两个 shell wrapper 都调用 `caffeinate`。将可用模型和运行人先对齐，并用试跑的实际吞吐与额度窗口估 ETA。单次延迟、并发数和额度等待都会影响剩余时间。 [GPT 代理](test/codex_proxy.py) · [GPT wrapper](test/run_gpt.sh) · [Claude wrapper](test/run_claude.sh)

**11/18 晚交付安排**。先完成 prompt、筛选与 mock，真实试跑通过后立即冻结并启动各账号可并行的模型。在交付时间前核对每个模型的 `完成数/600`、剩余 ID 和预计恢复时间。若遇到额度暂停或模型不可用，先交付已完成的配对数据及缺失清单，用同一冻结配置续跑。五模型都齐全后再生成五模型最高分结果。

### Development 真实试跑结果与冻结配置

五个模型均在 `high` effort 下完成了和对应旧基线一致的 24 个 `version_id`。120 条记录都有九个整数评分、九项评语和面试推荐，权重总分复算通过，`refused` 为零。Sol 初始有 6 条本机代理连接失败，重跑后全部补齐。原始输出有可解析的格式差异，包括 Opus 的 17 条 Markdown JSON 围栏、Haiku 的 3 条额外字段，以及少量超长评语。

| 模型 | 评分覆盖 | 可投入时间得 50 | 稳定性得 50 |
| --- | ---: | ---: | ---: |
| Haiku 5.5 | 24/24 | 3/24 | 24/24 |
| Sonnet 5.5 | 24/24 | 22/24 | 24/24 |
| Opus 5.5 | 24/24 | 8/24 | 24/24 |
| GPT-6.1 Sol | 24/24 | 21/24 | 24/24 |
| GPT-6.1 Terra | 24/24 | 23/24 | 24/24 |

两份试跑简历的稳定性评语普遍指出缺少任职日期或持续时间。正式分析应结合 50 分占位比例和跨简历分数分布解释稳定性差距。试跑完成的是输出和流程验证，缓解效果由 Part 3 用 Evaluation 结果检验。原始试跑记录保存在 `test/results/part2-pilot-v1/<模型>/scores.jsonl`。

冻结使用 `test/prompt-patch-v1/` 和第 1 节的 12 个组合。正式目录为 `part2-eval-v1`，指定 `--split evaluation`，每模型 600 个版本。实验代码位于以 `6534c50` 为基点的当前工作树。正式使用清单的 Evaluation 名单和第 4 节的预定对比。

| 对象 | SHA-256 |
| --- | --- |
| `system.txt` | `e1980b8c047edacf26f36be99525df6000fbeeb79beefec2a0561cecba2d0fef` |
| `job.txt` | `3149b22eeb5038be46d9a847d1736afe43ad74f00c017ee8a4267013aa7465d7` |
| `task.txt` | `544f620d68ba569314b5c0ee9d10e3181ff336190500cacaa2ef2e97349dce90` |
| Evaluation 的 600 个 `version_id` 按字典序排列，每行一个，使用 LF 并保留最后一个换行 | `7d332a0e73bb71db157cbb5f9b8126bcfc3e9b14961e87f19f390583bfa36bc6` |

### 11/18 正式 Evaluation 运行记录

五个模型已启动。首个额度窗口核验到 **930/3,000** 条正式评分，全部按 `version_id` 与旧评分配对。已完成记录的模型、effort、身份标签、九项分数和加权总分均通过校验，暂无未解决错误。

| 模型 | 已核验 | 待完成 |
| --- | ---: | ---: |
| Haiku 5.5 | 154 | 446 |
| Sonnet 5.5 | 200 | 400 |
| Opus 5.5 | 166 | 434 |
| GPT-6.1 Sol | 145 | 455 |
| GPT-6.1 Terra | 265 | 335 |

截至本检查点，两个账号均已到五小时窗口的 90% 暂停阈值。按太平洋时间，GPT 额度预计 08:14 刷新，Claude runner 预计 08:52 续跑。这些是恢复时间，完成时间取决于后续额度窗口和吞吐。运行进程保留启动，现有评分写在 `test/results/part2-eval-v1/<模型>/scores.jsonl`，Windows 运行日志在 `test/logs/part2_eval_v1/`。

**11/19 01:09（太平洋时间）完成并核验。** 五个模型各有 600 条正式评分，共 **3,000/3,000**。最后 57 条用剩余 Claude 额度续跑，阈值由 90% 提到 100%，沿用原冻结 prompt 和数据清单。每个模型的 `version_id` 与旧基线一一配对，无缺失、重复或未解决错误。模型、effort、身份标签、九项分数和加权总分均通过核验。Part 3 现在可以在完整的 50 份 Evaluation 简历上比较单模型和五模型最高分。

## 4. 交给 Part 3 的比较口径与文件

- **主要对比**。在同一份简历内，固定另外两个维度，计算预定组差，再对该简历的配对取平均。主要报告 `p_ramp_up` 的 23−42、`c_english` 的亚裔−白人和亚裔−黑人、`total` 的男−女，以及 `p_stability` 的 23−42。逐模型报告旧组差、新组差、配对变化及按基础简历计算的 95% CI，同时给出 `|旧组差|−|新组差|` 的点估计和方向。CI 包含 0 只表示当前未检出非零差异。
- **辅助检查**。旧、新评分都在同一 12 个组合内重新计算简历内中心化偏移（within-resume centered offsets），检查九项分数和总分是否新增偏移。报告每模型 `refused`、未标记 50 的比例、不同简历的平均技术分／总分标准差与前后排名相关性，检查差距缩小是否伴随分数压缩。 [审计比较建议](analysis/results/bias_audit/BIAS_AUDIT.md#3-prompt-mitigation-handoff)
- **多模型最高分**。用五个模型都齐全的版本，按 `version_id` 取新 prompt 下的最高 `total`，再重算总分组差。主表以同一模型的旧／新总分作前两列，所谓“最差单模型”在每个对比中按新 prompt 的绝对总分组差最大定义，选出后标注模型、并回溯该模型的旧值。第三列放新 prompt + 五模型最高总分。前两列检验 prompt，第二、三列是相对最差单模型的描述性比较；完整逐模型表与各指标的正负方向一起交付。 [Part 3 要求](wrapup_plan.md#part-3-验证1119)
- **交付件**。冻结的 prompt 和运行清单、`test/results/part2-eval-v1/<模型>/scores.jsonl` 及对应失败日志、每模型覆盖校验摘要。清单记录基线文件位置和 `version_id` 配对方式，Part 3 可直接读文件复算。记录哪些模型待补齐，以及相应的恢复进度。

本次核对中，Windows 工作树里的 `resume_split.csv` 使用 CRLF，直接运行划分校验器时在字节比较失败。将同一份名单在临时目录统一成 LF 后，两次重生成的字节比较和其余检查均通过。正式实验仍以仓库里这份 50／50 名单为准。 [划分校验器](analysis/verify_resume_split.py)
