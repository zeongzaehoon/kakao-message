from __future__ import annotations

from threading import Event
from collections.abc import Callable
from .models import Backend, Cancelled, Friend, Plan, Result, checkpoint
from .storage import Journal


def execute(plan: Plan, backend: Backend, journal: Journal, stop: Event,
            report: Callable[[Result], None]) -> list[Result]:
    plan.validate()
    if plan.live and backend.is_demo:
        raise ValueError("데모 모드에서는 실제 전송을 실행할 수 없습니다.")
    if plan.photos:
        # Reject an unsupported photo backend before sending any accompanying text.
        backend.validate_photos(plan.photos)
    output: list[Result] = []

    def emit(friend: Friend, state: str, detail: str) -> None:
        item = Result(friend, state, detail)
        output.append(item)
        report(item)

    # Each item has a separate durable reservation. A partial retry cannot resend
    # a successfully submitted text or photo; old text-only identities are preserved.
    parts = ([None] if plan.message.strip() else []) + list(plan.photos)
    for index, friend in enumerate(plan.recipients):
        if stop.is_set():
            emit(friend, "cancelled", "남은 작업을 중지했습니다.")
            break
        reserved = False
        send_entered = False
        submitted = skipped = 0
        all_confirmed = True
        photo_hash = None
        try:
            if not plan.live:
                backend.prepare(friend, plan.scope, stop)
                checkpoint(stop)
                emit(friend, "checked", f"대상 확인 완료 · 사진 {len(plan.photos)}장 · 입력/전송하지 않았습니다.")
            else:
                for photo in parts:
                    checkpoint(stop)
                    reserved = send_entered = False
                    photo_hash = photo.fingerprint if photo else None
                    reserved = journal.reserve(plan.scope, friend.key, plan.message, photo_hash)
                    if not reserved:
                        skipped += 1
                        all_confirmed &= journal.state(plan.scope, friend.key, plan.message, photo_hash) == "submitted"
                        continue
                    # Revalidate the recipient and existing draft before every item.
                    backend.prepare(friend, plan.scope, stop)
                    checkpoint(stop)
                    send_entered = True
                    if photo is None:
                        backend.send(friend, plan.message, plan.scope, stop)
                    else:
                        backend.send_photo(friend, photo, plan.scope, stop)
                    journal.finish(plan.scope, friend.key, plan.message, "submitted", photo_hash)
                    reserved = send_entered = False
                    submitted += 1
                state = "submitted" if submitted else "duplicate"
                detail = f"전송 실행 {submitted}건 · 기존 이력 {skipped}건 건너뜀 · 수신/읽음 여부는 확인하지 않습니다."
                if submitted and all_confirmed:
                    try:
                        backend.finish_recipient(friend, plan.scope, stop)
                    except Exception as exc:
                        emit(friend, state, detail + f"\n전송은 완료됐지만 창 닫기를 중단했습니다: {exc}")
                        break
                emit(friend, state, detail)
        except Exception as exc:
            if reserved:
                if send_entered:
                    journal.finish(plan.scope, friend.key, plan.message, "uncertain", photo_hash)
                else:
                    journal.release(plan.scope, friend.key, plan.message, photo_hash)
            state = "uncertain" if send_entered else ("cancelled" if isinstance(exc, Cancelled) else "failed")
            detail = f"{exc}\n이 대화방: 전송 실행 {submitted}건, 기존 이력 {skipped}건."
            emit(friend, state, detail)
            # Stop the entire batch on failure. Never retry a possible send.
            break
        if index + 1 < len(plan.recipients) and stop.wait(plan.interval):
            break
    return output
