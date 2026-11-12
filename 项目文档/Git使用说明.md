# GitHub 作品集发布与日常更新

下面的命令在**仓库根目录**的 PowerShell 执行。此仓库已配置 `origin` 远程地址；在其他电脑克隆后可用 `git remote -v` 核对。提交和推送是两步：`commit` 保存在本机，`push` 才上传到 GitHub。

## 发布前先检查

```powershell
git status --short
git diff --check
git ls-files --others --exclude-standard
```

逐个检查新增文件，特别是 `硬件/` 与 `项目文档/`。不要把 `.env`、`secrets.h`、Wi-Fi 密码、设备密钥、微信 AppSecret、SQLite 数据库、真实患者资料、日志、Arduino IDE 安装目录或个人工作笔记提交。`.gitignore` 只防止**新的、未跟踪的**文件误入；如果文件以前已经提交，仍须单独检查 Git 历史。

本仓库的 `公网扫码演示/` 是独立演示快照，启动脚本带本机路径；上传源码不会让临时二维码继续有效，也不会自动托管后端。简历中可以展示代码与截图，不能把临时链接描述为长期在线服务。

## 保存并上传

先用 `git status --short` 确认每项变更。对要公开的目录和文件逐项暂存，避免直接把尚未检查的所有内容加入：

```powershell
git add README.md .gitignore backend 微信小程序 测试代码 硬件/联调
git add 项目文档/PROJECT_BRIEF.md 项目文档/系统流程图设计.md 项目文档/小程序联动交付说明.md 项目文档/硬件接入说明.md 项目文档/微信家属通知接入.md 项目文档/全部硬件接线表.md 项目文档/Git使用说明.md
git diff --cached --name-status
git diff --cached --check
git commit -m "整理智慧药盒公开展示版本"
git push origin main
```

上面的暂存范围包含 README 直接引用的核心文档与固件。其他硬件练习、答辩素材、新增草稿及 `公网扫码演示/` 改动，请在确认内容后再分别 `git add`。删除的旧文件也要核对是否是自己希望公开的变化。没有完成检查前不要推送。

别人要直接浏览仓库，GitHub 仓库必须设为 **Public**；如果保持 Private，则需单独邀请对方并确认其已接受访问。仓库可见性是 GitHub 设置，`git push` 不会自动改变它。改为 Public 前请再次检查文件列表、旧提交历史和媒体资料是否适合公开。

## 以后如何维护

每完成一项功能或修复，先跑[根目录 README](../README.md)列出的测试，再查看 `git status --short` 和 `git diff`。按功能暂存、提交、推送；可用 `git log --oneline -5` 查看最近版本。Python 虚拟环境和本机数据库被忽略，新电脑要按 README 重新建立，不能靠 Git 恢复。
