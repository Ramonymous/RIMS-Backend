from pydantic import BaseModel

class RefreshRequest(BaseModel):
	refresh_token: str

class RefreshTokenResponse(BaseModel):
	access_token: str
	refresh_token: str
