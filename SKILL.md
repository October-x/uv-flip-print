---
name: uv-flip-print
description: 按仓库 README 将用户上传的两张原图生成用于单面 UV 浮雕变画打印的彩色 PNG 与高度 PNG；支持尺寸、透明底和实验性三图。用于实际打印文件，不用于普通文生图或柱镜片背印。
license: MIT
metadata:
  runtime: Python 3.12; code execution; network for dependency installation
---

# UV 变画打印文件

读取 [README.md 的“给 AI 执行的流程”](README.md#给-ai-执行的流程)，按其中步骤运行本技能目录中的生成程序并核对文件。默认第一张左视、第二张右视，50×50 mm、0.8 mm 浮雕，无需用户再次确认这些默认值；已有明确要求时按用户要求。

交付彩色图与高度图两个真实下载链接即可，不主动生成说明文档、项目附件、ZIP 或多轮 Studio 教学。打印步骤已写在 README，用户问到时再解释。

若不能执行代码或返回文件，如实说明具体限制并提供本地运行入口，不得声称已经生成。只有需要分析算法时再读 [docs/ALGORITHM.md](docs/ALGORITHM.md)。
