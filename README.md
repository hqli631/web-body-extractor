# 项目一：基于XPath的规则化网页内容提取

这是面向离线搜索网页数据处理岗位的入门项目。使用 Python、lxml 与 XPath，对已适配布局的新闻和博客 HTML 提取标题、有序正文、图片说明及结构化页面信息，并记录被排除的内容和原文位置。

项目可独立安装、运行和复验，不依赖原 web_extract_demo 目录，不需要云 GPU、模型权重或 API Key。当前定位是“多模板规则化抽取工具”，适用范围以本目录样例和规则为准。

## 1．第一次运行

需要 Python 3.10 或更高版本，并能用 pip 安装依赖。打开 VS Code 的终端，执行：

~~~powershell
cd "D:\codex project\web-body-extractor"
.\run.bat
~~~

启动脚本会准备本项目的 Python 虚拟环境、安装依赖并运行默认样例批处理。首次安装依赖需要网络，后续抽取本地 HTML 不需要访问网页。

如果希望亲手完成安装过程：

~~~powershell
cd "D:\codex project\web-body-extractor"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 .\app.py batch
~~~

若系统找不到 py，可将创建环境命令换成 python -m venv .venv。直接调用虚拟环境内的 Python，无需运行 Activate.ps1，也不需要修改 PowerShell 执行策略。

## 2．结果在哪里看

默认批处理读取 samples/manifest.json 登记的9篇历史样例（三种布局），保存：

- output/results.json：结构化抽取结果及运行状态。
- reports/index.html：便于阅读的效果报告。

另外运行 Trafilatura 外部基线对照时，会生成 output/trafilatura_comparison.json、output/trafilatura_reference/ 和 reports/trafilatura_comparison.html。

当前验收结果：9篇主回归样例提取成功并与历史基准一致，23项测试通过；Trafilatura 对照覆盖15页、0个运行错误，平均字符5-gram F1 为0.9169。具体口径与限制见 [效果评测与验收](reports/EVALUATION.md)。这不是未见网页的语义准确率。

运行后打开报告：

~~~powershell
Start-Process ".\reports\index.html"
~~~

先选择一篇新闻，查看标题、页面信息（作者、责任编辑、来源、发布时间）、段落顺序以及排除记录；再打开同一页的原始 HTML 或来源网页核对。主报告顶部还会显示“结果与Trafilatura外部基线对照”的汇总，并提供完整对照报告入口。博客样例适合观察旧式 table/font 布局和 br 分段。

报告中的程序检查用于验证输出结构、原文定位和已确认样例的回归情况。它不能独自证明跨站准确率，也不能判断没有获取到的图片像素和 JavaScript 动态正文。

## 3．提取一个本地网页

~~~powershell
.\.venv\Scripts\python.exe -X utf8 .\app.py extract --input .\samples\chinanews_01.html --output .\output\single.json
~~~

默认使用自动布局识别。需要明确选择模板时，可以加 --template：

~~~powershell
.\.venv\Scripts\python.exe -X utf8 .\app.py extract --input .\samples\chinanews_01.html --template chinanews --output .\output\single.json
~~~

可选模板以 app.py 的帮助为准：

~~~powershell
.\.venv\Scripts\python.exe .\app.py --help
.\.venv\Scripts\python.exe .\app.py extract --help
~~~

自动识别依据是 HTML 内真实存在的容器结构，不根据文件名猜网站。未知布局、容器缺失或存在歧义时应查看错误与警告，不能把空正文视为成功。

## 4．输出字段怎样理解

|字段|含义|
|---|---|
|title|提取到的文章主标题|
|blocks|按原文顺序保留的正文块，包括段落、小标题、图说和表格等|
|metadata|与正文分离的页面信息，包括作者、责任编辑、来源、发布时间或制作署名等|
|excluded|规则明确识别并移除的推广、导航或页面组件记录|
|warnings|静态解析、图片未识别、未处理结构等限制|

每个内容记录通常包含 kind、text、xpath。kind 是内容类型；text 是规范化后的文字；xpath 用于回到源 DOM 定位证据。表格还可能包含 rows，保留行列关系。

metadata 的 kind 当前包括：

|kind|页面信息类别|
|---|---|
|author|作者或记者署名|
|editor|责任编辑|
|source|来源媒体或发布机构|
|published_at|发布时间|
|production_credit|策划、统筹、制作等署名|

作者、编辑、来源和发布时间是有用的页面信息，不是广告或推荐内容。规则把它们从正文中分离，是为了让正文指标和阅读内容更清楚，而不是删除信息。主报告中的“页面信息（与正文分离）”表会直接显示类别、文本和 XPath。

“没有出现在 excluded 中”不代表该网页没有杂质。正文容器之外的导航、侧栏、评论等在定位阶段就未被选中，未必逐块写入 excluded。独立作者从正文移至 metadata 是分类修正，不是正文漏提。

## 5．文件职责

