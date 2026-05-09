"""Pydantic schemas used by fixture pipelines."""
from pydantic import BaseModel

from pyconveyor.vocab import VocabField, Vocabulary


class Greeting(BaseModel):
    message: str
    language: str


_PlasticVocab = Vocabulary(known={"PET", "PE", "PLA"}, label="plastic_type")


class PlasticRecord(BaseModel):
    plastic: str = VocabField(vocab=_PlasticVocab)
    quantity: int
