"""The names arq jobs are enqueued and registered under.

The API enqueues by name and the worker registers by name, and the two processes share nothing
else, so a name that drifted between them would enqueue a job no worker runs. Both sides read the
name from here rather than importing each other.
"""

RESET_EMAIL_JOB_NAME = "send_password_reset_email"