|路径|职责|
|---|---|
|app.py|命令行入口：单页抽取、样例批处理和结果保存|
|extractor.py|按结构选择模板，检查字段、XPath原文与顺序|
|rules/|按布局组织的 Python/XPath 规则实现|
|samples/|本地 HTML 演示与回归样例|
|samples/manifest.json|样例、来源、布局和版本等登记信息|
|samples/pydoc_manifest.json|Python官方 Sphinx 文档的适配与留出样例清单|
|samples/baseline.json|固定历史结果，用于发现规则修改造成的变化|
|trafilatura_baseline.py|调用 Trafilatura、规范化文本并生成外部基线对照|
|requirements.txt|本项目依赖，核心为 lxml 和固定版本的 trafilatura|
|run.bat|Windows 快速安装与批处理入口|
|tests/|规则和输出协议的回归测试|
|output/|生成的结构化结果|
|output/trafilatura_reference/|每页 Trafilatura 原始 JSON 结果，便于复核|
|reports/|可阅读的效果报告|
|reports/EVALUATION.md|本次验收结果、复验方法和评测限制|
|reports/trafilatura_comparison.html|可阅读的外部基线对照报告|
|docs/PROVENANCE.json|规则来源版本和文件哈希|
|docs/LEARNING_GUIDE.md|具体知识点与学习操作|
|docs/SCOPE.md|支持范围、样例来源和评测边界|
|docs/TRAFILATURA_BASELINE.md|基线方法、结果、差异解释和经验总结|

以实际目录和 --help 输出为准，规则文件用途也可直接阅读其模块说明。

## 6．运行测试

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
~~~

修改 XPath 或清理逻辑后，先运行测试，再重跑 batch 并查看报告。固定样例回归能发现结果变化；变化后仍需要核对是否符合抽取规范，不能简单把新输出覆盖成正确答案。

## 7．如何适配新网页

1. 保存网页 HTML，先确认文件本身含有正文文字，而不是只有动态加载的空壳。
2. 在浏览器“检查”中找到标题与正文容器，记录稳定的 id、class 或语义结构，避免依赖很长的绝对 XPath。
3. 对比同布局的两三篇文章，确认容器与段落结构能复用。一个站点可能包含多个布局。
4. 在 rules 中添加或调整规则，保留原文 XPath，不用正文句子、标题内容或文件名硬编码答案。
5. 对作者、图说、广告和真实采访问题分别判断，避免用“包含记者”“含链接”等粗规则删除正文。
6. 先用开发样例修正，再用没有参与修正的其他网页检查。已看过或用于修复的样例不能继续称为未见测试。

本项目未接入任意网站的自动采集服务。阅读和保存公开网页时应遵守目标网站的访问规则。

## 8．Trafilatura 外部基线对照

为了给规则结果增加一个独立参照，项目固定使用 [adbar/trafilatura](https://github.com/adbar/trafilatura) 作为传统正文提取基线。执行：

~~~powershell
.\.venv\Scripts\python.exe -X utf8 .\app.py baseline
~~~

默认读取主回归清单和 Python 文档清单，共15页。对照会：

- 对每页保存 Trafilatura 的 JSON 原始结果；
- 按字符 5-gram 计算精确率、召回率和 F1；
- 同时报告标题是否一致、文本块数、块级匹配率和需要人工核查的页面；
- 对去空白后覆盖率或局部相似度达到 `0.95` 的文本块按近似匹配处理，不把 `|`、空白或单个标点这类极小差异列入未匹配错误；
- 生成 output/trafilatura_comparison.json、reports/trafilatura_comparison.html 和 reports/trafilatura_comparison.md。

当前结果为15/15页成功运行、15/15标题一致、平均字符 5-gram F1 为0.9169、平均块级匹配 F1 为0.8952，其中3页因全文差异大于阈值标记为需核查。块级近似匹配按两侧合计统计，未匹配块为基线侧28个、规则侧47个；近似匹配只代表不列为块级差异，不代表两边都正确，也不在报告中展开原文。全文字符 F1 只比较正文块；作者、编辑、来源和发布时间已单独分类并在页面信息表展示，对照时也不作为正文块差异点，Trafilatura 结果里带来源、作者、编辑或发布时间标签的行同样从差异列表排除。低分不一定表示我们的结果错误：例如 pydoc_library_index 是“标准库总目录”，Trafilatura只保留导语，我们的规则保留了目录列表，F1因此很低。相反，Trafilatura也会在新浪和中新网样例中加入推荐列表或其他页面组件。

Trafilatura是外部参照，不是人工标注。它只能说明“两个抽取器的输出差异在哪里”，不能自动决定哪个结果更符合语义。出现差异时必须回到原始 HTML、规则意图和页面类型判断。完整方法与经验见 [Trafilatura外部基线说明](docs/TRAFILATURA_BASELINE.md)。

## 9．适合简历怎样写

可据实描述：使用 Python、lxml 和 XPath 实现新闻、博客和 Python 文档的多布局内容提取，输出标题、有序正文、作者/编辑/来源/发布时间等分类页面信息及原文定位证据，支持批处理、效果报告和回归检查；接入 Trafilatura 外部基线进行正文指标与抽取文本块对照，并分析基线遗漏目录、带入推荐列表、分块口径不同等问题。

不要把本项目描述为任意网页通用抽取、生产级海量系统或高准确率模型。模型训练、API Agent、自我修复和 Rubrics 模型评审属于原项目其他模块，本文件夹聚焦项目一。
