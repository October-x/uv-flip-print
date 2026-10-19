---
name: uv-flip-print
description: 按仓库 README 帮助用户选择单次生成 UV 浮雕变画的彩色 PNG 与高度 PNG，或安装可重复使用的本地工具；生成后附 Studio 操作步骤。用于实际打印文件，不用于普通文生图或柱镜片背印。
license: MIT
metadata:
  runtime: Python 3.12; code execution; network for dependency installation
---

# UV 变画打印文件

读取 [README.md 的“给 AI 执行的流程”](README.md#给-ai-执行的流程)。先询问用户是只生成本次图片，还是安装完整本地工具、以后重复生成；等待选择后再执行。用户已明确选择时沿用，不重复询问。安装的是本仓库独立 UV 工具，不是 Spoolio 或公网服务；不能把 AI 临时环境中安装成功说成用户电脑已安装。

生成分支按 README 执行并核对文件。默认第一张左视、第二张右视，50×50 mm、0.8 mm 浮雕，无需再次确认这些默认值；已有明确要求时按用户要求。

交付彩色图与高度图两个真实下载链接，并按 README“生成后的回复”附简短 Studio 操作步骤。不主动制作说明文档或项目附件，也不把操作步骤拆成必须逐次回复才能继续的问答。单次生成默认不附 ZIP；安装分支可提供完整系统代码下载包。

若不能执行代码或返回文件，如实说明具体限制并提供本地运行入口，不得声称已经生成。只有需要分析算法时再读 [docs/ALGORITHM.md](docs/ALGORITHM.md)。
