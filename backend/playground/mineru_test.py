import requests
import os
import time

# ==========================================
# 1. 配置区域
# ==========================================
# 您的真实 API Token
API_TOKEN = "eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiI3ODgwMDcxMSIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3NTIzODkyOSwiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiMTg4NjMyMTE3OTEiLCJvcGVuSWQiOm51bGwsInV1aWQiOiI0YjhjYTA3OC0wNzIzLTRhZjMtOTkxNC1jZWIxM2RhNjVmNWUiLCJlbWFpbCI6IiIsImV4cCI6MTc4MzAxNDkyOX0.NwZss1F6SAjo25tmyQw-wyJHbIPglcR25eN-jIxqlyBvjk4sXFESTtNsGJ1TnTd-yHEpghuo4ly4a4ed5xqehg" 

BATCH_URL_API = "https://mineru.net/api/v4/file-urls/batch"

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_TOKEN}"
}

# 准备要上传的本地文件列表
local_files = [
    "./计算方法-第六章.pdf",
    # "./demo2.docx"  <-- 您可以随意注释或添加文件
]

# 动态构造请求体数据
files_payload = []
for i, file_path in enumerate(local_files):
    files_payload.append({
        "name": os.path.basename(file_path),
        "data_id": f"doc_{i+1:03d}"
    })

payload = {
    "files": files_payload,
    # model_version 可选: pipeline(默认), vlm(推荐用于PDF/图片), MinerU-HTML(仅限HTML)
    "model_version": "vlm", 
    "enable_formula": True,  # 是否开启公式识别
    "enable_table": True,    # 是否开启表格识别
    "is_ocr": False          # 是否开启 OCR 识别（针对图片文件）
}

# ==========================================
# 2. 核心功能函数
# ==========================================

def download_result_zip(zip_url, save_filename):
    """下载解析完成的 zip 文件保存到本地"""
    print(f"   ⬇️ 正在下载: {save_filename} ...")
    try:
        response = requests.get(zip_url, stream=True)
        if response.status_code == 200:
            with open(save_filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"   ✅ 下载完成，已保存为: {save_filename}")
        else:
            print(f"   ❌ 下载失败，HTTP 状态码: {response.status_code}")
    except Exception as e:
        print(f"   ❌ 下载时发生异常: {e}")

def query_and_download(batch_id):
    """轮询查询批次状态，并在完成后自动下载"""
    query_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
    query_headers = {"Authorization": f"Bearer {API_TOKEN}"} # 查询不需要 Content-Type
    
    # 记录已经下载过的文件，避免重复下载
    downloaded_files = set()
    
    print(f"\n🔍 开始监听批次 {batch_id} 的解析状态...")
    
    while True:
        try:
            response = requests.get(query_url, headers=query_headers)
            if response.status_code != 200:
                print(f"查询请求失败，HTTP 状态码: {response.status_code}")
                break
                
            result = response.json()
            if result.get("code") == 0:
                extract_results = result.get("data", {}).get("extract_result", [])
                all_done = True
                
                print("-" * 40)
                for file_info in extract_results:
                    file_name = file_info.get("file_name")
                    state = file_info.get("state")
                    
                    if state == "done":
                        # 检查是否已经下载过
                        if file_name not in downloaded_files:
                            zip_url = file_info.get("full_zip_url")
                            print(f"🎉 文件 [{file_name}] 解析完成！")
                            # 构造保存的文件名 (例如: 计算方法-第六章_result.zip)
                            base_name = os.path.splitext(file_name)[0]
                            save_name = f"{base_name}_result.zip"
                            
                            # 执行下载
                            download_result_zip(zip_url, save_name)
                            downloaded_files.add(file_name)
                    elif state == "failed":
                        if file_name not in downloaded_files:
                            print(f"❌ 文件 [{file_name}] 解析失败: {file_info.get('err_msg')}")
                            downloaded_files.add(file_name) # 标记为处理过，不再重复打印
                    else:
                        # pending 或 running
                        print(f"⏳ 文件 [{file_name}] 正在处理中，当前状态: {state}")
                        all_done = False
                
                # 如果所有文件都处理完毕（无论成功还是失败），退出循环
                if all_done:
                    print("\n🏁 批次内所有文件均已处理完毕！程序结束。")
                    break
                else:
                    print("... 等待 10 秒后重新查询 ...")
                    time.sleep(10)
            else:
                print(f"❌ 查询接口返回错误: {result.get('msg')}")
                break
                
        except Exception as e:
            print(f"查询异常: {e}")
            break

def batch_upload_and_parse():
    """主流程：申请链接 -> 上传 -> 触发查询与下载"""
    try:
        print("🚀 第一步：正在向 MinerU 申请批量上传链接...")
        response = requests.post(BATCH_URL_API, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"❌ 申请失败，HTTP 状态码: {response.status_code}")
            return

        result = response.json()
        if result.get("code") == 0:
            data = result.get("data", {})
            batch_id = data.get("batch_id")
            upload_urls = data.get("file_urls")
            
            print(f"✅ 链接申请成功！批次 ID: {batch_id}")
            print("-" * 40)
            
            print("🚀 第二步：开始上传文件...")
            for i in range(len(upload_urls)):
                file_path = local_files[i]
                target_url = upload_urls[i]
                
                if not os.path.exists(file_path):
                    print(f"⚠️ 找不到本地文件: {file_path}，跳过上传。")
                    continue
                
                print(f"正在上传 [{file_path}] ...")
                with open(file_path, 'rb') as f:
                    res_upload = requests.put(target_url, data=f)
                    
                    if res_upload.status_code == 200:
                        print(f"   -> 上传成功！")
                    else:
                        print(f"   -> ❌ 上传失败，HTTP 状态码: {res_upload.status_code}")
            
            # 第三步：进入轮询和下载阶段
            query_and_download(batch_id)
            
        else:
            print(f"❌ 申请上传链接失败，错误信息: {result.get('msg')}")

    except Exception as e:
        print(f"程序发生异常: {e}")

# ==========================================
# 3. 运行入口
# ==========================================
if __name__ == "__main__":
    batch_upload_and_parse()