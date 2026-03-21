#!/usr/bin/env python3
"""
backend/scripts/export_openapi.py
从已运行的 FastAPI 服务下载 OpenAPI 文档
"""

import json
import sys
from pathlib import Path

# ============ 配置 ============
SCRIPT_DIR = Path(__file__).parent.resolve()       # backend/scripts/
BACKEND_DIR = SCRIPT_DIR.parent                     # backend/
PROJECT_ROOT = BACKEND_DIR.parent                   # project/
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "openapi.json"
# ==============================


def export_openapi_schema(app) -> bool:
    """内部函数：直接利用传入的 FastAPI app 实例导出 schema"""
    try:
        schema = app.openapi()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ 导出 OpenAPI 错误: {e}")
        return False


def main():
    print(f"📄 输出路径: {OUTPUT_PATH}")
    
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from app.main import app
        
        if export_openapi_schema(app):
            print(f"✅ 完成!")
            return 0
        else:
            return 1
    except Exception as e:
        print(f"❌ 错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())