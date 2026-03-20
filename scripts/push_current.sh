#!/bin/bash
# 推送当前分支的改动到远程
# 用法: ./scripts/push_current.sh "你的commit信息"

set -e

# ============ 颜色 ============
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ============ 检查参数 ============
if [ -z "$1" ]; then
    echo -e "${RED}请提供 commit 信息！${NC}"
    echo "用法: ./scripts/push_current.sh \"add: 新增了xxx功能\""
    exit 1
fi

# ============ 检查当前分支 ============
BRANCH=$(git branch --show-current)
echo -e "${YELLOW}当前分支: ${BRANCH}${NC}"

if [ "$BRANCH" = "main" ]; then
    echo -e "${RED}你现在在 main 分支！不能直接推送到 main。${NC}"
    echo -e "请先创建新分支: ./scripts/new_feature.sh 分支名 \"commit信息\""
    exit 1
fi

# ============ 显示改动 ============
echo ""
echo -e "${YELLOW}--- 当前改动 ---${NC}"
git status --short
echo ""

# ============ 确认 ============
read -p "确认要提交并推送这些改动吗？(y/n) " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消。"
    exit 0
fi

# ============ 添加、提交、推送 ============
git add -A
git commit -m "$1"
git push -u origin "$BRANCH"

# ============ 完成提示 ============
echo ""
echo -e "${GREEN}===============================${NC}"
echo -e "${GREEN}  推送成功！${NC}"
echo -e "${GREEN}===============================${NC}"
echo ""
echo -e "分支: ${YELLOW}${BRANCH}${NC}"
echo -e "下一步: 去 GitHub 检查你的 PR"
echo -e "链接: ${YELLOW}https://github.com/ALL-IN-EXO/Exo-Data-Analysis-GUI/pulls${NC}"
echo ""
echo -e "如果还没开 PR，点这里创建:"
echo -e "${YELLOW}https://github.com/ALL-IN-EXO/Exo-Data-Analysis-GUI/pull/new/${BRANCH}${NC}"
echo ""
echo -e "PR merge 后记得本地清理:"
echo -e "  git checkout main"
echo -e "  git pull origin main"
echo -e "  git branch -d ${BRANCH}"
