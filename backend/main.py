from fastapi import FastAPI

app = FastAPI(
    title="独居老人智慧管理系统",
    description="用于测试项目后端服务是否正常运行",
)


@app.get("/")
def read_root():
    return {
        "message": "服药管理系统后端已启动",
        "status": "ok",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
    }
