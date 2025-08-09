from pydantic import BaseModel

class SeedLot(BaseModel):
    id: str
    user_id: str
    species: str
    genome_json: str
    qty: int
    generation: str

class Plant(BaseModel):
    id: str
    user_id: str
    species: str
    genome_json: str
    age_days: int
    health: float
