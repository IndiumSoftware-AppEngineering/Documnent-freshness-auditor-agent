import threading

waiting = {}
lock = threading.Lock()
thread_to_report = {}
original_func = None
is_patched = False


def link_report(report_id):
    tid = threading.current_thread().ident
    thread_to_report[tid] = report_id
    print(f"[HITL] linked thread={tid} to report={report_id}")


def get_report_for_thread():
    tid = threading.current_thread().ident
    rid = thread_to_report.get(tid)
    print(f"[HITL] thread={tid} is working on report={rid}")
    return rid


def unlink_report():
    tid = threading.current_thread().ident
    thread_to_report.pop(tid, None)


def send_feedback(report_id, feedback):
    with lock:
        entry = waiting.get(report_id)
        if entry is None or entry["event"].is_set():
            return False
        entry["feedback"] = feedback
        entry["event"].set()
    print(f"[HITL] feedback sent for {report_id}, length={len(feedback)}")
    return True


def remove(report_id):
    with lock:
        waiting.pop(report_id, None)
    unlink_report()
    print(f"[HITL] cleaned up report={report_id}")


def ask_human_via_api(self, final_answer):
    print(f"[HITL] >>> ask_human_via_api called! thread={threading.current_thread().ident}")
    print(f"[HITL]     answer length: {len(final_answer)}")

    report_id = get_report_for_thread()
    if report_id is None:
        print("[HITL] WARNING: no report linked, using terminal input()")
        return original_func(self, final_answer)

    print(f"[HITL] pausing crew for report {report_id}, waiting for feedback...")

    entry = {
        "report_id": report_id,
        "agent_output": final_answer,
        "feedback": None,
        "event": threading.Event()
    }
    with lock:
        waiting[report_id] = entry

    try:
        from document_freshness_auditor import db
        db.set_status(report_id, "pending_human_input", agent_output=final_answer)
        print(f"[HITL] db updated to pending_human_input for {report_id}")
    except Exception as e:
        print(f"[HITL] ERROR updating db: {e}")

    print(f"[HITL] waiting for feedback on {report_id}...")
    entry["event"].wait()

    feedback = entry["feedback"] or ""
    print(f"[HITL] got feedback for {report_id}: {feedback[:100]!r}")

    try:
        from document_freshness_auditor import db
        db.set_status(report_id, "processing")
    except Exception as e:
        print(f"[HITL] ERROR setting status back: {e}")

    return feedback


def install():
    global original_func, is_patched
    if is_patched:
        print("[HITL] already patched, skipping")
        return

    from crewai.agents.crew_agent_executor import CrewAgentExecutor

    original_func = CrewAgentExecutor._ask_human_input
    CrewAgentExecutor._ask_human_input = ask_human_via_api
    is_patched = True
    print(f"[HITL] ✅ PATCH INSTALLED on CrewAgentExecutor._ask_human_input")
    print(f"[HITL]    original: {original_func}")
    print(f"[HITL]    patched:  {CrewAgentExecutor._ask_human_input}")


def uninstall():
    global original_func, is_patched
    if not is_patched or original_func is None:
        return

    from crewai.agents.crew_agent_executor import CrewAgentExecutor

    CrewAgentExecutor._ask_human_input = original_func
    original_func = None
    is_patched = False
    print("[HITL] Patch removed, original _ask_human_input restored")
