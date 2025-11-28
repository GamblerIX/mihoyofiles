# HoyoFiles - 米哈游游戏文件浏览器

一个功能强大的GUI应用，用于浏览和下载米哈游旗下游戏的文件资源。

## 功能特性

- 🎮 支持多款游戏：原神、崩坏·星穹铁道、绝区零、崩坏3
- 📦 游戏包和更新包管理
- 🎵 多语言语音包支持
- 📁 完整的文件树浏览
- 🔍 快速文件搜索
- 📋 文件校验和查看（MD5/Hash）
- 💾 批量链接复制

## 系统要求

- Python 3.8+
- Windows/macOS/Linux

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
python main.py
```

## 依赖

- PySide6 - Qt GUI框架
- PySide6-Fluent-Widgets - Fluent设计组件
- requests - HTTP请求库
- orjson - 高性能JSON解析

## 环境变量

- `HOYO_LOG_LEVEL` - 日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL，默认ERROR）
- `HOYO_DEMO_MODE` - 演示模式（true/false）
- `HOYO_DEMO_DURATION` - 演示模式持续时间（毫秒）
