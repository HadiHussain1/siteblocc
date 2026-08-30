import json
import logging
import os
import re
import subprocess
import threading
import time
import traceback
from datetime import datetime, timedelta

from flask import jsonify, request


STAGE_DAY_OFFSETS = {
    1: 0,
    2: 4,
    3: 10,
    4: 25,
}

DEFAULT_STAGE_TEMPLATES = {
    1: {
        1: "Hey {name} team",
        2: "We build premium websites for cafes that give customers a much better way to discover your menu, order online and connect with your business - while giving your team the tools to manage everything behind the scenes.",
        3: "We're currently offering the first 3 months completely free, including the full setup.",
        4: "Would you be open to a quick 2-minute demo of what we could build for {name}?",
    },
    2: {
        1: "Hey {name} team, just following up.",
        2: "We've put together a concept specifically for {name} so you can see exactly what it could look like for your business.",
        3: "Want me to send it through? It'll only take a couple of minutes to look over and decide whether it's worth exploring further.",
        4: "",
    },
    3: {
        1: "Hey {name} team - as promised, here's the {name} concept we put together:",
        2: "{WEBSITE_URL}",
        3: "We've designed it around giving {name} a stronger online presence - with your menu, ordering and key customer information all in one place.",
        4: "And behind the website is the Dinebloc admin system, where you can manage orders, customers, enquiries and other day-to-day operations from one place.",
    },
    4: {
        1: "Hey {name} team, just checking in regarding the concept we put together for you.",
        2: "If you'd like to take it further, we can handle the setup and get everything ready for {name}.",
        3: "If the timing isn't right, no problem at all - we'll leave it there for now.",
        4: "",
    },
}


