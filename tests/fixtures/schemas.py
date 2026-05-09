"""Pydantic schemas used by fixture pipelines."""
from pydantic import BaseModel


class Greeting(BaseModel):
    message: str
    language: str
