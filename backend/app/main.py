from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="AiTeachMe API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 部署后替换为实际前端域名
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"message": "AiTeachMe backend is running!"}
