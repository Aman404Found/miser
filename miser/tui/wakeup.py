"""Compatibility for hosts that prohibit asyncio's local wakeup socket writes.

No listener or remote connection is opened. Normal hosts keep native wakeups.
On a restricted host a public loop timer bounds selector sleep, including during
executor shutdown after Textual's widget timers have stopped.
"""
import errno
import socket


def ensure_wakeup_poll(loop):
    marker = "_miser_textual_wakeup_poll"
    if getattr(loop, marker, None) is not None:
        return True
    try:
        left, right = socket.socketpair()
        try:
            left.send(b"\0")
        finally:
            left.close()
            right.close()
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES}:
            return False
    else:
        return False

    def poll():
        if not loop.is_closed():
            setattr(loop, marker, loop.call_later(.05, poll))

    # This handle deliberately lasts until loop.close(), rather than being a
    # Textual timer: asyncio joins its parser executor after App shutdown.
    setattr(loop, marker, loop.call_later(.05, poll))
    return True
