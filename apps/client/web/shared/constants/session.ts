/**
 * The session cookie's name, shared by the Nitro gate and anything else that must agree with it.
 *
 * It matches `SESSION_COOKIE_NAME` in `apps/server/app/constants/session.py`, which is what the
 * backend actually sets. Two spellings of one name is a bug nobody sees until a gate silently
 * stops gating, so the value is written once on this side of the wire.
 */
export const SESSION_COOKIE_NAME = 'sid';
