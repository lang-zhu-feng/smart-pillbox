# 智慧城市项目 Git 使用说明

仓库位置：`E:\学校课程\智慧城市`。Git 统一记录后端、小程序、硬件程序、数据库结构脚本和项目文档的变化。

当前采用本地版本管理，默认分支为 `main`。以后连接 GitHub 时，可以保留已有提交历史。

## 打开项目终端

在 PowerShell 中进入项目目录：

```powershell
Set-Location -LiteralPath 'E:\学校课程\智慧城市'
```

也可以在项目文件夹中打开终端。运行 `git status` 可以确认当前状态。

## 保存一个版本

完成一个小功能并检查运行结果后，依次运行：

```powershell
git status
git diff
git add --all
git diff --cached --stat
git commit -m "说明本次完成的功能"
```

- `git status`：查看哪些文件被新增、修改或删除。
- `git diff`：查看已跟踪文件中尚未暂存的文字改动；新增文件还需自行打开检查。
- `git add --all`：把当前改动加入暂存区，准备存成一个版本。
- `git diff --cached --stat`：核对本次准备保存的文件和改动数量。
- `git commit`：保存一个带说明的版本；提交说明应换成本次的实际内容。

只修改文件不会自动产生版本，运行 `git commit` 才会保存提交。Git 也不会自动上传到 GitHub。

## 配置提交者信息

第一次提交前需要设置姓名和邮箱。下面两项只作用于当前项目，不修改全局配置。请将示例替换为自己希望记录在提交历史中的信息：

```powershell
git config --local user.name "你的姓名"
git config --local user.email "你的邮箱"
```

后续准备上传 GitHub 时，也可以选择使用 GitHub 提供的隐私邮箱作为提交邮箱。

## 查看已经保存的版本

```powershell
git log --oneline -10
git show --stat HEAD
```

第一条查看最近 10 次提交，第二条查看最新提交的说明和文件变化。尚未创建首次提交时，没有可显示的提交历史。

## 哪些内容不会纳入版本

根目录的 `.gitignore` 已排除 Python 虚拟环境、微信开发者工具安装目录、依赖包、个人开发设置、缓存、日志、环境密钥配置、数据库运行文件与备份。

数据库建表脚本等项目源码可以保存；真实业务数据、数据库密码和访问密钥应保存在忽略目录或本地配置中。安全配置示例可使用 `.env.example`，只填写占位内容。

`.gitkeep` 用于保留暂时为空的数据库、硬件程序和测试代码目录。

## 以后上传 GitHub

之后在 GitHub 创建仓库，再把远程地址关联到本地仓库并推送。现阶段不配置远程地址、不执行上传，也不需要 GitHub 登录。
