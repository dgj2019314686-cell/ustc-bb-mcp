# 第三方来源与授权

## 工具设计参考

[changshenhan/bb-mcp](https://github.com/changshenhan/bb-mcp) 提供了课程、课件、作业、公告及两阶段提交的 MCP 工具设计参考。参考版本为提交 `1a2ea2625ea87f42e4597347813c44291e6c2553`；本项目面向中科大独立实现认证和页面适配，没有沿用港中深的账号密码编码流程。

为保留上游来源及授权说明，附其 MIT License 原文：

```text
MIT License

Copyright (c) 2026 changshenhan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

现有 `ustc-bb-helper` 仅用于核对公开页面路径与中科大状态规则，本项目没有复制其 GPL 代码。`BBMarkAssistant` 的资料仅作为认证流程调查参考，没有复制其代码。

## 运行依赖

依赖通过 `pyproject.toml` 和 `uv.lock` 安装，不将第三方包源码复制到本项目。各依赖及浏览器组件仍受其各自许可证约束：

| 依赖 | 项目来源 |
|---|---|
| MCP Python SDK | <https://github.com/modelcontextprotocol/python-sdk> |
| pyustc | <https://github.com/USTC-XeF2/pyustc> |
| HTTPX | <https://github.com/encode/httpx> |
| Beautiful Soup | <https://www.crummy.com/software/BeautifulSoup/> |
| Playwright | <https://github.com/microsoft/playwright-python> |
| keyring | <https://github.com/jaraco/keyring> |
| platformdirs | <https://github.com/tox-dev/platformdirs> |
| Pydantic | <https://github.com/pydantic/pydantic> |

打包分发安装环境或 Chromium 时，应一并保留相应依赖自带的授权文件。开发工具与 CI actions 的授权以其上游项目为准。
