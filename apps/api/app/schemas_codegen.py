"""Pydantic schemas for codegen responses (e.g. from LLM or agents)."""

from pydantic import BaseModel, Field, field_validator

MAX_FILES = 30


class GeneratedFile(BaseModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def path_relative_no_escape(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("path must be non-empty")
        if v.startswith("/"):
            raise ValueError("path must be relative: no leading slash")
        if ".." in v:
            raise ValueError("path must be relative: no '..' segments")
        if "\\" in v:
            raise ValueError("path must use forward slashes only (no backslashes)")
        return v

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must be non-empty")
        return v


class CodegenResponse(BaseModel):
    summary: str = Field(..., min_length=1)
    implementation_plan_md: str = Field(..., min_length=1)
    tree_md: str = Field(..., min_length=1)
    files: list[GeneratedFile] = Field(...)

    @field_validator("files")
    @classmethod
    def files_max_count(cls, v: list) -> list:
        if len(v) > MAX_FILES:
            raise ValueError(f"files list must have at most {MAX_FILES} items, got {len(v)}")
        return v
