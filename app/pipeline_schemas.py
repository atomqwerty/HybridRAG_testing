from pydantic import BaseModel, Field
from typing import List, Optional

class TechSpecs(BaseModel):
    engine: Optional[str] = Field(None, description="Engine type or motor configuration")
    horsepower: Optional[str] = Field(None, description="Power output in HP or kW")
    range_km: Optional[int] = Field(None, description="Electric range in km")
    battery_capacity: Optional[str] = Field(None, description="Battery capacity in kWh")
    price: Optional[str] = Field(None, description="Price of the vehicle")

class CarModel(BaseModel):
    brand: str = Field(..., description="Car brand (e.g. Tesla, BYD)")
    model: str = Field(..., description="Model name (e.g. Model 3, Seal)")
    year: Optional[int] = Field(None, description="Model year")
    specs: TechSpecs = Field(default_factory=TechSpecs)
    source_url: str = Field(..., description="URL where this data was found")
    description: Optional[str] = Field(None, description="Brief description or summary")
