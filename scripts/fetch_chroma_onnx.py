# -*- coding: utf-8 -*-
"""分离进程续传下载 chroma onnx 嵌入模型（architect 规范校验节点依赖，2026-09-03 尾项）。

目标：~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz（79.3MB）
策略：urllib Range 续传 + 重试循环，网络慢（~20KB/s）则数十分钟完成；
完成后 chromadb 首次使用自动 extract。日志 scripts/../logs/onnx_download.log。
"""
import os
import sys
import time
import urllib.request
from pathlib import Path

URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
TARGET = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2" / "onnx.tar.gz"
TOTAL = 79_300_000
LOG = Path(__file__).resolve().parent.parent / "logs" / "onnx_download.log"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    size = TARGET.stat().st_size if TARGET.exists() else 0
    while size < TOTAL:
        try:
            req = urllib.request.Request(URL)
            if size:
                req.add_header("Range", f"bytes={size}-")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 206):
                    chunk = resp.read(65536)
                    if resp.status == 200 and size:
                        # 服务端不支持续传：从零重下
                        size = 0
                        with open(TARGET, "wb") as f:
                            f.write(b"")
                    with open(TARGET, "ab") as f:
                        while chunk:
                            f.write(chunk)
                            size += len(chunk)
                            chunk = resp.read(65536)
                    log(f"progress {size/1048576:.1f}/{TOTAL/1048576:.0f}MB")
        except Exception as exc:
            log(f"retry after error: {type(exc).__name__}: {exc}")
            time.sleep(15)
    log("DONE")
    print("onnx download complete:", TARGET)


if __name__ == "__main__":
    main()
