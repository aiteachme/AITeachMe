#!/usr/bin/env python3
"""
backend/scripts/export_openapi.py
从已运行的 FastAPI 服务下载 OpenAPI 文档
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# ============ 配置 ============
HOST = "127.0.0.1"
PORT = 8000

# 路径计算
SCRIPT_DIR = Path(__file__).parent.resolve()       # backend/scripts/
BACKEND_DIR = SCRIPT_DIR.parent                     # backend/
PROJECT_ROOT = BACKEND_DIR.parent                   # project/
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "openapi.json"
# ==============================


def main():
    url = f"http://{HOST}:{PORT}/openapi.json"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"📄 输出路径: {OUTPUT_PATH}")
    print(f"📥 下载: {url}")
    
    try:
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"✅ 完成!")
            return 0
    except URLError as e:
        print(f"❌ 连接失败: {e}")
        print(f"   请确保服务已启动: uvicorn app.main:app --port {PORT}")
        return 1
    except Exception as e:
        print(f"❌ 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())