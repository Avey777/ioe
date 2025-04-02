# 🐳 Docker 部署指南

## 环境要求

- Docker 19.03.0+
- Docker Compose 1.29.0+

## 使用 Docker Compose 部署

### 1. 克隆项目

```bash
git clone <项目地址>
cd ioe
```

### 2. 配置环境变量（可选）

如需自定义配置，可以修改 `docker-compose.yml` 文件中的环境变量，主要包括：
- 数据库配置（POSTGRES_*）
- Django 配置（DJANGO_*）
- 邮件配置（EMAIL_*）
- 超级管理员账户（DJANGO_SUPERUSER_*）
- API 密钥配置（BARCODE_API_KEY, ALI_BARCODE_APPCODE）

### 3. 启动服务

```bash
# 构建并启动所有服务
docker compose up -d

# 查看服务状态
docker compose ps

# 查看服务日志
docker compose logs -f
```

### 4. 访问系统

服务启动后，可以通过以下地址访问：
- 主系统：http://localhost:8000
- 管理后台：http://localhost:8000/admin

默认超级管理员账户：
- 用户名：admin
- 密码：admin123

## 数据持久化

系统使用 Docker volumes 实现数据持久化，包括：
- `postgres_data`：数据库文件
- `media_volume`：用户上传的媒体文件
- `backup_volume`：系统备份文件
- `temp_volume`：临时文件
- `log_volume`：应用日志
- `static_volume`：静态文件
- `redis_data`：Redis 缓存数据

## 服务说明

系统包含以下 Docker 服务：
1. **web**：Django 应用主服务
   - 运行在 8000 端口
   - 使用 Gunicorn 作为 WSGI 服务器
   - 自动进行数据库迁移和静态文件收集

2. **db**：PostgreSQL 数据库服务
   - 版本：PostgreSQL 15
   - 运行在 5432 端口
   - 自动创建数据库和用户

3. **redis-ioe**：Redis 缓存服务
   - 版本：Redis 7
   - 运行在 6379 端口
   - 启用数据持久化

## 常用操作命令

```bash
# 停止所有服务
docker compose down

# 重启特定服务
docker compose restart web

# 查看服务日志
docker compose logs -f web

# 进入容器执行命令
docker compose exec web bash

# 备份数据库
docker compose exec db pg_dump -U postgres ioe > backup.sql

# 恢复数据库
docker compose exec -T db psql -U postgres ioe < backup.sql
```

## 注意事项

1. 首次启动时，系统会自动：
   - 创建数据库表
   - 收集静态文件
   - 创建超级管理员账户

2. 生产环境部署建议：
   - 修改默认的数据库密码
   - 更改超级管理员密码
   - 配置 HTTPS
   - 设置适当的 ALLOWED_HOSTS
   - 关闭 DEBUG 模式 