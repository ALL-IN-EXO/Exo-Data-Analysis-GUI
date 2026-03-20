#!/bin/bash
# 开新分支 → 提交改动 → 推送 → 提醒开PR
# 用法: ./scripts/new_feature.sh 分支名 "你的commit信息"
# 例子: ./scripts/new_feature.sh feature/add-emg "add: EMG数据支持"

set -e

# ============ 颜色 ============
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ============ 检查参数 ============
if [ -z "$1" ] || [ -z "$2" ]; then
    echo -e "${RED}缺少参数！${NC}"
    echo "用法: ./scripts/new_feature.sh 分支名 \"commit信息\""
    echo ""
    echo "分支命名规范:"
    echo "  feature/xxx  — 新功能"
    echo "  fix/xxx      — 修bug"
    echo "  docs/xxx     — 改文档"
    echo "  refactor/xxx — 重构"
    echo ""
    echo "例子:"
    echo "  ./scripts/new_feature.sh feature/add-emg \"add: EMG数据加载和绘图\""
    echo "  ./scripts/new_feature.sh fix/crash-on-load \"fix: 加载空CSV时崩溃\""
    exit 1
fi

BRANCH_NAME=$1
COMMIT_MSG=$2

# ============ 检查是否有未提交的改动 ============
if [ -z "$(git status --porcelain)" ]; then
    echo -e "${RED}没有任何改动，请先修改代码再运行此脚本。${NC}"
    exit 1
fi

# ============ 显示改动 ============
echo -e "${YELLOW}--- 你的改动 ---${NC}"
git status --short
echo ""
echo -e "新分支名: ${CYAN}${BRANCH_NAME}${NC}"
echo -e "提交信息: ${CYAN}${COMMIT_MSG}${NC}"
echo ""

# ============ 确认 ============
read -p "确认要创建分支并推送吗？(y/n) " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消。"
    exit 0
fi

# ============ 同步main → 开分支 → 提交 → 推送 ============
echo ""
echo -e "${YELLOW}[1/4] 同步 main...${NC}"
git stash
git checkout main
git pull origin main

echo -e "${YELLOW}[2/4] 创建新分支 ${BRANCH_NAME}...${NC}"
git checkout -b "$BRANCH_NAME"
git stash pop

echo -e "${YELLOW}[3/4] 提交改动...${NC}"
git add -A
git commit -m "$COMMIT_MSG"

echo -e "${YELLOW}[4/4] 推送到远程...${NC}"
git push -u origin "$BRANCH_NAME"

# ============ 完成提示 ============
echo ""
echo -e "${GREEN}=======================================${NC}"
echo -e "${GREEN}  新分支创建并推送成功！${NC}"
echo -e "${GREEN}=======================================${NC}"
echo ""
echo -e "分支: ${CYAN}${BRANCH_NAME}${NC}"
echo ""
echo -e "${YELLOW}下一步: 去 GitHub 创建 Pull Request${NC}"
echo -e "点击这个链接:"
echo -e "${CYAN}https://github.com/ALL-IN-EXO/Exo-Data-Analysis-GUI/pull/new/${BRANCH_NAME}${NC}"
echo ""
echo -e "PR 里写清楚:"
echo -e "  1. 改了什么"
echo -e "  2. 为什么改"
echo -e "  3. 怎么测试"
echo ""
echo -e "队友 review 通过后 → Squash and merge → 然后本地清理:"
echo -e "  git checkout main"
echo -e "  git pull origin main"
echo -e "  git branch -d ${BRANCH_NAME}"
