"""Strict validation of the LLM output before it ever touches the DB."""
from typing import List

from pydantic import BaseModel, Field, field_validator


class QuizItem(BaseModel):
    prompt: str = Field(min_length=1)
    choices: List[str] = Field(min_length=2, max_length=6)
    correct_index: int = Field(ge=0)
    explanation: str = ""
    topic: str = "General"

    @field_validator("choices")
    @classmethod
    def _strip_choices(cls, v):
        cleaned = [c.strip() for c in v if c and c.strip()]
        if len(cleaned) < 2:
            raise ValueError("A quiz item needs at least two non-empty choices.")
        return cleaned

    def model_post_init(self, __context):
        if self.correct_index >= len(self.choices):
            raise ValueError("correct_index is out of range for the given choices.")


class WordItem(BaseModel):
    word: str = Field(min_length=2, max_length=12)
    clue: str = Field(min_length=1)

    @field_validator("word")
    @classmethod
    def _az_only(cls, v):
        cleaned = "".join(ch for ch in v.upper() if ch.isalpha())
        if not (2 <= len(cleaned) <= 12):
            raise ValueError("Word must be 2-12 A-Z letters (hangman-style).")
        return cleaned


class Section(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    example: str = ""
    quiz: List[QuizItem] = Field(default_factory=list)


class GenerationResult(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    sections: List[Section] = Field(min_length=1)
    word_game: List[WordItem] = Field(default_factory=list)
