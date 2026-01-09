docs/设计文档  这个文件夹是我开发计划的文档
docs/使用文档  这个是我目前实际开发出来的文档。
docs/UI设计文档  就是 UI 设计文档 ，已经按照这种方式设计了
docs/WeRSS相关  这个是项目部署文档
docs/开发工作流.md  这是工作开发的工作流程
docs/key    用部署相关的一些 `key`，这个不可以提交到 GitHub.

## 常用脚本
scripts/deploy.sh  一键部署脚本：服务器拉取代码并重启服务（web/worker/beat）

## 部署注意事项
- Docker 容器修改代码后必须用 `--build` 重建镜像，仅 `restart` 不会加载新代码
- 修改模板/静态文件后需 rebuild web 容器：`docker compose up -d --build web`