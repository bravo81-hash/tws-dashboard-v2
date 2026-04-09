import json
import os
import sys
import traceback

from flask import jsonify, request, send_from_directory


def register_core_routes(
    app,
    *,
    base_dir,
    combos_file,
    portfolio_data,
    portfolio_lock,
    request_queue,
    underlying_prices,
    api_gate,
    get_ib_app,
    get_runtime_diagnostics,
    normalize_combos_payload,
    client_portal_adapter=None,
):
    @app.route("/")
    def serve_index():
        return send_from_directory(base_dir, "dashboard.html")

    @app.route("/<path:filename>")
    def serve_static(filename):
        return send_from_directory(base_dir, filename)

    @app.route("/data")
    def get_data():
        with portfolio_lock:
            data_copy = [dict(p) for p in portfolio_data.values()]
            return jsonify(data_copy)

    @app.route("/health", methods=["GET"])
    def get_health():
        runtime = get_runtime_diagnostics()
        with portfolio_lock:
            position_count = len(portfolio_data)
        is_snapshot = "--snapshot" in sys.argv
        ib_app = get_ib_app()
        connected = bool(ib_app and ib_app.isConnected())
        client_portal = (
            client_portal_adapter.health()
            if client_portal_adapter
            else {"enabled": False, "checked": False, "reachable": False}
        )

        return jsonify(
            {
                "status": "ok",
                "mode": "snapshot" if is_snapshot else "live",
                "connected_to_tws": connected,
                "positions": position_count,
                "queued_leg_requests": request_queue.qsize(),
                "runtime": runtime,
                "client_portal": client_portal,
            }
        )

    @app.route("/refresh_positions", methods=["POST"])
    def refresh_positions():
        if "--snapshot" in sys.argv:
            return jsonify(
                {
                    "status": "ignored",
                    "message": "Snapshot mode does not support live refresh.",
                }
            ), 200

        ib_app = get_ib_app()
        if not ib_app or not ib_app.isConnected():
            return jsonify({"error": "TWS not connected"}), 503

        try:
            api_gate.wait()
            ib_app.reqPositions()
            return jsonify({"status": "ok", "message": "Position refresh requested."})
        except Exception as exc:
            return jsonify({"error": f"Failed to refresh positions: {exc}"}), 500

    @app.route("/underlying_prices")
    def get_underlying_prices():
        return jsonify(dict(underlying_prices))

    @app.route("/request_leg_data", methods=["POST"])
    def request_leg_data():
        payload = request.get_json(silent=True) or {}
        con_id = payload.get("conId")
        if not isinstance(con_id, int):
            return jsonify({"error": "Invalid conId"}), 400

        with portfolio_lock:
            if con_id in portfolio_data:
                leg = portfolio_data[con_id]
                if leg.get("status") == "Queued":
                    try:
                        request_queue.put(con_id)
                        leg["status"] = "Loading..."
                        print(f"Queued request for conId {con_id}")
                        return jsonify({"status": "Request queued"})
                    except Exception:
                        print(
                            f"Error putting conId {con_id} in queue:\n{traceback.format_exc()}"
                        )
                        return jsonify({"error": "Failed to queue request"}), 500
                return jsonify(
                    {"status": "Request already active or leg not found/queued"}
                )
            return jsonify({"status": "conId not found in portfolio"})

    @app.route("/get_combos", methods=["GET"])
    def get_combos():
        if not os.path.exists(combos_file):
            print("combos.json not found, returning empty list.")
            return jsonify([])
        try:
            with open(combos_file, "r") as f:
                data = json.load(f)
            normalized, errors, warnings = normalize_combos_payload(data)
            if warnings:
                print("Combo normalization warnings:", warnings)
            if errors:
                print("Combo normalization errors:", errors)
            return jsonify(normalized)
        except Exception as exc:
            print(f"Error reading combos.json: {exc}")
            return jsonify({"error": str(exc)}), 500

    @app.route("/save_combos", methods=["POST"])
    def save_combos():
        temp_file = combos_file + ".tmp"
        backup_file = combos_file + ".bak"
        try:
            combos_data = request.get_json(silent=True)
            try:
                normalized_combos, errors, warnings = normalize_combos_payload(
                    combos_data
                )
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            if errors:
                return jsonify(
                    {"error": "Invalid combo payload", "details": errors}
                ), 400
            if any(len(combo.get("legs", [])) == 0 for combo in normalized_combos):
                return jsonify(
                    {"error": "Every combo must include at least one leg."}
                ), 400

            if warnings:
                print("Combo save warnings:", warnings)

            print(f"Attempting to save {len(normalized_combos)} combos.")
            with open(temp_file, "w") as f:
                json.dump(normalized_combos, f, indent=4)

            if os.path.exists(combos_file):
                os.replace(combos_file, backup_file)

            os.replace(temp_file, combos_file)

            if os.path.exists(backup_file):
                os.remove(backup_file)

            print("Combos saved successfully.")
            return jsonify({"status": "success"})

        except Exception as exc:
            error_msg = f"Error saving combos.json: {exc}"
            print(error_msg)
            traceback.print_exc()
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except OSError:
                    pass
            if os.path.exists(backup_file) and not os.path.exists(combos_file):
                try:
                    os.replace(backup_file, combos_file)
                    print("Restored combos.json from backup.")
                except OSError:
                    print("Could not restore combos.json from backup.")

            return jsonify({"error": error_msg}), 500
