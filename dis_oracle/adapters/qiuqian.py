"""Author-defined 1..100 numeric set and explicit confirmation commands.

This is NOT the historical procedure of Kwan Im Thong Hood Cho Temple.
Manual observations are retained; no automatic redraw follows a refusal.
"""

import secrets

from ..contracts import ContractError, now_iso
from .mechanics_store import SessionStore, integer, make_card, mode_check

SELECTED_TEMPLE = "Kwan Im Thong Hood Cho Temple, Singapore"
SET_ID = "author-numeric-100-v1"
MODEL = "Two independent equiprobable sides: 0=convex, 1=flat; not measured temple probabilities."
MAX_ATTEMPTS = 1000  # Technical resource bound, not a traditional rule.
RESULTS = ("sheng_bei", "yin_bei", "xiao_bei")


def confirmation_from_sides(first, second):
    integer(first, "first side", 0, 1); integer(second, "second side", 0, 1)
    return "sheng_bei" if first != second else "yin_bei" if first == 0 else "xiao_bei"


def check_confirmation(value):
    if not isinstance(value, str) or value not in RESULTS:
        raise ContractError("confirmation_result must be sheng_bei, yin_bei or xiao_bei")


class QiuqianSessions(SessionStore):
    core_id = "qiuqian"

    def start(self, session_id, event_id, *, mode, max_attempts=3,
              stick_number=None, confirmation_result=None):
        mode_check(mode, f"confirmation/repeat rules for {SELECTED_TEMPLE} are unverified")
        integer(max_attempts, "max_attempts", 0, MAX_ATTEMPTS)
        if mode == "digital":
            if stick_number is not None or confirmation_result is not None:
                raise ContractError("digital mode conflicts with supplied manual stick/confirmation")
        else:
            integer(stick_number, "stick_number", 1, 100)
            if confirmation_result is not None:
                check_confirmation(confirmation_result)
        if max_attempts == 0 and confirmation_result is not None:
            raise ContractError("max_attempts=0 conflicts with a supplied confirmation; no observations may be discarded")
        request = {"operation": "start", "mode": mode, "max_attempts": max_attempts,
                   "stick_number": stick_number, "confirmation_result": confirmation_result}

        def build(latest):
            if latest:
                raise ContractError("session already exists")
            stick = secrets.SystemRandom().randint(1, 100) if mode == "digital" else stick_number
            integer(stick, "selected stick", 1, 100)
            inputs = {"event_id": event_id, "session_id": session_id, "mode": mode,
                      "max_attempts": max_attempts, "set_id": SET_ID, "temple": None,
                      "research_target_temple": SELECTED_TEMPLE, "deity_context": "Guanyin",
                      "protocol_scope": "AUTHOR_ADAPTATION_NOT_HISTORICAL",
                      "requests": [{"request_id": "start", **request}]}
            raw = {"generated_at": now_iso(), "method": "digital-csprng-adaptation" if mode == "digital" else "reported-observations",
                   "stick_number": stick, "set_id": SET_ID, "total_sticks": 100,
                   "temple_protocol_status": "BLOCKED_SOURCE", "confirmation": None,
                   "attempts": [], "final_state": "pending", "completion_reason": None,
                   "simulation_assumption": MODEL if mode == "digital" else None}
            if confirmation_result is not None:
                self._record_attempt(raw, confirmation_result, None, "start", max_attempts)
            elif max_attempts == 0:
                raw.update(final_state="no_confirmation", completion_reason="attempt_limit_reached")
            return make_card(self.core_id, inputs, raw)

        return self._execute(session_id, event_id, "start", request, build)

    @staticmethod
    def _record_attempt(raw, result, sides, request_id, limit):
        raw["attempts"].append({"attempt": len(raw["attempts"]) + 1,
                                "stick_number": raw["stick_number"], "confirmation": result,
                                "sides": sides, "request_id": request_id, "recorded_at": now_iso()})
        raw["confirmation"] = result
        if result == "sheng_bei":
            raw.update(final_state="confirmed", completion_reason="confirmation_received")
        elif len(raw["attempts"]) == limit:
            raw.update(final_state="no_confirmation", completion_reason="attempt_limit_reached")

    def _continue(self, session_id, event_id, request_id, operation, result=None):
        self._continuation_id(request_id)
        if operation == "confirm":
            check_confirmation(result)
        request = {"operation": operation, "confirmation_result": result}

        def build(latest):
            if latest is None:
                raise ContractError("start the session before submitting observations")
            inputs, raw = latest["inputs"], latest["raw_result"]
            if raw["final_state"] != "pending":
                raise ContractError("session is completed; no new draws/observations allowed")
            if operation == "confirm" and inputs["mode"] != "manual":
                raise ContractError("manual confirmation conflicts with digital mode")
            if operation == "advance" and inputs["mode"] != "digital":
                raise ContractError("digital advance conflicts with manual mode")
            inputs["requests"].append({"request_id": request_id, **request})
            if operation == "finish":
                raw.update(final_state="no_confirmation", completion_reason="explicit_finish")
            else:
                if len(raw["attempts"]) >= inputs["max_attempts"]:
                    raise ContractError("total attempt limit reached")
                if operation == "advance":
                    rng = secrets.SystemRandom()
                    sides = [rng.choice((0, 1)), rng.choice((0, 1))]
                    confirmation = confirmation_from_sides(*sides)
                else:
                    sides, confirmation = None, result
                self._record_attempt(raw, confirmation, sides, request_id, inputs["max_attempts"])
            raw["generated_at"] = now_iso()
            return make_card(self.core_id, inputs, raw)

        return self._execute(session_id, event_id, request_id, request, build)

    def confirm(self, session_id, event_id, request_id, confirmation_result):
        return self._continue(session_id, event_id, request_id, "confirm", confirmation_result)

    def advance(self, session_id, event_id, request_id):
        return self._continue(session_id, event_id, request_id, "advance")

    def finish(self, session_id, event_id, request_id):
        return self._continue(session_id, event_id, request_id, "finish")
