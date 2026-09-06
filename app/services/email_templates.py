from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from html import escape
from typing import Any


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _value(payload: dict[str, Any], key: str, default: str = "") -> str:
    value = payload.get(key)
    return str(value) if value not in (None, "") else default


def _render_message(
    *,
    subject: str,
    greeting: str,
    paragraphs: list[str],
    action_label: str | None,
    action_url: str | None,
    app_name: str,
) -> RenderedEmail:
    text_parts = [greeting, *paragraphs]
    if action_label and action_url:
        text_parts.extend((f"{action_label}: {action_url}",))
    text_parts.append(f"-- {app_name}")

    html_paragraphs = "".join(
        f'<p style="margin:0 0 14px;color:#263b36;line-height:1.55">{escape(part)}</p>'
        for part in paragraphs
    )
    action = ""
    if action_label and action_url:
        action = (
            '<p style="margin:24px 0">'
            f'<a href="{escape(action_url, quote=True)}" '
            'style="display:inline-block;background:#0d4d45;color:#fff;text-decoration:none;'
            'padding:11px 18px;border-radius:7px;font-weight:600">'
            f"{escape(action_label)}</a></p>"
        )
    html = (
        '<!doctype html><html><body style="margin:0;background:#f3f6f4;'
        'font-family:Arial,sans-serif">'
        '<div style="max-width:620px;margin:0 auto;padding:28px 16px">'
        '<div style="background:#0d4d45;color:#fff;padding:18px 24px;border-radius:10px 10px 0 0;'
        f'font-size:20px;font-weight:700">{escape(app_name)}</div>'
        '<div style="background:#fff;padding:26px 24px;border:1px solid #dce5e0;'
        'border-top:0;border-radius:0 0 10px 10px">'
        f'<h1 style="margin:0 0 20px;color:#0d4d45;font-size:22px">{escape(subject)}</h1>'
        f'<p style="margin:0 0 14px;color:#263b36">{escape(greeting)}</p>'
        f"{html_paragraphs}{action}"
        '<p style="margin:24px 0 0;color:#6a7b76;font-size:13px">'
        f"{escape(app_name)}</p></div></div></body></html>"
    )
    return RenderedEmail(subject=subject, text="\n\n".join(text_parts), html=html)


def _generic(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=_value(payload, "title", f"{context['app_name']} notification"),
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[_value(payload, "message", "You have a new update.")],
        action_label="Open BNC",
        action_url=context["frontend_url"],
        app_name=context["app_name"],
    )


def _invitation(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=f"You are invited to {context['app_name']}",
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[
            "Your BNC membership has been approved.",
            "Use the secure invitation link below to activate your account and set your password.",
        ],
        action_label="Activate account",
        action_url=_value(payload, "invite_url", context["frontend_url"]),
        app_name=context["app_name"],
    )


def _payment_approved(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=_value(payload, "title", "Contribution approved"),
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[
            _value(payload, "message", "Your contribution has been approved."),
            "Your official receipt is attached to this email.",
        ],
        action_label="View payments",
        action_url=context["frontend_url"],
        app_name=context["app_name"],
    )


def _payment_rejected(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=_value(payload, "title", "Contribution needs correction"),
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[_value(payload, "message", "Your contribution needs correction.")],
        action_label="Review and resubmit",
        action_url=context["frontend_url"],
        app_name=context["app_name"],
    )


def _announcement(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=_value(payload, "title", "BNC announcement"),
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[_value(payload, "message", "A new announcement was published.")],
        action_label="View announcements",
        action_url=context["frontend_url"],
        app_name=context["app_name"],
    )


def _reminder(payload: dict[str, Any], context: dict[str, str]) -> RenderedEmail:
    return _render_message(
        subject=_value(payload, "title", "Contribution reminder"),
        greeting=f"Hello {context['recipient_name']},",
        paragraphs=[_value(payload, "message", "Your monthly contribution is due.")],
        action_label="Add contribution",
        action_url=context["frontend_url"],
        app_name=context["app_name"],
    )


TemplateRenderer = Callable[[dict[str, Any], dict[str, str]], RenderedEmail]

_TEMPLATES: dict[str, TemplateRenderer] = {
    "invitation": _invitation,
    "payment_approved": _payment_approved,
    "payment_receipt": _payment_approved,
    "payment_rejected": _payment_rejected,
    "announcement_published": _announcement,
    "contribution_reminder": _reminder,
}


def render_email_template(
    template_key: str,
    payload: dict[str, Any],
    *,
    recipient_name: str,
    frontend_url: str,
    app_name: str,
) -> RenderedEmail:
    context = {
        "recipient_name": recipient_name.strip() or "BNC member",
        "frontend_url": frontend_url.rstrip("/"),
        "app_name": app_name.strip() or "BNC",
    }
    renderer = _TEMPLATES.get(template_key.strip().lower(), _generic)
    return renderer(payload, context)
