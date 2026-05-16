FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY . .

# 创建数据卷目录以持久化账号数据和缓存
RUN mkdir -p /app/data && chmod 777 /app/data

# 暴露端口
EXPOSE 8088

# 启动代理服务
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8088"]
