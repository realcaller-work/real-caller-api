from pydantic import BaseModel


class LoginRequest(BaseModel):
    idToken: str
    deviceId: str


class TokenPair(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "bearer"
    accessTokenExpiresIn: int  # seconds


class LoginResponse(TokenPair):
    needsProfileUpdate: bool


class RefreshRequest(BaseModel):
    refreshToken: str


class RefreshResponse(TokenPair):
    pass


class LogoutRequest(BaseModel):
    refreshToken: str


class LogoutResponse(BaseModel):
    success: bool
