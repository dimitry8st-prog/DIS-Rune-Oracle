"""Two ordered numeric die throws, with no invented syllables or readings."""

import secrets

from ..contracts import ContractError, now_iso
from .mechanics_store import SessionStore, integer, make_card, mode_check


class MoSessions(SessionStore):
    core_id = "mo"

    def run(self, session_id, event_id, *, mode, first_throw=None, second_throw=None):
        mode_check(mode, "Mo numeric-to-syllable mapping and text corpus are not fixed")
        if mode == "digital":
            if first_throw is not None or second_throw is not None:
                raise ContractError("digital mode conflicts with supplied manual throws")
        else:
            integer(first_throw, "first_throw", 1, 6)
            integer(second_throw, "second_throw", 1, 6)
        request = {"operation": "start", "mode": mode,
                   "first_throw": first_throw, "second_throw": second_throw}

        def build(latest):
            if latest:
                raise ContractError("session already exists")
            if mode == "digital":
                rng = secrets.SystemRandom()
                first, second = rng.randint(1, 6), rng.randint(1, 6)
                integer(first, "generated first_throw", 1, 6)
                integer(second, "generated second_throw", 1, 6)
            else:
                first, second = first_throw, second_throw
            inputs = {"event_id": event_id, "session_id": session_id, **request}
            attempt = {"attempt": 1, "first_throw": first, "second_throw": second}
            raw = {"generated_at": now_iso(), "method": "digital-csprng" if mode == "digital" else "reported-throws",
                   "first_throw": first, "second_throw": second,
                   "combination_id": f"mo-{first}-{second}", "attempts": [attempt],
                   "final_state": "completed", "syllable_mapping": "UNAVAILABLE",
                   "historical_interpretation": "UNAVAILABLE"}
            return make_card(self.core_id, inputs, raw)

        return self._execute(session_id, event_id, "start", request, build)
