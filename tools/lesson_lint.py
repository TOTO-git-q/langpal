"""Checks lesson files against docs/LESSON-AUTHORING.md. A lesson is not finished until this passes.

usage:  python tools/lesson_lint.py <lesson id> [...]        (course toefl-2026 unless --course is given)
        python tools/lesson_lint.py --course toefl-2026 --all-new
Exit code 1 when any lesson has an error. Warnings do not fail the run but must be read.
"""
import argparse
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.services.course import lessons  # noqa: E402
from app.services.course.lint import check  # noqa: E402


def lint(course_id, name):
    path = next((base / course_id / (name + ".json") for base in (lessons.DIRECTORY, lessons.CUSTOM) if (base / course_id / (name + ".json")).is_file()), None)
    if path is None:
        return [f"no file for {name}"], []
    try:
        raw = json.loads(path.read_text("utf-8"))
        lessons.Lesson.model_validate(raw)
    except Exception as error:  # noqa: BLE001
        return ["does not load: " + " ".join(str(error).split())[:400]], []
    course = json.loads((path.parent / "course.json").read_text("utf-8"))
    return check(raw, course, name, course_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*")
    parser.add_argument("--course", default="toefl-2026")
    parser.add_argument("--all-new", action="store_true", help="every lesson of the course that has `mastery: once`")
    args = parser.parse_args()
    names = list(args.names)
    if args.all_new:
        home = lessons.DIRECTORY / args.course
        names += sorted(p.stem for p in home.glob("*.json") if p.stem not in ("course", "kinds") and json.loads(p.read_text("utf-8")).get("mastery") == "once")
    failed = 0
    for name in names:
        errors, warnings = lint(args.course, name)
        print(("FAIL " if errors else "ok   ") + name)
        for line in errors:
            print("   error: " + line)
        for line in warnings:
            print("   warning: " + line)
        failed += bool(errors)
    print(f"{len(names) - failed} of {len(names)} pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
