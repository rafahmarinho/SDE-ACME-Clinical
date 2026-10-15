"""Reports: generated in Python, stored as private CSV files, downloadable only through the API."""

import re
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from psycopg.types.json import Jsonb

from app.db import get_db
from app.errors import ApiError, forbidden, not_found
from app.schemas.requests import ReportIn
from app.security import authz, ratelimit
from app.security.auth import Principal, get_principal
from app.security.context import RequestContext, get_context
from app.security.crypto import sha256_hex
from app.services import audit, reports, supabase

router = APIRouter(prefix="/reports", tags=["reports"])


def _allowed_kinds(principal: Principal) -> list[str]:
    return [kind for kind, perm in authz.REPORT_KIND_PERMISSION.items() if principal.can(perm)]


@router.get("")
def list_reports(page_size: int = Query(default=50, ge=1, le=100), principal: Principal = Depends(get_principal),
                 conn: psycopg.Connection = Depends(get_db)) -> dict:
    kinds = _allowed_kinds(principal)
    rows = conn.execute(
        """select id, kind, title, params, deidentified, size_bytes, row_count, created_by_name, created_at
           from public.reports where kind = any(%s) order by created_at desc limit %s""",
        (kinds, page_size),
    ).fetchall()
    return {"items": rows, "kinds": kinds}


@router.post("", status_code=201)
def create_report(body: ReportIn, principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                  ctx: RequestContext = Depends(get_context)) -> dict:
    if body.kind not in _allowed_kinds(principal):
        audit.record(conn, "authz.denied", actor=principal, outcome="denied", details={"report": body.kind}, ctx=ctx)
        raise forbidden("Your role cannot generate this report.")
    ratelimit.hit(conn, f"report:{principal.id}", limit=20, window_seconds=3600)
    try:
        title, csv_bytes, summary, row_count = reports.build(conn, body.kind, body.period_hours, body.deidentified,
                                                             body.patient_id)
    except LookupError as exc:
        raise not_found("Patient") from exc
    except PermissionError as exc:
        raise ApiError(409, "restricted", "This patient's data is restricted from secondary use.") from exc
    report_id = uuid4()
    path = f"{report_id}.csv"
    supabase.storage_upload("reports", path, csv_bytes, "text/csv")
    params = {"period_hours": body.period_hours, "patient_id": str(body.patient_id) if body.patient_id else None}
    conn.execute(
        """insert into public.reports (id, kind, title, params, summary, deidentified, storage_path, size_bytes, sha256,
               row_count, created_by, created_by_name)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (report_id, body.kind, title, Jsonb(params), Jsonb(summary), body.deidentified, path, len(csv_bytes),
         sha256_hex(csv_bytes), row_count, principal.id, principal.full_name),
    )
    if body.kind in ("shift_summary", "patient_vitals") and not body.deidentified:
        conn.execute(
            """insert into public.integration_outbox (channel, recipient, subject, payload)
               values ('ehr', 'ehr-gateway', %s, %s)""",
            (f"{title} filed to EHR (simulated)", Jsonb({"report_id": str(report_id), "rows": row_count})),
        )
    audit.record(conn, "report.create", actor=principal, entity_type="report", entity_id=str(report_id),
                 details={"kind": body.kind, "deidentified": body.deidentified, "rows": row_count}, ctx=ctx)
    return {"id": report_id, "title": title, "row_count": row_count}


def _get_report(conn: psycopg.Connection, principal: Principal, report_id: UUID, ctx: RequestContext) -> dict:
    row = conn.execute("select * from public.reports where id = %s", (report_id,)).fetchone()
    if row is None:
        raise not_found("Report")
    if row["kind"] not in _allowed_kinds(principal):
        audit.record(conn, "authz.denied", actor=principal, outcome="denied", entity_type="report",
                     entity_id=str(report_id), ctx=ctx)
        raise forbidden()
    return row


@router.get("/{report_id}")
def report_detail(report_id: UUID, principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                  ctx: RequestContext = Depends(get_context)) -> dict:
    row = _get_report(conn, principal, report_id, ctx)
    return {k: row[k] for k in ("id", "kind", "title", "params", "summary", "deidentified", "size_bytes", "row_count",
                                "sha256", "created_by_name", "created_at")}


@router.get("/{report_id}/download")
def download(report_id: UUID, principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
             ctx: RequestContext = Depends(get_context)) -> Response:
    row = _get_report(conn, principal, report_id, ctx)
    data = supabase.storage_download("reports", row["storage_path"])
    if sha256_hex(data) != row["sha256"]:
        audit.record(conn, "report.integrity_failure", actor=principal, outcome="failure", entity_type="report",
                     entity_id=str(report_id), ctx=ctx)
        raise ApiError(409, "integrity_error", "The report file failed its integrity check and was not delivered.")
    audit.record(conn, "report.download", actor=principal, entity_type="report", entity_id=str(report_id), ctx=ctx)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", row["title"]).strip("-")[:80] or "report"
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"', "X-Content-SHA256": row["sha256"]},
    )
