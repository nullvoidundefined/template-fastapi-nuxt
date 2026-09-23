"""Request and response models for the auth routes.

The response never carries a password hash, which is why `AuthenticatedUserData` names its two
fields rather than serializing whatever row the repository returned: a model that spread a row
would leak the hash the first time someone added a column.

Email validation is a constrained pattern rather than Pydantic's `EmailStr`, because `EmailStr`
pulls in `email-validator` and R-331 asks what an existing module cannot do. The pattern rejects
what B-38 needs rejected, an address with no `@` or no domain, and the authoritative check on an
address is delivery rather than syntax anyway.
"""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import UUID4

# Deliberately permissive about the local part and strict about the overall shape: one `@`, a
# domain with a dot, and no whitespace anywhere.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$"
MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 8
# bcrypt silently truncates beyond 72 bytes, so a longer password would make two different
# passwords equivalent. Refusing it is the honest answer.
MAX_PASSWORD_LENGTH = 72


class AuthRequestModel(BaseModel):
    """Shared configuration: unknown fields are refused and surrounding space is stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(AuthRequestModel):
    """The body of a registration."""

    email: str = Field(max_length=MAX_EMAIL_LENGTH, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginRequest(AuthRequestModel):
    """The body of a sign-in.

    The email carries no pattern. A malformed address is a failed sign-in rather than a malformed
    request, and answering 400 here would tell a caller that an address is not even registrable,
    which is one more bit than a sign-in should reveal.
    """

    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordRequest(AuthRequestModel):
    """The body of a password change, which proves the caller knows the current password."""

    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class AuthenticatedUserData(BaseModel):
    """The signed-in user, carrying only what a client may see."""

    id: UUID4
    email: str


class AuthenticatedUserResponse(BaseModel):
    """The `{ data }` envelope every successful auth route answers with."""

    data: AuthenticatedUserData
