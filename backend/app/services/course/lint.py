"""The checks of docs/LESSON-AUTHORING.md on one lesson, shared by tools/lesson_lint.py and the course builder."""
import json
import re
from collections import Counter

TITLE = re.compile(r"^(概述|题型|规则|解题步骤|要点|结构|常用表达|词汇表|辨析|例题|干扰项|常见错误|说明|小测|练习[一二三四])([：　 ].{1,16})?$")
BANNED = ["你", "咱", "吧", "呢", "哦", "啦", "嘛", "！", "!", "其实", "别怕", "记住", "小技巧", "秘诀", "干货", "搞定", "轻松", "一眼", "划掉", "小词",
          "那一堆", "帮不了", "眼熟", "长什么样", "怎么挑", "怎么选", "带着做", "下面我们", "接下来", "综上", "总之", "坑", "陷阱", "套路", "稳了", "拿下"]
ZH = re.compile(r"[的是为说对应依据所以因此这那个们吗呢还没从让被把给]")   # characters a Chinese explanation can hardly do without, and Japanese kana text never uses in simplified form
HEDGE = re.compile(r"不等于|不能据此|不表示|并非|不必然|不能一律|不代表|不能仅|不能只凭|不能单凭|不意味|不能推定|不能认定|不构成|不能直接")
QUESTION_TITLE = re.compile(r"怎么|什么|哪|吗|？|\?")
LETTER_REF = re.compile(r"(?<![A-Za-z])(?<![A-Za-z] )(?<![A-Za-z]　)[ABCD](?![A-Za-z])(?=\s*[^\sA-Za-z])")   # "Hall A" names a thing, "选 A" refers to an option
CJK = re.compile(r"[㐀-鿿]")


