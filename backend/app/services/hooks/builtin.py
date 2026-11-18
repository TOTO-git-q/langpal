"""自带的规则。首次启动写入；可以改、可以关、不能删。

升级时：用户没碰过的（updated_at == created_at）跟着这里的新定义走；用户改过的一律不动。
新加的自带规则在下次启动时补进去。
"""
BUILTINS: list[dict] = [
    {"builtin": "reunion", "name": "久别重逢", "enabled": True, "event": "chat.open",
     "conditions": [{"field": "idle_days", "op": ">=", "value": 2}], "once_per": "day",
     "actions": [{"type": "say", "directive": "对方已经 {{idle_days}} 天没来找你了。按你的性格先开口。"}]},
    {"builtin": "late_night", "name": "深夜", "enabled": True, "event": "chat.user_message",
     "conditions": [{"field": "hour", "op": "between", "value": [1, 4]}], "once_per": "day",
     "actions": [{"type": "inject", "turns": 1,
                  "text": "（现在是深夜 {{time}}。可以顺口提一句这么晚还没睡，别说教。）"}]},
    {"builtin": "study_reading", "name": "学完来找你（阅读）", "enabled": True, "event": "study.reading_finished",
     "cooldown_minutes": 180,
     "actions": [{"type": "say", "directive": "对方刚做完一篇阅读《{{event.title}}》，答对 {{event.correct}}/{{event.total}}。"
                                              "按你的性格说两句。"}]},
    {"builtin": "study_listening", "name": "学完来找你（听力）", "enabled": True,
     "event": "study.listening_finished", "cooldown_minutes": 180,
     "actions": [{"type": "say", "directive": "对方刚做完一组听力，答对 {{event.correct}}/{{event.total}}。"
                                              "按你的性格说两句。"}]},
    {"builtin": "vocab_review", "name": "生词回炉", "enabled": True, "event": "chat.user_message",
     "conditions": [{"field": "vocab_due", "op": ">=", "value": 1}], "cooldown_turns": 8,
     "actions": [{"type": "inject", "turns": 1,
                  "text": "对方该复习这个词了：{{due_vocab::1}}。这一轮的话题用得上，就自然地用一次；"
                          "用不上就完全不用。不要为了用它改变你想说的话，不要解释，不要点名。"}]},
    {"builtin": "lesson_done", "name": "下课了", "enabled": False, "event": "study.lesson_finished",
     "actions": [{"type": "say", "directive": "对方刚上完一节口语课。按你的性格问问上得怎么样，别像老师那样讲评。"}]},
    {"builtin": "unit_done", "name": "单元达标", "enabled": True, "event": "course.unit_completed",
     "actions": [
         {"type": "remember", "category": "event", "content": "{{date}} 对方在课程里学完了「{{event.title}}」这一单元"},
         {"type": "say", "directive": "对方刚在课程里学完「{{event.title}}」这个单元。按你的性格夸一句或聊两句，别像老师讲评。"}]},
]
