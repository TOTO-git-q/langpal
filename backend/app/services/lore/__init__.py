"""世界书（酒馆 World Info 式）。规格见 docs/LORE-AND-HOOKS.md 第一节。

model     书和条目（version 2）的字段、默认值、上限；version 1 自动升级
store     world_books 表、挂接关系、旧数据迁移
match     关键词 / 正则 / 整词 / 原形匹配、次要关键词逻辑
state     按对话记的轮数、粘性、冷却
engine    触发流程：系统提示词那一路 + 每轮背景块那一路
transfer  酒馆世界书、角色卡（json / png）导入导出
"""
from .engine import Effects, SystemLore, TurnLore, commit, evaluate_turn, system_lore
from .model import Book, BookSettings, Entry, compact
from .store import (books_for, delete_book, get_book, list_books, migrate_legacy, save_book,
                    validate_profile, world_books)

__all__ = [
    "Book", "BookSettings", "Effects", "Entry", "SystemLore", "TurnLore", "books_for", "commit", "compact",
    "delete_book", "evaluate_turn", "get_book", "list_books", "migrate_legacy", "save_book", "system_lore",
    "validate_profile", "world_books",
]
