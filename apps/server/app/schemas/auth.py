"""Request and response models for the auth routes.

The response never carries a password hash, which is why `AuthenticatedUserData` names its three
fields rather than serializing whatever row the repository returned: a model that spread a row
would leak the hash the first time someone added a column.

Email validation is a constrained pattern rather than Pydantic's `EmailStr`, because `EmailStr`
pulls in `email-validator` and R-331 asks what an existing module cannot do. The pattern rejects
what B-38 needs rejected, an address with no `@` or no domain, and the authoritative check on an
address is delivery rather than syntax anyway.
"""

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic.types import UUID4

from app.constants.user_roles import UserRole

# Deliberately permissive about the local part and strict about the overall shape: one `@`, a
# domain with a dot, and no whitespace anywhere.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$"
MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 8
# The pinned bcrypt refuses a secret past this many bytes rather than truncating it, so one it
# cannot take has to be refused here, as a validation error naming its field, or it reaches
# `hashpw` and raises where nothing catches it and the client gets a 500.
MAX_PASSWORD_BYTES = 72
# The same ceiling in characters, which every string longer than it exceeds in bytes as well. It
# is kept so the OpenAPI document states a bound, and it is not the check: a character encodes to
# one to four bytes, so the byte ceiling is what decides for anything outside ASCII.
MAX_PASSWORD_LENGTH = MAX_PASSWORD_BYTES
MAX_RESET_TOKEN_LENGTH = 256
BCRYPT_BYTE_LIMIT_MESSAGE = f"Password must be at most {MAX_PASSWORD_BYTES} bytes when encoded"


def refuse_secret_bcrypt_cannot_take(candidate: str) -> str:
    """Return the submitted secret, or refuse the ones bcrypt raises on rather than truncates."""
    if len(candidate.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError(BCRYPT_BYTE_LIMIT_MESSAGE)
    return candidate


# Annotated onto every password field the application accepts, so no route reaches bcrypt with a
# value bcrypt refuses. A field carrying this answers 400 naming itself rather than raising.
BcryptSafeSecret = Annotated[str, AfterValidator(refuse_secret_bcrypt_cannot_take)]


class AuthRequestModel(BaseModel):
    """Shared configuration: unknown fields are refused and surrounding space is stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(AuthRequestModel):
    """The body of a registration."""

    email: str = Field(max_length=MAX_EMAIL_LENGTH, pattern=EMAIL_PATTERN)
    password: Annotated[
        BcryptSafeSecret, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    ]


class LoginRequest(AuthRequestModel):
    """The body of a sign-in.

    The email carries no pattern. A malformed address is a failed sign-in rather than a malformed
    request, and answering 400 here would tell a caller that an address is not even registrable,
    which is one more bit than a sign-in should reveal.
    """

    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: Annotated[BcryptSafeSecret, Field(max_length=MAX_PASSWORD_LENGTH)]


class ChangePasswordRequest(AuthRequestModel):
    """The body of a password change, which proves the caller knows the current password."""

    current_password: Annotated[BcryptSafeSecret, Field(max_length=MAX_PASSWORD_LENGTH)]
    new_password: Annotated[
        BcryptSafeSecret, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    ]


class ForgotPasswordRequest(AuthRequestModel):
    """The body of a reset request.

    The email carries no pattern, for the reason `LoginRequest` gives: the answer is the same 200
    for every address, and a 400 for one that is not even registrable would be the one response
    that differed.
    """

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)


class ResetPasswordRequest(AuthRequestModel):
    """The body of a reset: the token from the email's link and the new password.

    The password takes registration's constraints, since it becomes the account's password on
    exactly the same terms. The token's ceiling is generous against the 43 characters a real one
    has, and exists so an oversized value is refused before it is hashed.
    """

    token: str = Field(min_length=1, max_length=MAX_RESET_TOKEN_LENGTH)
    password: Annotated[
        BcryptSafeSecret, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    ]


class ForgotPasswordData(BaseModel):
    """The confirmation a reset request answers with, identical for every address."""

    message: str


class ForgotPasswordResponse(BaseModel):
    """The `{ data }` envelope of a reset request."""

    data: ForgotPasswordData


class AuthenticatedUserData(BaseModel):
    """The signed-in user, carrying only what a client may see: the id, address, and role."""

    id: UUID4
    email: str
    role: UserRole


class AuthenticatedUserResponse(BaseModel):
    """The `{ data }` envelope every successful auth route answers with."""

    data: AuthenticatedUserData
