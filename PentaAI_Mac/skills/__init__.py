# PentaAI Skills package
# Mỗi skill trong thư mục này phải expose:
#   SKILL_META  — dict mô tả skill
#   check_intent(text: str) -> bool
#   run(text: str, context: dict) -> dict  {"response": str, "pipeline": str}
