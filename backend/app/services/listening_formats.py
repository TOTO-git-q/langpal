"""Listening practice profiles and the shared content boundary."""
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .languages import LanguageTag as Language


@dataclass(frozen=True)
class Format:
    language: Language
    label: str
    description: str
    speakers: int
    questions: int
    choices: int = 4
    spoken_choices: bool = False
    preview: bool = False


FORMATS = {
    "en_response": Format("en", "即时回应", "Listen and Choose a Response. 一句自然的校园场景话语，选最得体的回应。", 1, 1),
    "en_conversation": Format("en", "校园对话", "Listen to a Conversation. 两人围绕校园问题交谈，考意图、细节或推断。", 2, 2),
    "en_announcement": Format("en", "校园公告", "Listen to an Announcement. 有具体变更或行动要求，考目的与下一步。", 1, 2),
    "en_talk": Format("en", "学术讲解", "Listen to an Academic Talk. 短讲包含观点、例证和关系，考组织与推断。", 1, 3),
    "ja_task": Format("ja", "課題理解", "先明确要解决的问题。两人的对话应有顺序或限制，问听者接下来怎么做。", 2, 1, preview=True),
    "ja_points": Format("ja", "ポイント理解", "先给出关注点。两人的对话应包含几项相近的信息，问特定条件下的正确细节。", 2, 1, preview=True),
    "ja_gist": Format("ja", "概要理解", "先听一段完整独白，选最能概括发言者意图或观点的选项。", 1, 1, spoken_choices=True),
    "ja_response": Format("ja", "即時応答", "一条短口语话语，三种简短回应。考语境中的礼貌、关系与意图。", 1, 1, 3, spoken_choices=True),
    "ja_integrated": Format("ja", "統合理解", "两名说话者给出分散但互补的信息和条件。结合不同人的信息，作出选择。", 2, 2),
}


def profiles_for(language: Language) -> dict[str, Format]:
    native = {key: profile for key, profile in FORMATS.items() if profile.language == language}
    if native:
        return native
    return {
        "conversation": Format(language, "生活对话", "两人自然交谈，考说话意图和一项具体约束。", 2, 2),
        "brief-talk": Format(language, "短讲", "围绕一个主题展开短讲，考主旨和一个支持细节。", 1, 2),
    }

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=500)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=800)]


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    speaker: Literal["A", "B"]
    text: ShortText


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: ShortText
    choices: list[ShortText] = Field(min_length=3, max_length=4)
    answer: int = Field(ge=0, le=3)
    evidence: list[Annotated[int, Field(ge=1, le=18)]] = Field(min_length=1, max_length=4)
    explanation: Reason
    # Question type for diagnosis (docs/LEARNING.md 4.3): gist / detail / function / organization /
    # inference. Optional so saved practice from before stays readable; unknown values are dropped.
    skill: Annotated[str, StringConstraints(max_length=40)] | None = None


class Exercise(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: Annotated[ShortText, Field(max_length=100)]
    script: list[Line] = Field(min_length=1, max_length=18)
    questions: list[Question] = Field(min_length=1, max_length=3)


def validate_exercise(exercise: Exercise, profile: Format) -> None:
    script = exercise.script
    prompts = [question.prompt.casefold() for question in exercise.questions]
    if (script[0].speaker != "A" or len({line.speaker for line in script}) != profile.speakers
            or len(exercise.questions) != profile.questions or len(set(prompts)) != len(prompts)):
        raise ValueError("Unexpected speaker or question structure")
    if profile.label in {"即时回应", "即時応答"} and len(script) != 1:
        raise ValueError("A quick-response stimulus must be one utterance")
    if profile.speakers == 2 and len(script) < 3:
        raise ValueError("A dialogue needs at least three turns")
    parts = [line.text for line in script]
    for question in exercise.questions:
        if (len(question.choices) != profile.choices or question.answer >= profile.choices
                or len({choice.casefold() for choice in question.choices}) != profile.choices
                or len(set(question.evidence)) != len(question.evidence)
                or any(index > len(script) for index in question.evidence)):
            raise ValueError("Invalid answer or evidence references")
        parts.extend([question.prompt, *question.choices])
    text = " ".join(parts)
    if sum(len(line.text) for line in script) > 2600:
        raise ValueError("Script too long")
    if profile.language == "ja" and not re.search(r"[ぁ-んァ-ン]", text):
        raise ValueError("Expected Japanese script and questions")
    if profile.language == "en" and re.search(r"[ぁ-んァ-ン一-龯]", text):
        raise ValueError("Expected English script and questions")


def audio_lines(exercise: Exercise, profile: Format) -> list[Line]:
    lines = exercise.script.copy()
    if profile.spoken_choices:
        question, = exercise.questions
        # Narration uses a consistent A voice. Choices stay outside the evidence span.
        if profile.label != "即時応答":
            lines.append(Line(speaker="A", text=question.prompt))
        for index, choice in enumerate(question.choices):
            lines.append(Line(speaker="A", text=f"{('一', '二', '三', '四')[index]}番。{choice}"))
    return lines
