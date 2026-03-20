#!/bin/bash
# 一键查看当前 Git 状态全貌
# 用法: ./scripts/status.sh

# ============ 颜色 ============
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========== Git 状态总览 ==========${NC}"
echo ""

# ============ 当前分支 ============
CURRENT=$(git branch --show-current)
if [ "$CURRENT" = "main" ]; then
    echo -e "当前分支:  ${GREEN}${CURRENT}${NC}"
else
    echo -e "当前分支:  ${YELLOW}${CURRENT}${NC}"
fi

# ============ 与远程的同步状态 ============
git fetch origin --quiet 2>/dev/null
LOCAL=$(git rev-parse HEAD 2>/dev/null)
REMOTE=$(git rev-parse origin/"$CURRENT" 2>/dev/null)
BASE=$(git merge-base HEAD origin/"$CURRENT" 2>/dev/null)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo -e "远程同步:  ${GREEN}已同步${NC}"
elif [ "$LOCAL" = "$BASE" ]; then
    echo -e "远程同步:  ${YELLOW}远程有新提交，需要 git pull${NC}"
elif [ "$REMOTE" = "$BASE" ]; then
    AHEAD=$(git rev-list origin/"$CURRENT"..HEAD --count 2>/dev/null)
    echo -e "远程同步:  ${YELLOW}本地领先 ${AHEAD} 个提交，需要 git push${NC}"
else
    echo -e "远程同步:  ${RED}本地和远程有分歧，可能需要处理${NC}"
fi

# ============ 未提交的改动 ============
echo ""
STAGED=$(git diff --cached --stat | tail -1)
UNSTAGED=$(git diff --stat | tail -1)
UNTRACKED=$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')

if [ -z "$STAGED" ] && [ -z "$UNSTAGED" ] && [ "$UNTRACKED" = "0" ]; then
    echo -e "工作区:    ${GREEN}干净，没有未提交的改动${NC}"
else
    echo -e "${YELLOW}--- 工作区改动 ---${NC}"
    if [ -n "$STAGED" ]; then
        echo -e "  已暂存:    ${GREEN}${STAGED}${NC}"
    fi
    if [ -n "$UNSTAGED" ]; then
        echo -e "  未暂存:    ${RED}${UNSTAGED}${NC}"
    fi
    if [ "$UNTRACKED" != "0" ]; then
        echo -e "  新文件:    ${RED}${UNTRACKED} 个未追踪文件${NC}"
    fi
    echo ""
    echo -e "${YELLOW}改动文件:${NC}"
    git status --short
fi

# ============ 本地分支列表 ============
echo ""
echo -e "${YELLOW}--- 本地分支 ---${NC}"
git branch | while read line; do
    if echo "$line" | grep -q '^\*'; then
        echo -e "  ${GREEN}${line}${NC}  (当前)"
    else
        echo -e "  ${line}"
    fi
done

# ============ 最近提交 ============
echo ""
echo -e "${YELLOW}--- 最近 5 次提交 ---${NC}"
git log --oneline -5 --decorate | while read line; do
    echo -e "  ${line}"
done

# ============ 远程仓库 ============
echo ""
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
echo -e "远程仓库:  ${CYAN}${REMOTE_URL}${NC}"

echo ""
echo -e "${CYAN}=================================${NC}"