def texts(value, path=""):
    """Every Chinese-bearing string the learner reads, with where it is."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for n, item in enumerate(value):
            yield from texts(item, f"{path}[{n}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("id", "type", "src", "url", "point", "points", "tags", "look", "answer", "fill", "options", "stem", "text", "lines", "audio", "accept", "chunks", "extra"):
                continue
            yield from texts(item, f"{path}.{key}" if path else key)


def gaps(fill):
    return re.findall(r"([A-Za-z]*)\{([a-z]+)\}", fill)


def groups_of(card):
    return card.get("groups", []) + [g for s in card.get("sets", []) for g in s["groups"]]


def check(raw, course, name, course_id, choices=(4,)):
    """Errors and warnings of one lesson that already loads (`lessons.Lesson`), given its course.json.
    `choices`: how many options a single question may have (a built course may follow an exam with three)."""
    errors, warnings = [], []
    if name not in [i for s in course["sections"] for i in s["lessons"]]:
        errors.append("not listed in course.json")
    if course.get("titles", {}).get(name) and course["titles"][name] != raw["title"]:
        errors.append(f"title differs from the syllabus: {course['titles'][name]!r}")
    if raw.get("mastery") != "once":
        errors.append('missing "mastery": "once"')
    if not 2 <= len(raw["points"]) <= 3:
        errors.append(f"{len(raw['points'])} points (2-3)")
    if QUESTION_TITLE.search(raw["title"]):
        errors.append("lesson title is a question or uses 怎么/什么")
    cards = raw["cards"]
    if not (5 <= len(cards) <= 11 or (len(cards) in (2, 4) and name.endswith(("-mock", "-overview")))):
        warnings.append(f"{len(cards)} cards (7-10 expected; overview 4-5, mock test 2)")
    final = cards[-1]
    if final["type"] != "quiz" or final["id"] != "timed" or final["title"] != "小测":
        errors.append("the last card must be the quiz: id timed, title 小测")
    elif len(final["sets"]) != 1 or final["sets"][0]["id"] != "set-a" or "more" in final:
        errors.append("the quiz has exactly one set (set-a) and no `more`")
    for card in cards:
        where = card["id"]
        title = card["title"]
        if card.get("note") and "不是官方规定" in card["note"] and card["type"] in ("check", "quiz", "facts"):
            errors.append(f"{where}: the note that something is the course's own advice belongs only under a card that gives such advice (steps, timing), not here")
        if card.get("note") and "不是官方规定" in card["note"] and card["type"] in ("check", "quiz", "facts"):
            errors.append(f"{where}: the note that something is the course's own advice belongs only under a card that gives such advice (steps, timing), not here")
        if card["type"] in ("check", "quiz") and card.get("intro"):
            errors.append(f"{where}: practice and quiz cards carry no `intro` (the page shows the amount and the time itself): {card['intro'][:30]}")
        if card["type"] == "check" and not re.match(r"^练习[一二三四]([：　 ].{1,16})?$", title):
            errors.append(f"{where}: a practice card is titled 练习一 … 练习四 (plus an optional name): {title!r}")
        elif card["type"] in ("facts", "steps") and not TITLE.match(title):
            errors.append(f"{where}: card title {title!r} is not from the list in section 3")
        elif not TITLE.match(title) and (len(title) > 14 or QUESTION_TITLE.search(title) or any(word in title for word in BANNED) or "的那" in title):
            errors.append(f"{where}: card title {title!r} must be a fixed word from section 3 or a short noun phrase naming the topic")
        for key, text in texts({k: v for k, v in card.items() if k != "title"}):
            if not CJK.search(text):
                continue
            hits = [word for word in BANNED if word in text]
            if hits:
                errors.append(f"{where}.{key}: banned wording {hits}: {text[:50]}")
        for row in card.get("rows", []) if card["type"] == "table" else []:
            for cell in row:
                if "{" in cell:
                    errors.append(f"{where}: table cells show whole words, no braces: {cell[:40]}")
        if card["type"] == "table" and any(QUESTION_TITLE.search(col) for col in card["cols"]):
            errors.append(f"{where}: table headers are nouns, not questions: {card['cols']}")
        for group in groups_of(card):
            if "fill" in group:
                found = gaps(group["fill"])
                for head, tail in found:
                    if len(head) != (len(head) + len(tail)) // 2:
                        errors.append(f"{where}: gap {head}{{{tail}}} does not keep the first half of the word")
                if card["type"] == "check" and len(group.get("notes") or []) != len(found):
                    errors.append(f"{where}: a practice paragraph needs one note per gap")
            shared = [item["options"] for item in group.get("items") or [] if "options" in item]
            bank = len(shared) >= 2 and 5 <= len(shared[0]) <= 15 and all(options == shared[0] for options in shared)   # matching: one option list for the group
            for item in group.get("items") or []:
                if "accept" in item and all(len(re.sub(r"^(paragraph|section|part)\s+", "", answer.strip().strip("[]()").lower())) == 1 for answer in item["accept"]):
                    errors.append(f"{where}: nobody types a letter or a number: matching items share one option list (section 5): {item['stem'][:40]}")
                if "options" in item:
                    if len(set(item["options"])) != len(item["options"]) or (len(item["options"]) not in choices and not bank):
                        errors.append(f"{where}: four distinct options (or one shared list of 5-15 for every item of the group): {item['stem'][:40]}")
                    lengths = [len(o.split()) for o in item["options"]]
                    if max(lengths) > 3 * max(1, min(lengths)) and max(lengths) > 8:
                        warnings.append(f"{where}: options differ a lot in length: {item['stem'][:40]}")
                if "chunks" in item:
                    if len(item.get("extra") or []) != 1:
                        errors.append(f"{where}: a sentence item has exactly one extra chunk: {item['stem'][:40]}")
                    if len(set(item["chunks"] + (item.get("extra") or []))) != len(item["chunks"]) + len(item.get("extra") or []):
                        errors.append(f"{where}: two chunks are the same: {item['stem'][:40]}")
                    if not 4 <= len(item["chunks"]) <= 7:
                        errors.append(f"{where}: 4-7 chunks: {item['stem'][:40]}")
                if course_id == "n1" and item.get("why") and not ZH.search(item["why"]):
                    errors.append(f"{where}: `why` is not written in Chinese (it reads as Japanese): {item['why'][:40]}")
                if not item.get("why") or not CJK.search(item["why"]):
                    errors.append(f"{where}: `why` in Chinese is missing: {item['stem'][:40]}")
                elif LETTER_REF.search(item["why"]):
                    errors.append(f"{where}: `why` refers to options by letter: {item['why'][:50]}")
    if final["type"] == "quiz" and final.get("sets"):
        items = [item for group in final["sets"][0]["groups"] for item in group.get("items") or []]
        tagged = Counter(item["point"] for item in items)
        for group in final["sets"][0]["groups"]:
            tagged.update(group.get("tags") or [])
            if group.get("notes"):
                errors.append("timed: the quiz gives no notes")
        for point in raw["points"]:
            if tagged[point["id"]] < 2:
                errors.append(f"timed: point {point['id']} is tested by {tagged[point['id']]} item(s) (at least 2)")
        answers = [item["answer"] for item in items if "options" in item]
        if len(answers) >= 6:
            spread = Counter(answers)
            places = min(4, min(len(item["options"]) for item in items if "options" in item))
            if len(spread) < places or max(spread.values()) > (0.4 if places >= 4 else 0.5) * len(answers) + 0.5:
                errors.append(f"timed: answer positions are not spread: {dict(sorted(spread.items()))}")
        if not items and not any("fill" in g for g in final["sets"][0]["groups"]):
            errors.append("timed: the quiz is empty")
    four = [item for card in cards for group in groups_of(card) for item in group.get("items") or [] if len(item.get("options") or []) == 4]
    if len(four) >= 6:
        others = lambda item: [len(option) for n, option in enumerate(item["options"]) if n != item["answer"]]
        longest = sum(len(item["options"][item["answer"]]) > max(others(item)) for item in four)
        shortest = sum(len(item["options"][item["answer"]]) < min(others(item)) for item in four)
        if max(longest, shortest) > 0.4 * len(four) + 1e-9:
            errors.append(f"the correct option can be told by its length: it is the longest in {longest} and the shortest in {shortest} of {len(four)} items (at most four in ten each)")
    said = [text for _, text in texts(raw["cards"]) if CJK.search(text)]
    hedges = sum(len(HEDGE.findall(text)) for text in said)
    if hedges > 4:
        errors.append(f"{hedges} disclaimers (不等于 / 不表示 / 不能据此… ): at most four in a lesson, one in a card (section 4, 句子要好读)")
    if any("\\n" in text for _, text in texts(raw["cards"])) or any("\\n" in group.get(key) for card in cards for group in groups_of(card) for key in ("text", "fill") if isinstance(group.get(key), str)):
        errors.append("a line break is written as the two characters backslash and n: write a real line break")
    broken = re.findall(r".{0,12}(?:[0-9A-Za-z]\?[0-9A-Za-z]|\?{3,}|�).{0,12}", re.sub(r"https?://[^\s\"]+", "", json.dumps(raw, ensure_ascii=False)))
    if broken:
        errors.append(f"a character was lost when the file was written (a dash or an apostrophe became ?): {broken[:3]}")
    stems = [item["stem"] for card in cards for group in groups_of(card) for item in group.get("items") or []]
    passages = [group["text"][:60] for card in cards for group in groups_of(card) if group.get("text")]
    passages += [group["audio"]["lines"][0]["text"][:60] for card in cards for group in groups_of(card) if group.get("audio")]
    if len(passages) != len(set(passages)):
        errors.append("the same passage or recording is used twice in this lesson")
    for card in cards:
        for group in groups_of(card):
            for line in (group.get("audio") or {}).get("lines") or []:
                if re.match(r"^\s*(?:[A-Z][A-Za-z.'-]*(?: [A-Z][A-Za-z.'-]*){0,2}|[぀-ヿ一-鿿]{1,8})\s*[:：]\s", line["text"]):
                    errors.append(f"{card['id']}: a spoken line starts with a speaker label, which the voice would read aloud: {line['text'][:40]}")
                    break
    if name.startswith("listening-") and not name.endswith("-overview") and final["type"] == "quiz" and final.get("sets"):
        if not any(group.get("audio") for group in final["sets"][0]["groups"]):
            errors.append("timed: the quiz of a listening lesson has recordings")
    if name.startswith("writing-") and any(card["type"] in ("write", "drill", "model", "marking", "rubric", "skeleton") for card in cards):
        errors.append("a writing lesson uses facts, text, steps, table, check and quiz cards only (free writing is done in the practice)")
    if len(stems) > 4 and max(Counter(stems).values()) > max(4, len(stems) // 2):
        warnings.append("many identical stems")
    return errors, warnings
