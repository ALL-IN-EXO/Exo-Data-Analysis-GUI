#!/bin/bash
# PR merge 后一键清理：切回main、拉最新、删本地分支
# 用法: ./scripts/cleanup_branch.sh

set -e

# ============ 颜色 ============
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

# ============ 当前状态 ============
CURRENT=$(git branch --show-current)
echo -e "${YELLOW}当前分支: ${CURRENT}${NC}"
echo ""

if [ "$CURRENT" = "main" ]; then
    echo -e "${YELLOW}你已经在 main 上了，拉取最新代码...${NC}"
    git pull origin main
    echo ""
    echo -e "${GREEN}main 已是最新。${NC}"
    echo ""
    # 显示可以清理的分支
    LOCAL_BRANCHES=$(git branch | grep -v '^\*' | grep -v 'main' | sed 's/^  //')
    if [ -z "$LOCAL_BRANCHES" ]; then
        echo -e "${GREEN}没有需要清理的本地分支。${NC}"
        exit 0
    fi
    echo -e "${YELLOW}以下本地分支可以清理:${NC}"
    echo "$LOCAL_BRANCHES"
    echo ""
    read -p "要删除这些分支吗？(y/n) " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        echo "$LOCAL_BRANCHES" | while read branch; do
            git branch -d "$branch" 2>/dev/null && echo -e "  ${GREEN}已删除: ${branch}${NC}" \
                || echo -e "  ${RED}跳过 ${branch}（未合并，用 git branch -D 强制删除）${NC}"
        done
    fi
    exit 0
fi

# ============ 检查未提交的改动 ============
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}警告: 当前分支有未提交的改动！${NC}"
    git status --short
    echo ""
    read -p "这些改动会丢失。确认要继续吗？(y/n) " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "已取消。请先 commit 或 stash 你的改动。"
        exit 1
    fi
fi

# ============ 切回main、拉取、删分支 ============
BRANCH_TO_DELETE=$CURRENT

echo ""
echo -e "${YELLOW}[1/3] 切换到 main...${NC}"
git checkout main

echo -e "${YELLOW}[2/3] 拉取最新代码...${NC}"
git pull origin main

echo -e "${YELLOW}[3/3] 删除本地分支 ${BRANCH_TO_DELETE}...${NC}"
git branch -d "$BRANCH_TO_DELETE" 2>/dev/null \
    && echo -e "  ${GREEN}已删除${NC}" \
    || echo -e "  ${RED}删除失败（分支可能未合并，确认PR已merge后用 git branch -D ${BRANCH_TO_DELETE}）${NC}"

# ============ 完成 ============
echo ""
echo -e "${GREEN}===============================${NC}"
echo -e "${GREEN}  清理完成！${NC}"
echo -e "${GREEN}===============================${NC}"
echo ""
echo -e "当前分支: ${CYAN}main${NC}"
echo -e "状态: 已同步远程最新代码"
