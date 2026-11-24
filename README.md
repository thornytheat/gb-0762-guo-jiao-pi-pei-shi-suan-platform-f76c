# 果胶批配试算台

原料工程师可检查化验单、核算干物、验现有配方、按离散称量寻优并留档。首页展示配方余量轨。顶部横向工序和左侧导航可直达各环节。来料争议样本包含互相矛盾的化验记录与不可试配的原提案。

`docker compose up --build` 后访问 `http://localhost:18461/`。本地安装 `pip install -r requirements.txt` 后，执行 `python -m flask --app app.main run --port=18461`，使用 `pytest -q` 验收。`PECTIN_ARCHIVE` 是归档目录，Compose 将它保存在命名卷中。

预览和留档 API 接收 `{"sample":"dirty"}`、`{"sample":"clean"}` 或 `{ "assays":"CSV", "plan":{...}, "proposal":{"批号":2500} }`，可另带 `"calibration":[{"device":"MA-1","measured_on":"2026-11-20","low_bp":-50,"high_bp":50,"lots":["PJ-01"]}]` 登记同台同次的共享水分偏差。计划示例见 `sample_data/dirty/trial.json`。从留档页提交，再到试配签发页审读判定和待复测原因、申请签发并下载证据。`POST /api/certificate/<id>` 申请签发（可附迟到校准单），`GET /api/certificate/<id>` 查当前判定；签发幂等，重试复用首份证书。

- [模块与复算](docs/DEPTH.md)
- [数据定义](docs/DATA-DICTIONARY.md)
