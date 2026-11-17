# Trafilatura 外部基线对照

生成时间（UTC）：2026-11-17T01:38:27.134540+00:00

Trafilatura 版本：2.3.1

上游仓库：https://github.com/adbar/trafilatura

| 页面 | 分组 | 我们正文块 | 页面信息 | 基线行数 | 标题一致 | 需核查 | 精确率 | 召回率 | F1 |
| --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |
| chinanews_01 | manifest | 7 | 3 | 13 | 是 | 是 | 1.000 | 0.796 | 0.886 |
| chinanews_02 | manifest | 26 | 4 | 30 | 是 | 否 | 0.910 | 0.918 | 0.914 |
| chinanews_03 | manifest | 33 | 4 | 36 | 是 | 是 | 0.883 | 0.940 | 0.911 |
| sina_01 | manifest | 43 | 3 | 49 | 是 | 否 | 1.000 | 0.968 | 0.984 |
| sina_02 | manifest | 23 | 3 | 28 | 是 | 否 | 1.000 | 0.972 | 0.986 |
| sina_03 | manifest | 16 | 2 | 22 | 是 | 否 | 1.000 | 0.946 | 0.972 |
| pg_essay_01 | manifest | 67 | 0 | 7 | 是 | 否 | 0.991 | 0.987 | 0.989 |
| pg_essay_02 | manifest | 141 | 0 | 1 | 是 | 否 | 1.000 | 1.000 | 1.000 |
| pg_essay_03 | manifest | 79 | 0 | 5 | 是 | 否 | 1.000 | 0.992 | 0.996 |
| pydoc_intro | pydoc_tutorial | 115 | 0 | 303 | 是 | 否 | 0.977 | 1.000 | 0.989 |
| pydoc_data | pydoc_tutorial | 148 | 0 | 412 | 是 | 否 | 0.992 | 1.000 | 0.996 |
| pydoc_control | pydoc_tutorial | 203 | 0 | 542 | 是 | 否 | 0.996 | 1.000 | 0.998 |
| pydoc_library_index | pydoc_tutorial | 39 | 0 | 5 | 是 | 是 | 0.081 | 1.000 | 0.149 |
| pydoc_interpreter | pydoc_tutorial | 32 | 0 | 40 | 是 | 否 | 0.970 | 1.000 | 0.985 |
| pydoc_appetite | pydoc_tutorial | 16 | 0 | 16 | 是 | 否 | 1.000 | 1.000 | 1.000 |

## 口径

- Trafilatura 使用默认回退路径，关闭评论，保留表格。
- 两边都做 Unicode 兼容规范化和空白规范化，去掉 Sphinx 标题末尾的 `¶`。
- 标题不参加正文比较；Trafilatura 的列表符号在比较前去掉。
- 作者、编辑、来源、发布时间等页面信息单独分类保存；Trafilatura 对照只比较正文块。
- 主要指标是正文压缩后的字符 5-gram 精确率、召回率和 F1；顺序比仅作辅助。
- Trafilatura 是外部参照，不是绝对金标。差异必须结合原始 HTML 和规则意图判断。
