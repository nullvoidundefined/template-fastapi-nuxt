"""The cookie a signed-in browser carries and how long a session lives.

Both values are shared rather than repeated: the cookie name is written by the auth routes and
read by the session dependency, and the lifetime is written into the cookie's `max-age` and into
the `expires_at` column, which must agree or a browser keeps a cookie the database has retired.
"""

from datetime import timedelta

SESSION_COOKIE_NAME = "sid"
SESSION_TTL = timedelta(days=7)
