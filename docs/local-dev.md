# Windows 开发

## Windows 环境配置

### 1. python 环境

```bash
uv venv --python 3.12
.\.venv\Scripts\Activate.ps1
python -m ensurepip --upgrade
python -m pip install -U pip setuptools wheel
python -m pip -V
```

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
```

```bash
pip install -r requirements.txt
```