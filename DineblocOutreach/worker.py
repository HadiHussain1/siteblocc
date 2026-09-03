import json
import os
import subprocess
import tempfile
import time
import urllib.request
import urllib.error

SERVER_URL = "https://dinebloc.com"
POLL_SECONDS = 3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")
SENDER = os.path.join(BASE_DIR, "instagram_test.py")


def request_json(url, method="GET", data=None):
    body = None
    headers = {}

    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def run_sender(payload):
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False)
            temp_path = handle.name

        command = [
            PYTHON,
            SENDER,
            "--payload",
            temp_path,
        ]

        print("[WORKER] Running:", command)

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if stdout:
            print("[SENDER]", stdout)

        if stderr:
            print("[SENDER ERROR]", stderr)

        if result.returncode != 0:
            return {
                "success": False,
                "error": stderr or stdout or "Instagram sender failed.",
                "details": {
                    "returncode": result.returncode,
                },
            }

        try:
            return json.loads(stdout.splitlines()[-1]) if stdout else {
                "success": False,
                "error": "Sender returned no JSON.",
            }
        except Exception:
            return {
                "success": False,
                "error": "Sender output could not be parsed.",
                "raw_output": stdout,
            }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Instagram sender timed out.",
        }

    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def main():
    print("[WORKER] Dinebloc Outreach Worker starting...")
    print("[WORKER] Server:", SERVER_URL)
    print("[WORKER] Python:", PYTHON)
    print("[WORKER] Sender:", SENDER)

    if not os.path.isfile(PYTHON):
        raise RuntimeError(f"Python not found: {PYTHON}")

    if not os.path.isfile(SENDER):
        raise RuntimeError(f"Sender not found: {SENDER}")

    while True:
        try:
            response = request_json(
                SERVER_URL + "/admin-api/outreach/worker/job"
            )

            if response.get("job"):
                job = response["job"]
                job_id = job.get("id")

                print(f"[WORKER] Job received: {job_id}")

                result = run_sender(job["payload"])

                request_json(
                    SERVER_URL + "/admin-api/outreach/worker/result",
                    method="POST",
                    data={
                        "job_id": job_id,
                        "result": result,
                    },
                )

                print(
                    f"[WORKER] Job {job_id} completed: "
                    f"{result.get('success')}"
                )

            time.sleep(POLL_SECONDS)

        except urllib.error.URLError as exc:
            print("[WORKER] Server connection error:", exc)
            time.sleep(POLL_SECONDS)

        except Exception as exc:
            print("[WORKER] Error:", exc)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()