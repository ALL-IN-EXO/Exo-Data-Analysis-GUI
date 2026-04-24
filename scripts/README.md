# Scripts / 小工具脚本
[status.sh](/Volumes/X10 Pro/Engineering For Lifelong Use/Exo-Data-Analysis-GUI/scripts/status.sh)
看全局状态（当前分支、改动、分支列表、最近提交）。只读，不改任何东西。

[push_current.sh](/Volumes/X10 Pro/Engineering For Lifelong Use/Exo-Data-Analysis-GUI/scripts/push_current.sh)
在“当前非 main 分支”里：add + commit + push 一条龙。
适合“我还在这个分支继续改，想更新 PR”。

[new_feature.sh](/Volumes/X10 Pro/Engineering For Lifelong Use/Exo-Data-Analysis-GUI/scripts/new_feature.sh)
把当前改动转成一个新分支并推上远程。
适合“我现在有改动，但要开一个全新 feature/.../fix/... 分支”。

[cleanup_branch.sh](/Volumes/X10 Pro/Engineering For Lifelong Use/Exo-Data-Analysis-GUI/scripts/cleanup_branch.sh)
PR merge 后清理本地分支（切 main、pull、删本地分支）。
注意：它不删远程分支。

[build_mac_JZ.sh](/Volumes/X10 Pro/Engineering For Lifelong Use/Exo-Data-Analysis-GUI/scripts/build_mac_JZ.sh)
macOS 一键打包发布脚本（PyInstaller，生成 `.app` + `.zip`）。
默认入口是 `data_analyzer_main.py`，默认 icon 使用 `Hip Exo Controller.../scripts/exoanalysis.png`。
## 脚本列表

| 脚本 | 功能 | 用法 |
|------|------|------|
| `push_current.sh` | 提交并推送当前分支 | `./scripts/push_current.sh "commit信息"` |
| `new_feature.sh` | 开新分支 → 提交 → 推送（一条龙） | `./scripts/new_feature.sh feature/xxx "commit信息"` |
| `cleanup_branch.sh` | PR merge 后清理（切main、拉最新、删分支） | `./scripts/cleanup_branch.sh` |
| `status.sh` | 一键查看 Git 状态全貌 | `./scripts/status.sh` |
| `build_mac_JZ.sh` | macOS 打包发布（.app + .zip） | `./scripts/build_mac_JZ.sh` |

## Git 协作扫盲（中文教程）

详见 [GIT_GUIDE_CN.md](GIT_GUIDE_CN.md)
