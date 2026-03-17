from fastapi.testclient import TestClient  # 导入 FastAPI 测试客户端。

from backend.app.main import app  # 导入应用实例，用来直接测试接口。

client = TestClient(app)  # 创建全局测试客户端，供下面两个测试函数复用。


def test_root_endpoint() -> None:  # 测试根路径接口是否可用。
    response = client.get("/")  # 对根路径发起 GET 请求。

    assert response.status_code == 200  # 断言根路径返回 200。
    assert response.json()["docs"] == "/docs"  # 断言响应里带有 Swagger 文档地址。


def test_health_endpoint() -> None:  # 测试健康检查接口是否可用。
    response = client.get("/api/v1/health")  # 对健康检查接口发起 GET 请求。

    assert response.status_code == 200  # 断言健康检查接口返回 200。
    assert response.json()["status"] == "ok"  # 断言健康检查结果状态为 ok。
