"""Deterministic input registries and explicit conditional arithmetic models.

No historical corpus in the Qwen package was independently verified. These
cards cannot vote. Model profiles opt in to assumptions; they are not certified
traditional procedures. No code here generates observations or draws lots.
"""
from copy import deepcopy
from datetime import date
from unicodedata import name as unicode_name
from ..contracts import ContractError, digest, now_iso, shape, text, timestamp
from .mechanics_store import integer

SIGNS = ("Imix", "Ik'", "Ak'b'al", "K'an", "Chikchan", "Kimi", "Manik'", "Lamat", "Muluk", "Ok",
         "Chuwen", "Eb'", "B'en", "Ix", "Men", "Kib'", "Kab'an", "Etz'nab'", "Kawak", "Ajaw")
SOURCE_STATUS = "BLOCKED_SOURCE_HTTP_403"
NAME_ARITHMETIC_PROFILE = "author-five-grid-arithmetic-v1"


def gregorian_jdn(year, month, day):
    integer(year, "year", 1, 9999); integer(month, "month", 1, 12); integer(day, "day", 1, 31)
    try:
        date(year, month, day)
    except ValueError as exc:
        raise ContractError("invalid proleptic Gregorian civil date") from exc
    a = (14-month)//12; y = year+4800-a; m = month+12*a-3
    return day+(153*m+2)//5+365*y+y//4-y//100+y//400-32045


def maya_model(year, month, day):
    jdn = gregorian_jdn(year, month, day)
    elapsed = jdn-584283
    number, sign = (elapsed+3)%13+1, (elapsed+19)%20
    return {"jdn": jdn, "jd_at_civil_midnight": jdn-0.5, "long_count_days": elapsed,
            "number": number, "sign_index": sign, "sign_label": SIGNS[sign]}


def name_arithmetic(surname_strokes, given_strokes):
    """Apply the author profile to ordered, user-declared stroke counts."""
    for label, values in (("surname_strokes", surname_strokes), ("given_strokes", given_strokes)):
        if not isinstance(values, list) or not 1 <= len(values) <= 20:
            raise ContractError(f"{label} must contain 1..20 per-character counts")
        for value in values:
            integer(value, label, 1, 64)
    surname_total = sum(surname_strokes)
    given_total = sum(given_strokes)
    tenkaku = surname_total + int(len(surname_strokes) == 1)
    jinkaku = surname_strokes[-1] + given_strokes[0]
    chikaku = given_total + int(len(given_strokes) == 1)
    return {"tenkaku": tenkaku, "jinkaku": jinkaku, "chikaku": chikaku,
            "gaikaku": tenkaku + chikaku - jinkaku, "sokaku": surname_total + given_total}


def _strings(values, name):
    if not isinstance(values, list) or not values:
        raise ContractError(name+" must be a nonempty array")
    for value in values:text(value, name)
    if len(set(values)) != len(values):raise ContractError("duplicate "+name)


def _observation_timestamp(value, field):
    try:
        return timestamp(value)
    except (ContractError, OverflowError) as exc:
        raise ContractError(f"{field} must be a valid timestamp with a timezone") from exc


