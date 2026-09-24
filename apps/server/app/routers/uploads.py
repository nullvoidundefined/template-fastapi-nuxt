"""`POST /v1/uploads`: presign a direct-to-R2 PUT for the signed-in user (B-29).

The route validates the purpose and extension, hands both to the service with the user's ID, and
answers the signed URL. It never accepts a key: the service generates one under the user's prefix.
"""

from fastapi import APIRouter

from app.dependencies.current_user import CurrentUser
from app.dependencies.integrations import RequestStorage
from app.schemas.uploads import PresignedUploadData, PresignedUploadResponse, PresignUploadRequest
from app.services.uploads.presign_upload import presign_upload

router = APIRouter(prefix="/v1/uploads", tags=["uploads"])


@router.post("", response_model=PresignedUploadResponse)
async def create_presigned_upload(
    body: PresignUploadRequest, current: CurrentUser, storage_client: RequestStorage
) -> PresignedUploadResponse:
    """Answer a URL the browser can PUT the file to within fifteen minutes."""
    presigned = await presign_upload(storage_client, current.user.id, body.purpose, body.extension)
    return PresignedUploadResponse(
        data=PresignedUploadData(
            upload_url=presigned.upload_url,
            key=presigned.key,
            content_type=presigned.content_type,
            expires_in_seconds=presigned.expires_in_seconds,
        )
    )
