# Ocean Data Pipeline

🌊 **CTP 海洋环境数据自动获取与发布工具**

每天通过 GitHub Actions 自动从 NOAA / Copernicus Marine 获取海洋环境数据，发布到 GitHub Pages 静态网页供游戏端下载。

## 数据源

| 参数 | 数据源 | 是否需要认证 |
|------|--------|-------------|
| 🌡️ 海表温度 | NOAA CoastWatch ERDDAP | ❌ 无需 |
| 🌿 叶绿素-a | Copernicus Marine BGC | ✅ 需要 |
| 💨 溶解氧 | Copernicus Marine BGC | ✅ 需要 |
| 🧂 盐度 | Copernicus Marine PHY | ✅ 需要 |
| 🗑️ 微塑料 | 区域统计模拟 | — |

## 快速部署

### 1. 创建 GitHub 仓库

在 GitHub 上新建一个公开仓库，比如 `ocean-data-pipeline`。

### 2. 上传本目录所有文件

将本目录内容上传到仓库根目录，结构如下：

```
ocean-data-pipeline/
├── .github/workflows/fetch_ocean_data.yml
├── docs/
│   └── index.html
├── fetch_data.py
└── requirements.txt
```

### 3. 注册 Copernicus Marine 账号（免费）

1. 访问 https://marine.copernicus.eu/register-copernicus-marine-service
2. 填写邮箱和基本信息（免费，几分钟完成）
3. 记下你的用户名和密码

### 4. 配置 GitHub Secrets

在仓库页面: **Settings → Secrets and variables → Actions → New repository secret**

添加两个 secret:
- `CMEMS_USERNAME` — 你的 Copernicus 用户名
- `CMEMS_PASSWORD` — 你的 Copernicus 密码

> 💡 如果暂时不注册 Copernicus，可以跳过此步。系统会自动使用 NOAA SST + 科学估算。

### 5. 启用 GitHub Pages

1. 进入仓库 **Settings → Pages**
2. Source 选择 **Deploy from a branch**
3. Branch 选择 **gh-pages**，目录选 **/ (root)**
4. 点击 Save

### 6. 首次手动触发

进入仓库 **Actions → Fetch Ocean Data Daily → Run workflow** 手动运行一次。

完成后访问 `https://你的用户名.github.io/ocean-data-pipeline/` 即可看到数据页面。

## 游戏端接入

JSON 数据地址:
```
https://你的用户名.github.io/ocean-data-pipeline/ocean_data.json
```

## 本地测试

```bash
# 仅 NOAA (无需认证)
python fetch_data.py

# 含 Copernicus 数据
python fetch_data.py --username YOUR_USER --password YOUR_PASS
```