def validate_config(core, config):
    if core == "maya":
        shape(config, ("mode", "profile", "year", "month", "day", "day_boundary"))
        if config["mode"] != "calendar_model" or config["profile"] != "gmt584283-conditional-v1":
            raise ContractError("Maya supports only the explicit conditional calendar model; pajooneem is unavailable")
        if config["day_boundary"] != "civil_midnight_proleptic_gregorian":
            raise ContractError("choose civil midnight explicitly; historical day boundary is unverified")
        maya_model(config["year"], config["month"], config["day"])
    elif core == "name_grids":
        name_fields = ("mode", "surname", "given_name")
        stroke_fields = ("profile", "surname_strokes", "given_strokes", "stroke_standard", "evidence_ref")
        shape(config, name_fields, stroke_fields)
        for key in ("surname", "given_name"):
            text(config[key], key)
            # Keep the declared spelling, including supplementary and compatibility ideographs.
            if any(not unicode_name(character, "").startswith(("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-"))
                   for character in config[key]):
                raise ContractError(f"{key} must contain only explicit CJK ideographs")
        if config["mode"] == "automatic":
            if set(config) != set(name_fields):
                raise ContractError("automatic lookup conflicts with manual counts/profile")
        elif config["mode"] == "manual_strokes":
            shape(config, name_fields + stroke_fields)
            if config["profile"] != NAME_ARITHMETIC_PROFILE:
                raise ContractError("only the explicit author arithmetic profile is supported; traditional school is unverified")
            text(config["stroke_standard"], "stroke_standard")
            text(config["evidence_ref"], "evidence_ref")
            name_arithmetic(config["surname_strokes"], config["given_strokes"])
            for name_key, stroke_key in (("surname", "surname_strokes"), ("given_name", "given_strokes")):
                if len(config[stroke_key]) != len(config[name_key]):
                    raise ContractError(f"{stroke_key}: one manual count is required for each character of {name_key}")
        else:
            raise ContractError("name mode must be automatic or manual_strokes")
    elif core == "shakuna":
        shape(config, ("mode", "observation"))
        if config["mode"] != "manual_observation":
            raise ContractError("Shakuna observations must be supplied manually; no RNG")
        observation = config["observation"]
        shape(observation, ("object", "action", "direction", "side", "observed_at", "location", "context", "evidence_ref"))
        for field, value in observation.items():
            text(value, f"observation.{field}")
        _observation_timestamp(observation["observed_at"], "observation.observed_at")
    elif core == "slavic":
        shape(config, ("mode", "regional_variant", "protocol_ref", "participants", "items", "song_order", "return_policy", "rounds", "completion"))
        if config["mode"] != "manual_observation":
            raise ContractError("Slavic historical/digital draw is unavailable without a verified regional protocol/corpus")
        text(config["regional_variant"], "regional_variant")
        text(config["protocol_ref"], "protocol_ref")
        _strings(config["participants"], "participants")
        _strings(config["song_order"], "song_order")
        if not isinstance(config["items"], dict) or not config["items"]:
            raise ContractError("item-owner mapping required")
        for item, owner in config["items"].items():
            text(item, "item_id")
            text(owner, "participant_id")
            if owner not in config["participants"]:
                raise ContractError("item has an unregistered owner")
        if len(set(config["items"].values())) != len(config["participants"]) or len(config["items"]) != len(config["participants"]):
            raise ContractError("one distinct item per participant required by this observation schema")
        if config["return_policy"] not in ("with_replacement", "without_replacement"):
            raise ContractError("explicit reported return policy required")
        rounds = config["rounds"]
        if not isinstance(rounds, list) or not rounds or len(rounds) > len(config["song_order"]):
            raise ContractError("one or more ordered observed rounds required")
        drawn = set()
        previous = None
        time_fields = ("song_started_at", "drawn_at", "song_finished_at", "returned_at")
        for index, row in enumerate(rounds):
            fields = ("song_id", "song_source_ref", "item_id", "participant_id")
            shape(row, fields + time_fields, ("evidence_ref",))
            for field in fields:
                text(row[field], f"rounds[{index}].{field}")
            if "evidence_ref" in row:
                text(row["evidence_ref"], f"rounds[{index}].evidence_ref")
            if row["song_id"] != config["song_order"][index]:
                raise ContractError("song/draw order conflicts with registered order")
            if row["item_id"] not in config["items"] or config["items"][row["item_id"]] != row["participant_id"]:
                raise ContractError("item and participant binding mismatch")
            start, draw, end, returned = [
                _observation_timestamp(row[field], f"rounds[{index}].{field}") for field in time_fields
            ]
            if not start <= draw <= end <= returned or (previous is not None and start < previous):
                raise ContractError("inconsistent singing, draw or return chronology")
            previous = returned
            if config["return_policy"] == "without_replacement" and row["item_id"] in drawn:
                raise ContractError("item already removed under without-replacement policy")
            drawn.add(row["item_id"])
        if config["completion"] not in ("ongoing", "songs_finished", "all_participants_received", "stopped"):
            raise ContractError("explicit completion state required")
        if config["completion"] == "songs_finished" and len(rounds) != len(config["song_order"]):raise ContractError("not all registered songs have finished")
        if config["completion"] == "all_participants_received" and len(drawn) != len(config["participants"]):raise ContractError("not all participants have a recorded result")
    else:raise ContractError("unknown audited input core")