class OutreachEngine:
    def __init__(
        self,
        app,
        *,
        get_db_connection,
        admin_required,
        ensure_concept_site,
    ):
        self.app = app
        self.get_db_connection = get_db_connection
        self.admin_required = admin_required
        self.ensure_concept_site = ensure_concept_site
        self.runner_interval_seconds = max(30, int(os.getenv("OUTREACH_RUNNER_INTERVAL_SECONDS", "60")))
        self.sender_python = os.getenv(
            "OUTREACH_SENDER_PYTHON",
            os.path.normpath(
                os.path.join(app.root_path, "..", "..", "DineblocOutreach", "venv", "Scripts", "python.exe")
            ),
        )
        self.sender_script = os.getenv(
            "OUTREACH_SENDER_SCRIPT",
            os.path.normpath(
                os.path.join(app.root_path, "..", "..", "DineblocOutreach", "send_instagram_messages.py")
            ),
        )
        self._runner_thread = None
        self._runner_guard = threading.Lock()
        self._register_routes()
        self.start_runner()

    def _log(self, level, prefix, message, *args):
        logging.log(level, "%s %s", prefix, message % args if args else message)

    def _stage_prefix(self, stage_number):
        return f"[STAGE {stage_number}]"

    def _register_routes(self):
        @self.app.route("/admin-api/outreach/overview")
        @self.admin_required
        def outreach_overview():
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                settings = self.get_settings(conn)
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT COUNT(*) AS cnt FROM outreach_leads")
                total = int((cursor.fetchone() or {}).get("cnt") or 0)
                cursor.execute("SELECT COUNT(*) AS cnt FROM outreach_leads WHERE automation_state='queued'")
                queued = int((cursor.fetchone() or {}).get("cnt") or 0)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM outreach_leads
                    WHERE automation_state IN ('active', 'awaiting_website')
                      AND next_action_at IS NOT NULL
                      AND next_action_at <= NOW()
                    """
                )
                due = int((cursor.fetchone() or {}).get("cnt") or 0)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM outreach_leads
                    WHERE automation_state IN ('paused', 'stopped', 'replied', 'completed')
                    """
                )
                halted = int((cursor.fetchone() or {}).get("cnt") or 0)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt
                    FROM outreach_message_events
                    WHERE send_mode='live' AND status='sent' AND stage_number=1 AND slot_number=1
                      AND DATE(sent_at) = CURDATE()
                    """
                )
                new_today = int((cursor.fetchone() or {}).get("cnt") or 0)
                cursor.close()
                return jsonify(
                    {
                        "settings": settings,
                        "stats": {
                            "total_leads": total,
                            "queued_leads": queued,
                            "due_follow_ups": due,
                            "halted_leads": halted,
                            "new_stage1_today": new_today,
                        },
                    }
                )
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/settings", methods=["POST"])
        @self.admin_required
        def outreach_save_settings():
            payload = request.get_json(silent=True) or {}
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                target = max(0, min(100, int(payload.get("daily_new_lead_target") or 0)))
                automation_enabled = 1 if payload.get("automation_enabled") else 0
                cdp_url = (payload.get("instagram_cdp_url") or "http://127.0.0.1:9223").strip()
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE outreach_settings
                    SET daily_new_lead_target=%s,
                        automation_enabled=%s,
                        instagram_cdp_url=%s
                    WHERE id=1
                    """,
                    (target, automation_enabled, cdp_url),
                )
                conn.commit()
                cursor.close()
                return jsonify({"success": True, "settings": self.get_settings(conn)})
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/templates")
        @self.admin_required
        def outreach_templates():
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                return jsonify({"templates": self.get_templates(conn)})
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/templates", methods=["POST"])
        @self.admin_required
        def outreach_save_templates():
            payload = request.get_json(silent=True) or {}
            rows = payload.get("templates") or []
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                cursor = conn.cursor()
                for row in rows:
                    stage_number = int(row.get("stage_number") or 0)
                    slot_number = int(row.get("slot_number") or 0)
                    template_text = (row.get("template_text") or "").strip()
                    is_enabled = 1 if row.get("is_enabled", True) else 0
                    if stage_number not in STAGE_DAY_OFFSETS or slot_number not in (1, 2, 3, 4):
                        continue
                    cursor.execute(
                        """
                        UPDATE outreach_templates
                        SET template_text=%s, is_enabled=%s
                        WHERE stage_number=%s AND slot_number=%s
                        """,
                        (template_text, is_enabled, stage_number, slot_number),
                    )
                conn.commit()
                cursor.close()
                return jsonify({"success": True, "templates": self.get_templates(conn)})
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads")
        @self.admin_required
        def outreach_leads():
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                return jsonify({"leads": self.list_leads(conn)})
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads", methods=["POST"])
        @self.admin_required
        def outreach_add_lead():
            payload = request.get_json(silent=True) or {}
            business_name = (payload.get("business_name") or "").strip()
            instagram_username = self.normalize_username(payload.get("instagram_username"))
            if not business_name or not instagram_username:
                return jsonify({"success": False, "error": "Business name and Instagram username are required."}), 400
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead_id = self.create_lead(conn, business_name, instagram_username)
                return jsonify({"success": True, "lead_id": lead_id})
            except ValueError as exc:
                return jsonify({"success": False, "error": str(exc)}), 409
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads/<int:lead_id>/status", methods=["POST"])
        @self.admin_required
        def outreach_update_lead_status(lead_id):
            payload = request.get_json(silent=True) or {}
            action = (payload.get("action") or "").strip().lower()
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead = self.get_lead(conn, lead_id)
                if not lead:
                    return jsonify({"success": False, "error": "Lead not found."}), 404
                try:
                    self.apply_status_action(conn, lead, action)
                except ValueError as exc:
                    return jsonify({"success": False, "error": str(exc)}), 400
                return jsonify({"success": True})
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads/<int:lead_id>/detail")
        @self.admin_required
        def outreach_lead_detail(lead_id):
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead = self.get_lead(conn, lead_id)
                if not lead:
                    return jsonify({"success": False, "error": "Lead not found."}), 404
                return jsonify(
                    {
                        "success": True,
                        "lead": self.serialize_lead(lead),
                        "events": self.get_lead_events(conn, lead_id),
                        "logs": self.get_lead_logs(conn, lead_id),
                    }
                )
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads/<int:lead_id>/test-stage", methods=["POST"])
        @self.admin_required
        def outreach_test_stage(lead_id):
            payload = request.get_json(silent=True) or {}
            stage_number = int(payload.get("stage_number") or 0)
            mode = (payload.get("mode") or "test").strip().lower()
            wait_seconds = 180 if mode == "test" and stage_number == 3 else 5
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead = self.get_lead(conn, lead_id)
                if not lead:
                    return jsonify({"success": False, "error": "Lead not found."}), 404
                result = self.run_stage(
                    conn,
                    lead,
                    stage_number=stage_number,
                    send_mode=mode,
                    test_wait_seconds=wait_seconds,
                    source="manual_stage_test",
                )
                status = 200 if result.get("success") else 400
                return jsonify(result), status
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads/<int:lead_id>/live-test-stage1", methods=["POST"])
        @self.admin_required
        def outreach_live_test_stage1(lead_id):
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead = self.get_lead(conn, lead_id)
                if not lead:
                    return jsonify({"success": False, "error": "Lead not found."}), 404
                result = self.run_live_stage1_single_message_test(conn, lead)
                status = 200 if result.get("success") else 400
                return jsonify(result), status
            except Exception as exc:
                logging.exception("[ERROR] [OUTREACH] [STAGE 1] Live Test S1 endpoint failed for lead_id=%s", lead_id)
                return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/leads/<int:lead_id>/test-slot", methods=["POST"])
        @self.admin_required
        def outreach_test_slot(lead_id):
            payload = request.get_json(silent=True) or {}
            stage_number = int(payload.get("stage_number") or 0)
            slot_number = int(payload.get("slot_number") or 0)
            conn = self.get_db_connection()
            try:
                self.ensure_schema(conn)
                lead = self.get_lead(conn, lead_id)
                if not lead:
                    return jsonify({"success": False, "error": "Lead not found."}), 404
                result = self.preview_slot(conn, lead, stage_number, slot_number)
                status = 200 if result.get("success") else 400
                return jsonify(result), status
            finally:
                conn.close()

        @self.app.route("/admin-api/outreach/process-now", methods=["POST"])
        @self.admin_required
        def outreach_process_now():
            summary = self.process_due_work(manual=True)
            status = 200 if summary.get("success", True) else 500
            return jsonify(summary), status

    def ensure_schema(self, conn):
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_settings (
                id TINYINT PRIMARY KEY,
                daily_new_lead_target INT NOT NULL DEFAULT 20,
                automation_enabled TINYINT(1) NOT NULL DEFAULT 0,
                instagram_cdp_url VARCHAR(255) NOT NULL DEFAULT 'http://127.0.0.1:9223',
                last_runner_heartbeat DATETIME NULL,
                last_runner_summary VARCHAR(255) NULL,
                last_runner_error TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_templates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                stage_number TINYINT NOT NULL,
                slot_number TINYINT NOT NULL,
                template_text TEXT NULL,
                is_enabled TINYINT(1) NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_stage_slot (stage_number, slot_number)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_leads (
                id INT AUTO_INCREMENT PRIMARY KEY,
                business_name VARCHAR(255) NOT NULL,
                instagram_username VARCHAR(255) NOT NULL,
                normalized_instagram_username VARCHAR(255) NOT NULL,
                current_stage TINYINT NOT NULL DEFAULT 0,
                next_stage_number TINYINT NOT NULL DEFAULT 1,
                campaign_started_at DATETIME NULL,
                next_action_at DATETIME NULL,
                automation_state VARCHAR(32) NOT NULL DEFAULT 'queued',
                reply_state VARCHAR(32) NOT NULL DEFAULT 'no_reply',
                website_project_id INT NULL,
                website_slug VARCHAR(255) NULL,
                website_url VARCHAR(255) NULL,
                website_status VARCHAR(32) NOT NULL DEFAULT 'not_started',
                stop_reason VARCHAR(255) NULL,
                last_error TEXT NULL,
                last_message_at DATETIME NULL,
                last_reply_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_outreach_username (normalized_instagram_username),
                INDEX idx_outreach_next_action (next_action_at),
                INDEX idx_outreach_state (automation_state, next_action_at)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_message_events (
                id INT AUTO_INCREMENT PRIMARY KEY,
                lead_id INT NOT NULL,
                stage_number TINYINT NOT NULL,
                slot_number TINYINT NOT NULL,
                send_mode VARCHAR(16) NOT NULL DEFAULT 'live',
                status VARCHAR(32) NOT NULL,
                template_snapshot TEXT NULL,
                rendered_text TEXT NULL,
                sent_at DATETIME NULL,
                failure_reason TEXT NULL,
                source VARCHAR(64) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_outreach_message_lead (lead_id, stage_number, slot_number),
                INDEX idx_outreach_message_sent (sent_at)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outreach_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                lead_id INT NULL,
                event_type VARCHAR(64) NOT NULL,
                message TEXT NOT NULL,
                details_json MEDIUMTEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_outreach_logs_lead (lead_id, created_at)
            )
            """
        )
        cursor.execute(
            """
            INSERT IGNORE INTO outreach_settings (id, daily_new_lead_target, automation_enabled, instagram_cdp_url)
            VALUES (1, 20, 0, 'http://127.0.0.1:9223')
            """
        )
        for stage_number, slots in DEFAULT_STAGE_TEMPLATES.items():
            for slot_number, template_text in slots.items():
                cursor.execute(
                    """
                    INSERT IGNORE INTO outreach_templates (stage_number, slot_number, template_text, is_enabled)
                    VALUES (%s, %s, %s, 1)
                    """,
                    (stage_number, slot_number, template_text),
                )
        conn.commit()
        cursor.close()

    def start_runner(self):
        with self._runner_guard:
            if self._runner_thread and self._runner_thread.is_alive():
                return
            self._runner_thread = threading.Thread(target=self._runner_loop, name="outreach-runner", daemon=True)
            self._runner_thread.start()

    def _runner_loop(self):
        while True:
            try:
                self.process_due_work(manual=False)
            except Exception:
                logging.exception("[OUTREACH] Runner loop failed")
            time.sleep(self.runner_interval_seconds)

    def process_due_work(self, manual=False):
        conn = self.get_db_connection()
        summary = {
            "success": True,
            "processed_followups": 0,
            "processed_new_leads": 0,
            "details": [],
        }
        lock_name = "dinebloc_outreach_runner"
        lock_cursor = None
        try:
            self.ensure_schema(conn)
            self._log(logging.INFO, "[OUTREACH]", "Queue processing started. manual=%s", manual)
            lock_cursor = conn.cursor()
            lock_cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
            lock_row = lock_cursor.fetchone()
            if not lock_row or int(lock_row[0] or 0) != 1:
                self._log(logging.INFO, "[OUTREACH]", "Queue processing skipped because runner lock is already held.")
                return {"success": True, "skipped": True, "message": "Outreach runner lock already held."}

            settings = self.get_settings(conn)
            if not manual and not settings.get("automation_enabled"):
                self._log(logging.INFO, "[OUTREACH]", "Queue processing skipped because automation is disabled.")
                self._update_runner_state(conn, "Automation disabled.", None)
                return {"success": True, "skipped": True, "message": "Automation disabled."}

            followups = self._get_due_followups(conn)
            self._log(logging.INFO, "[OUTREACH]", "Due follow-ups selected: %s", len(followups))
            for lead in followups:
                self._log(logging.INFO, "[OUTREACH]", "Processing due lead id=%s business='%s' next_stage=%s", lead["id"], lead.get("business_name"), lead.get("next_stage_number"))
                result = self.run_stage(
                    conn,
                    lead,
                    stage_number=int(lead["next_stage_number"]),
                    send_mode="live",
                    test_wait_seconds=5,
                    source="scheduled_followup",
                )
                summary["details"].append(result)
                if result.get("success"):
                    summary["processed_followups"] += 1

            remaining_new = max(0, int(settings.get("daily_new_lead_target") or 0) - self._count_new_stage1_sent_today(conn))
            self._log(logging.INFO, "[OUTREACH]", "Remaining Stage 1 new-lead capacity today: %s", remaining_new)
            if remaining_new > 0:
                queued = self._get_queued_leads(conn, remaining_new)
                self._log(logging.INFO, "[OUTREACH]", "Queued new leads selected: %s", len(queued))
                for lead in queued:
                    self._log(logging.INFO, "[OUTREACH]", "Processing queued lead id=%s business='%s'", lead["id"], lead.get("business_name"))
                    result = self.run_stage(
                        conn,
                        lead,
                        stage_number=1,
                        send_mode="live",
                        test_wait_seconds=5,
                        source="scheduled_new_lead",
                    )
                    summary["details"].append(result)
                    if result.get("success"):
                        summary["processed_new_leads"] += 1

            msg = f"Follow-ups: {summary['processed_followups']}, new leads: {summary['processed_new_leads']}"
            self._log(logging.INFO, "[OUTREACH]", "Queue processing finished. %s", msg)
            self._update_runner_state(conn, msg, None)
            return summary
        except Exception as exc:
            logging.exception("[ERROR] [OUTREACH] Queue processing failed")
            summary["success"] = False
            summary["error"] = str(exc)
            try:
                self._update_runner_state(conn, "Runner failed.", str(exc))
            except Exception:
                pass
            return summary
        finally:
            if lock_cursor:
                try:
                    lock_cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                except Exception:
                    pass
                lock_cursor.close()
            conn.close()

    def _update_runner_state(self, conn, summary, error):
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE outreach_settings
            SET last_runner_heartbeat=NOW(),
                last_runner_summary=%s,
                last_runner_error=%s
            WHERE id=1
            """,
            (summary, error),
        )
        conn.commit()
        cursor.close()

    def create_lead(self, conn, business_name, instagram_username):
        normalized = self.normalize_username(instagram_username)
        self._log(logging.INFO, "[OUTREACH]", "Creating lead business='%s' username='@%s'", business_name, normalized)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM outreach_leads WHERE normalized_instagram_username=%s LIMIT 1",
            (normalized,),
        )
        if cursor.fetchone():
            cursor.close()
            raise ValueError("That Instagram username already exists in outreach leads.")
        cursor.execute(
            """
            INSERT INTO outreach_leads (
                business_name,
                instagram_username,
                normalized_instagram_username,
                current_stage,
                next_stage_number,
                automation_state,
                reply_state,
                website_status
            )
            VALUES (%s, %s, %s, 0, 1, 'queued', 'no_reply', 'not_started')
            """,
            (business_name, normalized, normalized),
        )
        lead_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        self.log_event(conn, lead_id, "lead_created", "Lead added to outreach queue.", {"business_name": business_name, "instagram_username": normalized})
        return lead_id

    def get_settings(self, conn):
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM outreach_settings WHERE id=1 LIMIT 1")
        row = cursor.fetchone() or {}
        cursor.close()
        return {
            "daily_new_lead_target": int(row.get("daily_new_lead_target") or 0),
            "automation_enabled": bool(row.get("automation_enabled")),
            "instagram_cdp_url": row.get("instagram_cdp_url") or "http://127.0.0.1:9223",
            "last_runner_heartbeat": self.serialize_datetime(row.get("last_runner_heartbeat")),
            "last_runner_summary": row.get("last_runner_summary") or "",
            "last_runner_error": row.get("last_runner_error") or "",
        }

    def get_templates(self, conn):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT stage_number, slot_number, template_text, is_enabled
            FROM outreach_templates
            ORDER BY stage_number ASC, slot_number ASC
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                "stage_number": int(row["stage_number"]),
                "slot_number": int(row["slot_number"]),
                "template_text": row.get("template_text") or "",
                "is_enabled": bool(row.get("is_enabled")),
            }
            for row in rows
        ]

    def list_leads(self, conn):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM outreach_leads
            ORDER BY
                CASE automation_state
                    WHEN 'awaiting_website' THEN 0
                    WHEN 'active' THEN 1
                    WHEN 'queued' THEN 2
                    WHEN 'paused' THEN 3
                    WHEN 'replied' THEN 4
                    WHEN 'stopped' THEN 5
                    WHEN 'completed' THEN 6
                    ELSE 7
                END,
                COALESCE(next_action_at, created_at) ASC,
                id DESC
            LIMIT 500
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        return [self.serialize_lead(row) for row in rows]

    def get_lead(self, conn, lead_id):
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM outreach_leads WHERE id=%s LIMIT 1", (lead_id,))
        row = cursor.fetchone()
        cursor.close()
        return row

    def serialize_lead(self, row):
        return {
            "id": int(row["id"]),
            "business_name": row.get("business_name") or "",
            "instagram_username": row.get("instagram_username") or "",
            "current_stage": int(row.get("current_stage") or 0),
            "next_stage_number": int(row.get("next_stage_number") or 0),
            "campaign_started_at": self.serialize_datetime(row.get("campaign_started_at")),
            "next_action_at": self.serialize_datetime(row.get("next_action_at")),
            "automation_state": row.get("automation_state") or "",
            "reply_state": row.get("reply_state") or "",
            "website_project_id": row.get("website_project_id"),
            "website_slug": row.get("website_slug") or "",
            "website_url": row.get("website_url") or "",
            "website_status": row.get("website_status") or "",
            "stop_reason": row.get("stop_reason") or "",
            "last_error": row.get("last_error") or "",
            "last_message_at": self.serialize_datetime(row.get("last_message_at")),
            "last_reply_at": self.serialize_datetime(row.get("last_reply_at")),
            "created_at": self.serialize_datetime(row.get("created_at")),
            "updated_at": self.serialize_datetime(row.get("updated_at")),
        }

    def get_lead_events(self, conn, lead_id):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT stage_number, slot_number, send_mode, status, rendered_text, sent_at, failure_reason, source, created_at
            FROM outreach_message_events
            WHERE lead_id=%s
            ORDER BY id DESC
            LIMIT 80
            """,
            (lead_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                "stage_number": int(row.get("stage_number") or 0),
                "slot_number": int(row.get("slot_number") or 0),
                "send_mode": row.get("send_mode") or "",
                "status": row.get("status") or "",
                "rendered_text": row.get("rendered_text") or "",
                "sent_at": self.serialize_datetime(row.get("sent_at")),
                "failure_reason": row.get("failure_reason") or "",
                "source": row.get("source") or "",
                "created_at": self.serialize_datetime(row.get("created_at")),
            }
            for row in rows
        ]

    def get_lead_logs(self, conn, lead_id):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT event_type, message, details_json, created_at
            FROM outreach_logs
            WHERE lead_id=%s
            ORDER BY id DESC
            LIMIT 80
            """,
            (lead_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        result = []
        for row in rows:
            details_json = row.get("details_json")
            try:
                details = json.loads(details_json) if details_json else None
            except Exception:
                details = details_json
            result.append(
                {
                    "event_type": row.get("event_type") or "",
                    "message": row.get("message") or "",
                    "details": details,
                    "created_at": self.serialize_datetime(row.get("created_at")),
                }
            )
        return result

    def apply_status_action(self, conn, lead, action):
        cursor = conn.cursor()
        lead_id = int(lead["id"])
        self._log(logging.INFO, "[OUTREACH]", "Lead action requested. lead_id=%s action=%s", lead_id, action)
        if action == "pause":
            cursor.execute(
                "UPDATE outreach_leads SET automation_state='paused', stop_reason='Paused manually' WHERE id=%s",
                (lead_id,),
            )
            self.log_event(conn, lead_id, "lead_paused", "Lead paused manually.", None)
        elif action == "resume":
            next_stage = int(lead.get("next_stage_number") or max(int(lead.get("current_stage") or 0) + 1, 1))
            campaign_started_at = lead.get("campaign_started_at") or datetime.now()
            next_action_at = self.calculate_next_action(campaign_started_at, next_stage)
            if next_stage == 1:
                next_action_at = None
            cursor.execute(
                """
                UPDATE outreach_leads
                SET automation_state=%s,
                    stop_reason=NULL,
                    reply_state='no_reply',
                    next_stage_number=%s,
                    next_action_at=%s
                WHERE id=%s
                """,
                ("queued" if next_stage == 1 else "active", next_stage, next_action_at, lead_id),
            )
            self.log_event(conn, lead_id, "lead_resumed", "Lead resumed manually.", {"next_stage_number": next_stage})
        elif action == "stop":
            cursor.execute(
                "UPDATE outreach_leads SET automation_state='stopped', stop_reason='Stopped manually' WHERE id=%s",
                (lead_id,),
            )
            self.log_event(conn, lead_id, "lead_stopped", "Lead stopped manually.", None)
        elif action == "mark_replied":
            cursor.execute(
                """
                UPDATE outreach_leads
                SET automation_state='replied',
                    reply_state='replied',
                    last_reply_at=NOW(),
                    stop_reason='Lead replied'
                WHERE id=%s
                """,
                (lead_id,),
            )
            self.log_event(conn, lead_id, "lead_replied", "Lead marked as replied.", None)
        elif action == "clear_reply":
            next_stage = int(lead.get("next_stage_number") or 1)
            next_action_at = lead.get("next_action_at")
            if next_stage > 1 and not next_action_at and lead.get("campaign_started_at"):
                next_action_at = self.calculate_next_action(lead["campaign_started_at"], next_stage)
            cursor.execute(
                """
                UPDATE outreach_leads
                SET automation_state=%s,
                    reply_state='no_reply',
                    stop_reason=NULL,
                    next_action_at=%s
                WHERE id=%s
                """,
                ("queued" if next_stage == 1 else "active", next_action_at, lead_id),
            )
            self.log_event(conn, lead_id, "reply_cleared", "Reply hold cleared.", None)
        else:
            cursor.close()
            raise ValueError(f"Unsupported action: {action}")
        conn.commit()
        cursor.close()

    def preview_slot(self, conn, lead, stage_number, slot_number):
        if stage_number not in STAGE_DAY_OFFSETS or slot_number not in (1, 2, 3, 4):
            return {"success": False, "error": "Invalid stage or slot."}
        rendered = self.render_stage_messages(conn, lead, stage_number, ensure_website=(stage_number == 3), wait_seconds=180)
        if not rendered.get("success"):
            return rendered
        slot = next((item for item in rendered["messages"] if item["slot_number"] == slot_number), None)
        if not slot:
            return {"success": False, "error": "Slot not found."}
        self.record_message_event(
            conn,
            lead_id=int(lead["id"]),
            stage_number=stage_number,
            slot_number=slot_number,
            send_mode="test",
            status="previewed",
            template_snapshot=slot.get("template_text"),
            rendered_text=slot.get("rendered_text"),
            source="manual_slot_test",
        )
        self.log_event(
            conn,
            int(lead["id"]),
            "slot_preview",
            f"Previewed Stage {stage_number} Slot {slot_number}.",
            {"rendered_text": slot.get("rendered_text")},
        )
        return {"success": True, "message": slot}

    def run_stage(self, conn, lead, *, stage_number, send_mode, test_wait_seconds, source):
        lead_id = int(lead["id"])
        stage_prefix = self._stage_prefix(stage_number)
        self._log(logging.INFO, "[OUTREACH]", "Lead selected. lead_id=%s business='%s' stage=%s mode=%s source=%s", lead_id, lead.get("business_name"), stage_number, send_mode, source)
        if stage_number not in STAGE_DAY_OFFSETS:
            return {"success": False, "lead_id": lead_id, "error": "Invalid stage."}
        if send_mode == "live" and lead.get("automation_state") in {"paused", "stopped", "replied", "completed"}:
            return {"success": False, "lead_id": lead_id, "error": f"Lead is {lead.get('automation_state')}."}

        rendered = self.render_stage_messages(
            conn,
            lead,
            stage_number,
            ensure_website=(stage_number == 3),
            wait_seconds=test_wait_seconds if send_mode == "test" else 5,
        )
        if not rendered.get("success"):
            self._log(logging.ERROR, "[ERROR]", "%s Rendering failed for lead_id=%s error=%s", stage_prefix, lead_id, rendered.get("error"))
            self._mark_stage_waiting_or_failed(conn, lead_id, stage_number, rendered)
            return {"success": False, "lead_id": lead_id, "stage_number": stage_number, **rendered}

        message_rows = rendered["messages"]
        deliverable = [item for item in message_rows if item.get("is_enabled") and (item.get("rendered_text") or "").strip()]
        self._log(logging.INFO, stage_prefix, "Stage selected with %s enabled deliverable messages for lead_id=%s mode=%s", len(deliverable), lead_id, send_mode)

        if send_mode == "test":
            self._log(logging.INFO, stage_prefix, "Safe test mode active for lead_id=%s. No live Instagram send will occur.", lead_id)
            for item in deliverable:
                self._log(logging.INFO, stage_prefix, "Rendered slot=%s text=%r", item["slot_number"], item.get("rendered_text"))
                self.record_message_event(
                    conn,
                    lead_id=lead_id,
                    stage_number=stage_number,
                    slot_number=item["slot_number"],
                    send_mode="test",
                    status="previewed",
                    template_snapshot=item.get("template_text"),
                    rendered_text=item.get("rendered_text"),
                    source=source,
                )
            self.log_event(conn, lead_id, "stage_preview", f"Previewed Stage {stage_number}.", {"messages": deliverable})
            return {
                "success": True,
                "lead_id": lead_id,
                "stage_number": stage_number,
                "send_mode": "test",
                "messages": deliverable,
                "website_url": rendered.get("website_url"),
                "website_status": rendered.get("website_status"),
            }

        unsent = []
        for item in deliverable:
            if not self._live_message_already_sent(conn, lead_id, stage_number, item["slot_number"]):
                unsent.append(item)
            else:
                self._log(logging.INFO, stage_prefix, "Duplicate prevention skipped slot=%s for lead_id=%s because it was already sent live.", item["slot_number"], lead_id)

        if not unsent:
            self.log_event(conn, lead_id, "duplicate_prevented", f"Skipped Stage {stage_number}; all live messages already sent.", None)
            return {
                "success": True,
                "lead_id": lead_id,
                "stage_number": stage_number,
                "send_mode": "live",
                "messages": [],
                "duplicate_prevented": True,
            }

        for item in unsent:
            self._log(logging.INFO, stage_prefix, "Prepared slot=%s for live send. text=%r", item["slot_number"], item.get("rendered_text"))
        send_result = self._send_live_messages(conn, lead, stage_number, unsent)
        if not send_result.get("success"):
            failure = send_result.get("error") or "Instagram send failed."
            self._log(logging.ERROR, "[ERROR]", "%s Instagram send failed for lead_id=%s step=%s error=%s", stage_prefix, lead_id, send_result.get("step"), failure)
            for item in unsent:
                self.record_message_event(
                    conn,
                    lead_id=lead_id,
                    stage_number=stage_number,
                    slot_number=item["slot_number"],
                    send_mode="live",
                    status="failed",
                    template_snapshot=item.get("template_text"),
                    rendered_text=item.get("rendered_text"),
                    failure_reason=failure,
                    source=source,
                )
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE outreach_leads
                SET last_error=%s,
                    next_action_at=%s,
                    automation_state=%s
                WHERE id=%s
                """,
                (failure, datetime.now() + timedelta(minutes=30), "active", lead_id),
            )
            conn.commit()
            cursor.close()
            self.log_event(conn, lead_id, "send_failed", f"Stage {stage_number} failed to send.", {"error": failure})
            return {"success": False, "lead_id": lead_id, "stage_number": stage_number, "error": failure, "step": send_result.get("step"), "details": send_result.get("details")}

        sent_at = datetime.now()
        self._log(logging.INFO, stage_prefix, "Instagram send confirmed for lead_id=%s message_count=%s", lead_id, len(unsent))
        for item in unsent:
            self.record_message_event(
                conn,
                lead_id=lead_id,
                stage_number=stage_number,
                slot_number=item["slot_number"],
                send_mode="live",
                status="sent",
                template_snapshot=item.get("template_text"),
                rendered_text=item.get("rendered_text"),
                sent_at=sent_at,
                source=source,
            )
        self._mark_stage_complete(conn, lead, stage_number, sent_at, rendered)
        self.log_event(conn, lead_id, "stage_sent", f"Stage {stage_number} sent successfully.", {"messages": unsent})
        return {
            "success": True,
            "lead_id": lead_id,
            "stage_number": stage_number,
            "send_mode": "live",
            "messages": unsent,
            "website_url": rendered.get("website_url"),
            "website_status": rendered.get("website_status"),
        }

    def run_live_stage1_single_message_test(self, conn, lead):
        lead_id = int(lead["id"])
        stage_number = 1
        stage_prefix = self._stage_prefix(stage_number)
        self._log(logging.INFO, "[OUTREACH]", "Live Test S1 requested. lead_id=%s business='%s' username='@%s'", lead_id, lead.get("business_name"), lead.get("instagram_username"))
        self._log(logging.INFO, stage_prefix, "Live Test S1 starting. This will send exactly one Stage 1 message and will not advance the lead or process the queue.")
        try:
            rendered = self.render_stage_messages(
                conn,
                lead,
                stage_number,
                ensure_website=False,
                wait_seconds=5,
            )
            if not rendered.get("success"):
                self._log(logging.ERROR, "[ERROR]", "%s Live Test S1 render failed for lead_id=%s error=%s", stage_prefix, lead_id, rendered.get("error"))
                return {"success": False, "lead_id": lead_id, "stage_number": 1, "error": rendered.get("error"), "traceback": traceback.format_exc()}

            first_message = None
            for item in rendered["messages"]:
                if item.get("is_enabled") and (item.get("rendered_text") or "").strip():
                    first_message = item
                    break
            if not first_message:
                return {"success": False, "lead_id": lead_id, "stage_number": 1, "error": "No enabled Stage 1 message is available to send."}

            self._log(logging.INFO, stage_prefix, "Live Test S1 selected slot=%s text=%r", first_message["slot_number"], first_message.get("rendered_text"))
            send_result = self._send_live_messages(conn, lead, 1, [first_message], source="manual_live_test_stage1")
            if not send_result.get("success"):
                self._log(logging.ERROR, "[ERROR]", "%s Live Test S1 failed for lead_id=%s step=%s error=%s", stage_prefix, lead_id, send_result.get("step"), send_result.get("error"))
                self.record_message_event(
                    conn,
                    lead_id=lead_id,
                    stage_number=1,
                    slot_number=first_message["slot_number"],
                    send_mode="live_test",
                    status="failed",
                    template_snapshot=first_message.get("template_text"),
                    rendered_text=first_message.get("rendered_text"),
                    failure_reason=send_result.get("error"),
                    source="manual_live_test_stage1",
                )
                self.log_event(conn, lead_id, "live_test_stage1_failed", "Live Test S1 failed.", send_result)
                return {
                    "success": False,
                    "lead_id": lead_id,
                    "stage_number": 1,
                    "slot_number": first_message["slot_number"],
                    "error": send_result.get("error"),
                    "step": send_result.get("step"),
                    "details": send_result.get("details"),
                    "traceback": send_result.get("traceback"),
                }

            sent_at = datetime.now()
            self.record_message_event(
                conn,
                lead_id=lead_id,
                stage_number=1,
                slot_number=first_message["slot_number"],
                send_mode="live_test",
                status="sent",
                template_snapshot=first_message.get("template_text"),
                rendered_text=first_message.get("rendered_text"),
                sent_at=sent_at,
                source="manual_live_test_stage1",
            )
            self.log_event(conn, lead_id, "live_test_stage1_sent", "Live Test S1 sent successfully.", {"slot_number": first_message["slot_number"]})
            self._log(logging.INFO, stage_prefix, "Live Test S1 completed successfully for lead_id=%s slot=%s", lead_id, first_message["slot_number"])
            return {
                "success": True,
                "lead_id": lead_id,
                "stage_number": 1,
                "slot_number": first_message["slot_number"],
                "message": first_message.get("rendered_text"),
                "send_mode": "live_test",
            }
        except Exception as exc:
            logging.exception("[ERROR] [OUTREACH] [STAGE 1] Live Test S1 crashed for lead_id=%s", lead_id)
            return {
                "success": False,
                "lead_id": lead_id,
                "stage_number": 1,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }

    def render_stage_messages(self, conn, lead, stage_number, *, ensure_website, wait_seconds):
        stage_prefix = self._stage_prefix(stage_number)
        templates = self.get_templates(conn)
        template_rows = [row for row in templates if row["stage_number"] == stage_number]
        if len(template_rows) != 4:
            return {"success": False, "error": "Stage templates are incomplete."}
        website_url = lead.get("website_url") or ""
        website_status = lead.get("website_status") or "not_started"
        website_project_id = lead.get("website_project_id")
        website_slug = lead.get("website_slug") or ""

        if ensure_website:
            self._log(logging.INFO, stage_prefix, "Stage 3 website generation/integration started for lead_id=%s", int(lead["id"]))
            site_result = self.ensure_concept_site(
                {
                    "lead_id": int(lead["id"]),
                    "business_name": lead.get("business_name") or "",
                    "instagram_username": lead.get("instagram_username") or "",
                    "website_project_id": website_project_id,
                    "website_slug": website_slug,
                    "website_url": website_url,
                },
                wait_seconds=wait_seconds,
            )
            if not site_result.get("success"):
                self._log(logging.ERROR, "[ERROR]", "%s Website integration failed for lead_id=%s error=%s", stage_prefix, int(lead["id"]), site_result.get("error"))
                return {"success": False, "error": site_result.get("error") or "Website generation failed.", "website_status": site_result.get("website_status") or "error"}
            website_url = site_result.get("website_url") or ""
            website_status = site_result.get("website_status") or "ready"
            website_project_id = site_result.get("project_id")
            website_slug = site_result.get("slug") or ""
            self._log(logging.INFO, stage_prefix, "Website integration status for lead_id=%s project_id=%s slug=%s status=%s url=%s", int(lead["id"]), website_project_id, website_slug, website_status, website_url)
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE outreach_leads
                SET website_project_id=%s,
                    website_slug=%s,
                    website_url=%s,
                    website_status=%s
                WHERE id=%s
                """,
                (website_project_id, website_slug, website_url, website_status, int(lead["id"])),
            )
            conn.commit()
            cursor.close()
            if website_status != "ready" or not website_url:
                return {
                    "success": False,
                    "error": "Website concept is still deploying.",
                    "website_status": website_status or "deploying",
                    "website_url": website_url,
                }

        rendered_messages = []
        for row in sorted(template_rows, key=lambda item: item["slot_number"]):
            rendered_text = self._render_template(
                row.get("template_text") or "",
                lead.get("business_name") or "",
                website_url,
            )
            rendered_messages.append(
                {
                    "stage_number": stage_number,
                    "slot_number": row["slot_number"],
                    "template_text": row.get("template_text") or "",
                    "rendered_text": rendered_text,
                    "is_enabled": bool(row.get("is_enabled")),
                }
            )
            self._log(logging.INFO, stage_prefix, "Message rendered. lead_id=%s slot=%s enabled=%s text=%r", int(lead["id"]), row["slot_number"], bool(row.get("is_enabled")), rendered_text)

        return {
            "success": True,
            "messages": rendered_messages,
            "website_url": website_url,
            "website_status": website_status,
        }

    def _mark_stage_waiting_or_failed(self, conn, lead_id, stage_number, rendered):
        self._log(logging.INFO, self._stage_prefix(stage_number), "Marking stage waiting/failed for lead_id=%s website_status=%s error=%s", lead_id, rendered.get("website_status"), rendered.get("error"))
        cursor = conn.cursor()
        if rendered.get("website_status") in {"deploying", "created", "queued"}:
            cursor.execute(
                """
                UPDATE outreach_leads
                SET automation_state='awaiting_website',
                    website_status=%s,
                    next_action_at=%s,
                    last_error=NULL
                WHERE id=%s
                """,
                (rendered.get("website_status"), datetime.now() + timedelta(minutes=10), lead_id),
            )
        else:
            cursor.execute(
                """
                UPDATE outreach_leads
                SET automation_state='active',
                    last_error=%s,
                    next_action_at=%s
                WHERE id=%s
                """,
                (rendered.get("error"), datetime.now() + timedelta(minutes=30), lead_id),
            )
        conn.commit()
        cursor.close()

    def _mark_stage_complete(self, conn, lead, stage_number, sent_at, rendered):
        lead_id = int(lead["id"])
        self._log(logging.INFO, self._stage_prefix(stage_number), "Recording stage completion for lead_id=%s at=%s", lead_id, self.serialize_datetime(sent_at))
        campaign_started_at = lead.get("campaign_started_at") or sent_at
        if stage_number == 1 and not lead.get("campaign_started_at"):
            campaign_started_at = sent_at
        next_stage = stage_number + 1
        if next_stage > 4:
            next_state = "completed"
            next_action_at = None
        else:
            next_state = "active"
            next_action_at = self.calculate_next_action(campaign_started_at, next_stage)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE outreach_leads
            SET current_stage=%s,
                next_stage_number=%s,
                campaign_started_at=%s,
                next_action_at=%s,
                automation_state=%s,
                website_url=%s,
                website_status=%s,
                last_message_at=%s,
                last_error=NULL
            WHERE id=%s
            """,
            (
                stage_number,
                min(next_stage, 5),
                campaign_started_at,
                next_action_at,
                next_state,
                rendered.get("website_url") or lead.get("website_url"),
                rendered.get("website_status") or lead.get("website_status") or "not_started",
                sent_at,
                lead_id,
            ),
        )
        conn.commit()
        cursor.close()

    def _send_live_messages(self, conn, lead, stage_number, unsent, source="live_send"):
        settings = self.get_settings(conn)
        stage_prefix = self._stage_prefix(stage_number)
        payload = {
            "username": lead.get("instagram_username") or "",
            "cdp_url": settings.get("instagram_cdp_url") or "http://127.0.0.1:9223",
            "messages": [item["rendered_text"] for item in unsent],
        }
        self._log(logging.INFO, "[INSTAGRAM]", "%s Invoking Instagram sender for lead_id=%s username='@%s' message_count=%s source=%s", stage_prefix, lead.get("id"), lead.get("instagram_username"), len(unsent), source)
        if not os.path.isfile(self.sender_script):
            return {"success": False, "error": f"Instagram sender script not found: {self.sender_script}"}
        if not os.path.isfile(self.sender_python):
            return {"success": False, "error": f"Instagram sender Python not found: {self.sender_python}"}
        temp_path = os.path.join(self.app.root_path, "outreach_sender_payload.json")
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        try:
            command = [self.sender_python, self.sender_script, "--payload", temp_path]
            self._log(logging.INFO, "[INSTAGRAM]", "%s Sender subprocess starting. command=%r", stage_prefix, command)
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            self._log(logging.INFO, "[INSTAGRAM]", "%s Sender subprocess finished with exit_code=%s", stage_prefix, result.returncode)
        except subprocess.TimeoutExpired:
            logging.exception("[ERROR] [INSTAGRAM] Sender timed out for lead_id=%s", lead.get("id"))
            return {"success": False, "error": "Instagram sender timed out.", "step": "subprocess_timeout", "traceback": traceback.format_exc()}
        except Exception as exc:
            logging.exception("[ERROR] [INSTAGRAM] Sender subprocess crashed for lead_id=%s", lead.get("id"))
            return {"success": False, "error": str(exc), "step": "subprocess_start", "traceback": traceback.format_exc()}
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if stdout:
            for line in stdout.splitlines():
                self._log(logging.INFO, "[INSTAGRAM]", "subprocess stdout: %s", line)
        if stderr:
            for line in stderr.splitlines():
                self._log(logging.INFO, "[INSTAGRAM]", "subprocess stderr: %s", line)
        if result.returncode != 0:
            return {
                "success": False,
                "error": stderr or stdout or "Instagram sender failed.",
                "step": "subprocess_nonzero_exit",
                "details": {"returncode": result.returncode},
                "traceback": stderr or None,
            }
        try:
            parsed = json.loads(stdout.splitlines()[-1]) if stdout else {}
        except Exception:
            logging.exception("[ERROR] [INSTAGRAM] Failed to parse sender JSON output for lead_id=%s", lead.get("id"))
            return {"success": False, "error": "Instagram sender output could not be parsed.", "step": "parse_sender_output", "traceback": traceback.format_exc()}
        if not parsed.get("success"):
            return {
                "success": False,
                "error": parsed.get("error") or stderr or stdout or "Instagram sender failed.",
                "step": parsed.get("step"),
                "details": parsed.get("details"),
                "traceback": parsed.get("traceback") or stderr or None,
            }
        return {"success": True, "raw": parsed}

    def _live_message_already_sent(self, conn, lead_id, stage_number, slot_number):
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id
            FROM outreach_message_events
            WHERE lead_id=%s
              AND stage_number=%s
              AND slot_number=%s
              AND send_mode='live'
              AND status='sent'
            LIMIT 1
            """,
            (lead_id, stage_number, slot_number),
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists

    def record_message_event(
        self,
        conn,
        *,
        lead_id,
        stage_number,
        slot_number,
        send_mode,
        status,
        template_snapshot,
        rendered_text,
        sent_at=None,
        failure_reason=None,
        source=None,
    ):
        self._log(logging.INFO, "[OUTREACH]", "Database event recorded. lead_id=%s stage=%s slot=%s mode=%s status=%s", lead_id, stage_number, slot_number, send_mode, status)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO outreach_message_events (
                lead_id,
                stage_number,
                slot_number,
                send_mode,
                status,
                template_snapshot,
                rendered_text,
                sent_at,
                failure_reason,
                source
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                lead_id,
                stage_number,
                slot_number,
                send_mode,
                status,
                template_snapshot,
                rendered_text,
                sent_at,
                failure_reason,
                source,
            ),
        )
        conn.commit()
        cursor.close()

    def log_event(self, conn, lead_id, event_type, message, details):
        self._log(logging.INFO, "[OUTREACH]", "Lead log recorded. lead_id=%s type=%s message=%s", lead_id, event_type, message)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO outreach_logs (lead_id, event_type, message, details_json)
            VALUES (%s, %s, %s, %s)
            """,
            (lead_id, event_type, message, json.dumps(details) if details is not None else None),
        )
        conn.commit()
        cursor.close()

    def _get_due_followups(self, conn):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM outreach_leads
            WHERE automation_state IN ('active', 'awaiting_website')
              AND next_stage_number BETWEEN 2 AND 4
              AND next_action_at IS NOT NULL
              AND next_action_at <= NOW()
              AND reply_state='no_reply'
            ORDER BY next_action_at ASC, id ASC
            LIMIT 100
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _get_queued_leads(self, conn, limit_count):
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM outreach_leads
            WHERE automation_state='queued'
              AND reply_state='no_reply'
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (limit_count,),
        )
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def _count_new_stage1_sent_today(self, conn):
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM outreach_message_events
            WHERE send_mode='live'
              AND status='sent'
              AND stage_number=1
              AND slot_number=1
              AND DATE(sent_at) = CURDATE()
            """
        )
        count = int((cursor.fetchone() or [0])[0] or 0)
        cursor.close()
        return count

    def calculate_next_action(self, campaign_started_at, stage_number):
        if not campaign_started_at or stage_number not in STAGE_DAY_OFFSETS:
            return None
        return campaign_started_at + timedelta(days=STAGE_DAY_OFFSETS[stage_number])

    def _render_template(self, template_text, business_name, website_url):
        text = (template_text or "").replace("{name}", business_name or "")
        text = text.replace("{WEBSITE_URL}", website_url or "")
        text = text.replace("{WEBSITE\\_URL}", website_url or "")
        return text.strip()

    def normalize_username(self, username):
        value = (username or "").strip().lower()
        value = value.lstrip("@")
        value = re.sub(r"[^a-z0-9._]", "", value)
        return value

    def serialize_datetime(self, value):
        if not value:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat(sep=" ", timespec="seconds")
        return str(value)
