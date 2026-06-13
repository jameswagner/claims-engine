from app.tasks.remittance import process_remittance_batch


def handler(event, context):
    # EventBridge Scheduler trigger — run a larger batch since interval is 1 min not 10s
    return process_remittance_batch(limit=300)