def card(core, event_id, config):
    text(event_id, "event_id");validate_config(core, config)
    inputs={"event_id":event_id, **deepcopy(config)}
    status="ABSTAIN"
    raw={"generated_at":now_iso(), "source_verification":SOURCE_STATUS,
         "interpretation_status":"ABSTAIN", "corpus_status":"UNAVAILABLE", "forecast_status":"NOT_ASSIGNED"}
    if core == "maya":
        raw.update(calendar_model=maya_model(config['year'],config['month'],config['day']),
                   assumptions={"correlation_jdn":584283,"long_count_zero":"4 Ajaw (conditional anchor)",
                                "day_boundary":config['day_boundary'],"historical_verification":"UNVERIFIED"},
                   pajooneem_status="UNAVAILABLE",procedure_status="MODEL_CALCULATED")
        reason="CONDITIONAL_CALENDAR_ONLY_SOURCE_AND_PAJOONEEM_UNAVAILABLE"
    elif core == "name_grids":
        if config["mode"] == "automatic":
            status = "UNAVAILABLE"
            reason = "LICENSED_STROKE_DICTIONARY_AND_STANDARD_UNAVAILABLE"
            raw.update(procedure_status="UNAVAILABLE",dictionary_status="UNAVAILABLE",dictionary_license="UNAVAILABLE")
        else:
            raw.update(grids=name_arithmetic(config["surname_strokes"], config["given_strokes"]),
                       stroke_provenance={key: config[key] for key in ("profile", "stroke_standard", "evidence_ref")},
                       stroke_verification="USER_DECLARED_NOT_AUTHENTICATED",
                       procedure_status="AUTHOR_MODEL_CALCULATED",
                       source="research/audit/four_cores/REPORT.md")
            reason = "AUTHOR_ARITHMETIC_ONLY_TRADITIONAL_PROFILE_AND_INTERPRETATION_UNVERIFIED"
    elif core == "shakuna":
        raw.update(observation=deepcopy(config['observation']), procedure_status="OBSERVATION_RECORDED",
                   observation_evidence_status="USER_DECLARED_NOT_AUTHENTICATED", matched_rules=[])
        reason="NO_SOURCE_VERIFIED_RULE_CORPUS"
    else:
        missing_evidence = [row["song_id"] for row in config["rounds"] if "evidence_ref" not in row]
        raw.update(observed_rounds=deepcopy(config['rounds']),completion=config['completion'],
                   procedure_status="PENDING" if config['completion']=='ongoing' else "OBSERVATIONS_RECORDED",
                   regional_protocol_verification="UNVERIFIED",matched_song_interpretations=[],
                   observation_evidence_status="INCOMPLETE" if missing_evidence else "USER_DECLARED_NOT_AUTHENTICATED",
                   songs_missing_observation_evidence=missing_evidence)
        reason="REGIONAL_PROTOCOL_AND_SONG_CORPUS_UNVERIFIED"
    return {"core_id":core,"status":status,"reason":reason,"protocol_version":core+"-audited-input-v1",
            "inputs":inputs,"input_hash":digest(inputs),"raw_result":raw,
            "interpretation":"Conditional calculation or reported observations only; no verified historical interpretation or forecast.","claims":[]}
