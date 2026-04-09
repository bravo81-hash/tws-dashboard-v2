from datetime import datetime

VALID_LEG_STATUSES = {"open", "closed"}


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_combo_leg(raw_leg):
    if not isinstance(raw_leg, dict):
        return None, "Leg must be an object."

    con_id = raw_leg.get("conId")
    qty = safe_float(raw_leg.get("qty"), None)
    if not isinstance(con_id, int):
        return None, "Missing/invalid conId."
    if qty is None:
        return None, "Missing/invalid qty."

    status = str(raw_leg.get("status", "open")).strip().lower()
    if status not in VALID_LEG_STATUSES:
        status = "open"

    normalized = {
        "conId": con_id,
        "qty": qty,
        "status": status,
        "costBasis": None,
        "realizedPnl": safe_float(raw_leg.get("realizedPnl"), 0.0),
    }

    if raw_leg.get("costBasis") is not None:
        normalized["costBasis"] = safe_float(raw_leg.get("costBasis"), 0.0)
    if raw_leg.get("closingPrice") is not None:
        normalized["closingPrice"] = safe_float(raw_leg.get("closingPrice"), 0.0)

    return normalized, None


def normalize_combos_payload(raw_combos):
    if not isinstance(raw_combos, list):
        raise ValueError("Combos payload must be a list.")

    normalized = []
    errors = []
    warnings = []

    for combo_index, raw_combo in enumerate(raw_combos):
        if not isinstance(raw_combo, dict):
            errors.append(f"Combo at index {combo_index} must be an object.")
            continue

        name = str(raw_combo.get("name") or f"Combo {combo_index + 1}").strip()
        group = str(raw_combo.get("group") or "Default").strip() or "Default"
        created_at = raw_combo.get("createdAt")
        if not isinstance(created_at, str) or not created_at.strip():
            created_at = datetime.utcnow().isoformat()

        legs = []
        raw_legs = raw_combo.get("legs")
        if isinstance(raw_legs, list):
            for leg_index, raw_leg in enumerate(raw_legs):
                leg, leg_error = normalize_combo_leg(raw_leg)
                if leg_error:
                    errors.append(f"Combo '{name}' leg {leg_index}: {leg_error}")
                    continue
                legs.append(leg)
        else:
            legacy_leg_con_ids = raw_combo.get("legConIds")
            if isinstance(legacy_leg_con_ids, list):
                warnings.append(
                    f"Combo '{name}' used legacy legConIds shape; migrated to legs."
                )
                for con_id in legacy_leg_con_ids:
                    if isinstance(con_id, int):
                        legs.append(
                            {
                                "conId": con_id,
                                "qty": 0.0,
                                "status": "open",
                                "costBasis": None,
                                "realizedPnl": 0.0,
                            }
                        )
                    else:
                        errors.append(f"Combo '{name}' has non-integer legacy conId.")
            else:
                errors.append(f"Combo '{name}' is missing legs.")

        normalized.append(
            {
                "name": name,
                "group": group,
                "createdAt": created_at,
                "legs": legs,
            }
        )

    return normalized, errors, warnings
